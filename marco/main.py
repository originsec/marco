"""Main entry point for marco."""

from __future__ import annotations

import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

signal.signal(signal.SIGINT, lambda s, f: os._exit(1))

from .cli import build_parser  # noqa: E402
from .core.config import Config, get_neo4j_credentials  # noqa: E402
from .core.helpers import resolve_file_path, sanitize_for_fs  # noqa: E402
from .core.rpc_registry import RPCRegistry  # noqa: E402
from .io.jsonl_writer import JsonlWriter  # noqa: E402
from .io.manifest import Manifest  # noqa: E402
from .io.neo4j_loader import Neo4jLoader  # noqa: E402
from .pipeline.orchestrator import AnalysisOrchestrator  # noqa: E402

_PREWALK_DEPTH = 1
_PREWALK_LIMIT = 200


def _neo4j_credentials_configured(config: Config | None) -> bool:
    """Return True if any Neo4j credential is explicitly set in config or environment."""
    for key in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        if config and config.get(key):
            return True
        if os.getenv(key):
            return True
    return False


def analyze_command(
    binaries: list[str],
    search_paths: list[str],
    output_dir: str,
    log_level: str,
    load_neo4j: bool,
    no_neo4j: bool = False,
    workers: int | None = None,
    single_binary: bool = False,
    prewalk: bool = False,
    no_kernel: bool = False,
    rpc_registry_file: str | None = None,
    only_binaries: list[str] | None = None,
    depth: int | None = None,
    config: Config | None = None,
    cache_dir: str = ".marco_cache",
    no_cache: bool = False,
    symbol_store: str = ".marco_symbols",
    no_pdb: bool = False,
    use_processes: bool = False,
    observer=None,
) -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="[%(asctime)s][%(levelname)s] %(message)s",
    )

    prewalk_depth = _PREWALK_DEPTH
    prewalk_limit = _PREWALK_LIMIT

    neo4j_uri, neo4j_user, neo4j_password = get_neo4j_credentials(config)

    credentials_configured = _neo4j_credentials_configured(config)
    should_load = (load_neo4j or credentials_configured) and not no_neo4j

    if should_load:
        logging.info("Verifying Neo4j connection...")
        Neo4jLoader.verify_connection(neo4j_uri, neo4j_user, neo4j_password)
        logging.info("Neo4j connection verified successfully.")
    elif not no_neo4j and not credentials_configured:
        logging.info(
            "Tip: set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD "
            "to automatically load results into Neo4j after analysis."
        )

    effective_cache_dir = None if no_cache else cache_dir
    effective_symbol_store = None if no_pdb else symbol_store

    if effective_cache_dir:
        Path(effective_cache_dir).mkdir(parents=True, exist_ok=True)
    if effective_symbol_store:
        Path(effective_symbol_store).mkdir(parents=True, exist_ok=True)

    # Initialize Binary Ninja adapter (tuning parameters from environment variables only)
    from .core.binja_discovery import ensure_binaryninja_importable

    ensure_binaryninja_importable()
    try:
        from .disassemblers.binaryninja_adapter import BinaryNinjaAdapter
        from .extractors.calls import CallsExtractor
        from .extractors.rpc_client import RPCClientExtractor
        from .extractors.rpc_server import RPCServerExtractor
        from .extractors.secure_call import SecureCallsExtractor
        from .extractors.syscall import SyscallsExtractor

        _bn_mfs = os.getenv("BN_MAX_FUNCTION_SIZE")
        bn_max_function_size = int(_bn_mfs) if _bn_mfs else None
        _bn_mfuc = os.getenv("BN_MAX_FUNCTION_UPDATE_COUNT")
        bn_max_function_update_count = int(_bn_mfuc) if _bn_mfuc else None
        bn_linear_sweep_permissive = os.getenv("BN_LINEAR_SWEEP_PERMISSIVE", "").lower() in ("1", "true", "yes")

        adapter = BinaryNinjaAdapter(
            linear_sweep_permissive=bn_linear_sweep_permissive,
            max_function_size=bn_max_function_size,
            max_function_update_count=bn_max_function_update_count,
            cache_dir=effective_cache_dir,
            symbol_store=effective_symbol_store,
        )
    except ModuleNotFoundError as e:
        raise SystemExit(
            "Binary Ninja Python API is not installed.\n"
            "Run <binja>/scripts/install_api.py, or set BINJA_PATH to your Binary Ninja python/ directory."
        ) from e

    extractors = [
        CallsExtractor(),
        SyscallsExtractor(),
        SecureCallsExtractor(),
        RPCClientExtractor(),
        RPCServerExtractor(),
    ]

    rpc_registry = RPCRegistry.load_from_file(Path(rpc_registry_file)) if rpc_registry_file else RPCRegistry()

    if log_level.upper() == "DEBUG":
        for logger_name in ["marco.extractors.rpc_client", "marco.extractors.rpc_server", "marco.core.rpc_registry"]:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)

    if only_binaries:
        seed_module = f"only_{len(only_binaries)}_binaries"
        seed_version = "batch"
    else:
        seed = binaries[0] if binaries else "seed"
        try:
            seed_resolved = resolve_file_path(seed, search_paths)
        except Exception:
            seed_resolved = seed

        seed_module = os.path.basename(seed_resolved).lower() or "seed"
        seed_version = None

        try:
            with adapter.open_binary(seed_resolved) as seed_bv:
                try:
                    if hasattr(adapter, "get_file_version"):
                        seed_version = adapter.get_file_version(seed_bv)
                except Exception:
                    pass
        except Exception:
            pass

        seed_version = seed_version or "unknown"

    dir_module = sanitize_for_fs(seed_module)
    dir_version = sanitize_for_fs(seed_version)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run_dir_name = f"{dir_module}_{dir_version}_{timestamp}"
    run_output_dir = os.path.join(output_dir, run_dir_name)

    Path(run_output_dir).mkdir(parents=True, exist_ok=True)
    nodes_path = os.path.join(run_output_dir, "nodes.jsonl")
    edges_path = os.path.join(run_output_dir, "edges.jsonl")
    manifest_path = os.path.join(run_output_dir, "manifest.json")

    writer = JsonlWriter(nodes_path, edges_path, manifest_path)
    manifest = Manifest(manifest_path)

    if only_binaries:
        logging.info(f"Using --only mode with {len(only_binaries)} specified binaries")
        binaries = only_binaries
        single_binary = True  # Disable dependency walking

    if depth == 1:
        logging.info("Using depth=1 (equivalent to single-binary mode)")
        single_binary = True

    max_workers = workers if workers and workers > 0 else max(1, os.cpu_count() or 1)
    logging.info(f"Beginning analysis with up to {max_workers} workers")

    orchestrator = AnalysisOrchestrator(
        binaries=binaries,
        search_paths=search_paths,
        output_dir=run_output_dir,
        adapter=adapter,
        extractors=extractors,
        rpc_registry=rpc_registry,
        max_workers=max_workers,
        single_binary=single_binary,
        depth=depth,
        no_kernel=no_kernel,
        use_processes=use_processes,
        bn_linear_sweep_permissive=bn_linear_sweep_permissive,
        bn_max_function_size=bn_max_function_size,
        bn_max_function_update_count=bn_max_function_update_count,
        cache_dir=effective_cache_dir,
        symbol_store=effective_symbol_store,
    )

    if observer is not None:
        orchestrator.observer = observer

    orchestrator.initialize_work_queue()

    if prewalk and not single_binary:
        _run_prewalk(orchestrator, binaries, search_paths, prewalk_depth, prewalk_limit, depth, no_kernel)

    orchestrator.manifest = manifest
    orchestrator.run_analysis(writer, manifest)

    if rpc_registry and not orchestrator.interrupted:
        final_edges = rpc_registry.get_all_edges(final=True)
        if final_edges:
            logging.info(f"Writing {len(final_edges)} unresolved RPC edges")
            for edge in final_edges:
                writer.write_edge(edge)

    writer.close()

    if rpc_registry:
        final_rpc_path = os.path.join(run_output_dir, "rpc_registry_final.json")
        rpc_registry.save_to_file(Path(final_rpc_path))

        unresolved_path = os.path.join(run_output_dir, "rpc_unresolved.json")
        rpc_registry.export_unresolved_edges(Path(unresolved_path))

        stats = rpc_registry.get_statistics()
        logging.info(
            f"RPC Analysis: {stats['registered_interfaces']} interfaces, "
            f"{stats['total_procedures']} procedures, "
            f"{stats['resolved_edges']} resolved edges, "
            f"{stats['unresolved_edges']} unresolved edges"
        )

    dep_md_path = os.path.join(run_output_dir, "dependencies.md")
    orchestrator.dependency_tracker.generate_mermaid_diagram(dep_md_path)

    if should_load and not orchestrator.interrupted:
        logging.info("Sending data to Neo4j...")
        if observer:
            observer.on_phase_started("neo4j")

        def _neo4j_progress(phase: str, current: int, total: int) -> None:
            if observer:
                observer.on_phase_progress(phase, current, total)

        loader = Neo4jLoader(neo4j_uri, neo4j_user, neo4j_password)
        loader.load_jsonl(nodes_path, edges_path, progress_callback=_neo4j_progress)
        loader.close()
        logging.info("Data loaded into Neo4j successfully!")
        if observer:
            observer.on_phase_complete("neo4j")
    elif should_load and orchestrator.interrupted:
        logging.info("Skipping Neo4j load due to user interrupt")


def _run_prewalk(
    orchestrator: AnalysisOrchestrator,
    binaries: list[str],
    search_paths: list[str],
    prewalk_depth: int,
    prewalk_limit: int,
    depth: int | None,
    no_kernel: bool,
) -> None:
    """Run pre-walk to seed work queue with dependencies."""
    try:
        import pefile
    except Exception:
        logging.debug("pefile not available; skipping pre-walk seeding")
        return

    from .disassemblers.binaryninja_adapter import _resolve_module_name

    def _imports_for(path: str) -> list[str]:
        try:
            pe = pefile.PE(path, fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            names = []
            if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
                for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
                    dll_name = getattr(entry, "dll", None)
                    if isinstance(dll_name, bytes):
                        try:
                            dll_name = dll_name.decode("utf-8", errors="ignore")
                        except Exception:
                            dll_name = None
                    if isinstance(dll_name, str) and dll_name:
                        names.append(_resolve_module_name(dll_name))
            return names
        except Exception:
            return []

    try:
        frontier = [(s, 0) for s in binaries]
        additions = 0
        effective_prewalk_depth = min(prewalk_depth, depth) if depth is not None else prewalk_depth

        while frontier and additions < prewalk_limit:
            current, cur_depth = frontier.pop(0)
            if cur_depth >= max(0, effective_prewalk_depth):
                continue

            try:
                cur_path = resolve_file_path(current, search_paths)
            except Exception:
                continue

            for imp in _imports_for(cur_path):
                if no_kernel and orchestrator._is_kernel_module(imp):
                    continue

                k = imp.lower()
                if k not in orchestrator.seen:
                    orchestrator.seen.add(k)
                    orchestrator.work_q.put((imp, cur_depth + 1))
                    additions += 1
                    if additions >= prewalk_limit:
                        break
                    frontier.append((imp, cur_depth + 1))

            current_lower = current.lower()
            base_name = current_lower.rsplit(".", 1)[0] if "." in current_lower else current_lower

            if base_name == "ntdll" and not no_kernel:
                kernel = "ntoskrnl.exe"
                k = kernel.lower()
                if k not in orchestrator.seen:
                    orchestrator.seen.add(k)
                    orchestrator.work_q.put((kernel, cur_depth + 1))
                    additions += 1
                    logging.info("Auto-added ntoskrnl.exe (syscall target for ntdll)")

            if base_name == "ntoskrnl":
                secure = "securekernel.exe"
                k = secure.lower()
                if k not in orchestrator.seen:
                    orchestrator.seen.add(k)
                    orchestrator.work_q.put((secure, cur_depth + 1))
                    additions += 1
                    logging.info("Auto-added securekernel.exe (secure call target for ntoskrnl)")

        if additions > 0:
            logging.info(
                f"Pre-walk seeded {additions} additional binaries "
                f"(depth={effective_prewalk_depth}, limit={prewalk_limit})"
            )
    except Exception as e:
        logging.debug(f"Pre-walk failed: {e}")


def main():
    """Main entry point — starts the web UI server."""
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(asctime)s][%(levelname)s] %(message)s",
    )

    from .web.server import run_server

    server_config = {
        "output_dir": args.output,
        "config_path": args.config,
        "log_level": args.log_level,
    }

    run_server(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        config=server_config,
    )


if __name__ == "__main__":
    main()
