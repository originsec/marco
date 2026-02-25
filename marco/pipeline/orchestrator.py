"""Multi-binary analysis orchestrator."""

from __future__ import annotations

import concurrent.futures
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

from ..core.helpers import compute_sha256, resolve_file_path
from ..core.rpc_registry import RPCRegistry
from ..io.jsonl_writer import JsonlWriter
from ..io.manifest import Manifest, ManifestEntry
from ..pipeline.dependency_tracker import DependencyTracker
from ..web.observer import AnalysisObserver
from .processor import process_binary, process_binary_subprocess

logger = logging.getLogger(__name__)

WORK_QUEUE_MAXSIZE = 10_000
WORKER_WAIT_TIMEOUT_S = 600
FUTURE_RESULT_TIMEOUT_S = 900


class AnalysisOrchestrator:
    def __init__(
        self,
        binaries: list[str],
        search_paths: list[str],
        output_dir: str,
        adapter: Any,
        extractors: list[Any],
        rpc_registry: RPCRegistry,
        max_workers: int,
        single_binary: bool = False,
        depth: int | None = None,
        no_kernel: bool = False,
        use_processes: bool = False,
        bn_linear_sweep_permissive: bool = False,
        bn_max_function_size: int | None = None,
        bn_max_function_update_count: int | None = None,
        cache_dir: str | None = None,
        symbol_store: str | None = None,
    ):
        self.binaries = binaries
        self.search_paths = search_paths
        self.output_dir = output_dir
        self.adapter = adapter
        self.extractors = extractors
        self.rpc_registry = rpc_registry
        self.max_workers = max_workers
        self.single_binary = single_binary
        self.depth = depth
        self.no_kernel = no_kernel
        self.use_processes = use_processes
        self.bn_linear_sweep_permissive = bn_linear_sweep_permissive
        self.bn_max_function_size = bn_max_function_size
        self.bn_max_function_update_count = bn_max_function_update_count
        self.cache_dir = cache_dir
        self.symbol_store = symbol_store

        self.work_q: queue.Queue[tuple[str, int]] = queue.Queue(maxsize=WORK_QUEUE_MAXSIZE)
        self.seen: set[str] = set()
        self._lock = threading.Lock()
        self.dependency_tracker = DependencyTracker()
        self.interrupted = False
        self.manifest: Manifest | None = None
        self.observer: AnalysisObserver | None = None
        self._total_nodes: int = 0
        self._total_edges: int = 0

    def _enqueue_work(self, item: tuple[str, int]) -> None:
        try:
            self.work_q.put_nowait(item)
        except queue.Full:
            logger.warning("Work queue full (maxsize=%d), dropping %s", self.work_q.maxsize, item[0])

    def _try_enqueue(self, module: str, depth: int) -> bool:
        """Enqueue module if not already seen. Returns True if enqueued."""
        with self._lock:
            if module.lower() in self.seen:
                return False
            self.seen.add(module.lower())
        self._enqueue_work((module, depth))
        if self.observer:
            self.observer.on_binary_queued(module, depth)
        return True

    def initialize_work_queue(self) -> None:
        for b in self.binaries:
            key = b.lower()
            if self.no_kernel and self._is_kernel_module(key):
                logger.info(f"Skipping '{b}' due to --no-kernel")
                if self.observer:
                    self.observer.on_binary_error(b, 0, "kernel module skipped")
                continue
            with self._lock:
                if key not in self.seen:
                    self.seen.add(key)
                else:
                    continue
            self._enqueue_work((b, 0))
            if self.observer:
                self.observer.on_binary_queued(b, 0)

    def run_analysis(
        self,
        writer: JsonlWriter,
        manifest: Manifest,
    ) -> None:
        analysis_start = time.perf_counter()
        futures: set[concurrent.futures.Future] = set()

        if not self.use_processes and self.max_workers > 1:
            logger.warning(
                "Using thread mode with %d workers. Binary Ninja analysis is serialized "
                "by a global lock in thread mode, so workers > 1 provides no speedup. "
                "Consider using --use-processes for true parallelism.",
                self.max_workers,
            )

        try:
            if self.use_processes:
                executor = concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers)
            else:
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)

            with executor:
                self._submit_initial_work(executor, futures)

                while futures:
                    done, _ = concurrent.futures.wait(
                        futures, timeout=WORKER_WAIT_TIMEOUT_S, return_when=concurrent.futures.FIRST_COMPLETED
                    )

                    if not done:
                        logger.warning(
                            "No workers completed in %ds (%d still running). "
                            "Workers may be hung; continuing to wait...",
                            WORKER_WAIT_TIMEOUT_S,
                            len(futures),
                        )
                        continue

                    for fut in done:
                        futures.discard(fut)
                        self._handle_completed_future(fut, writer, manifest, executor, futures)

        except KeyboardInterrupt:
            self.interrupted = True
            logger.warning("Interrupted by user (Ctrl+C). Cancelling remaining analysis...")
        finally:
            total_elapsed = time.perf_counter() - analysis_start
            if self.interrupted:
                logger.info(f"Analysis interrupted after {total_elapsed:.2f}s")
            else:
                logger.info(f"Analysis complete in {total_elapsed:.2f}s")
            if self.observer:
                self.observer.on_analysis_complete(total_elapsed, self._total_nodes, self._total_edges)

    def _submit_initial_work(
        self,
        executor: concurrent.futures.Executor,
        futures: set[concurrent.futures.Future],
    ) -> None:
        while len(futures) < self.max_workers and not self.work_q.empty():
            try:
                target, current_depth = self.work_q.get_nowait()
            except queue.Empty:
                break

            fut = self._submit_binary(executor, target, current_depth)
            if fut:
                futures.add(fut)

    def _submit_binary(
        self,
        executor: concurrent.futures.Executor,
        target: str,
        current_depth: int,
    ) -> concurrent.futures.Future | None:
        from ..disassemblers.binaryninja_adapter import _resolve_module_name

        resolved_target = _resolve_module_name(target)

        try:
            candidate_path = resolve_file_path(resolved_target, self.search_paths)
            sha = compute_sha256(candidate_path)
            if self.manifest is not None and self.manifest.has_sha(sha):
                logger.info(f"Skipping {target} (already processed)")
                if self.observer:
                    self.observer.on_binary_error(target, current_depth, "already processed")
                return None
        except FileNotFoundError:
            logger.info(f"Skipping {target} (not found)")
            if self.observer:
                self.observer.on_binary_error(target, current_depth, "not found")
            return None
        except Exception:
            logger.debug("SHA check failed for %s, proceeding with analysis", target, exc_info=True)

        logger.info(f"Analyzing {target} (depth={current_depth})...")
        if self.observer:
            self.observer.on_binary_started(target, current_depth)

        if self.use_processes:
            fut = executor.submit(
                process_binary_subprocess,
                resolved_target,
                self.search_paths,
                self.bn_linear_sweep_permissive,
                self.bn_max_function_size,
                self.bn_max_function_update_count,
                self.cache_dir,
                self.symbol_store,
            )
        else:
            fut = executor.submit(
                process_binary,
                resolved_target,
                self.search_paths,
                self.adapter,
                self.extractors,
                self.rpc_registry,
            )

        fut._target_name = target
        fut._current_depth = current_depth
        fut._start_time = time.perf_counter()

        return fut

    def _handle_completed_future(
        self,
        fut: concurrent.futures.Future,
        writer: JsonlWriter,
        manifest: Manifest,
        executor: concurrent.futures.Executor,
        futures: set[concurrent.futures.Future],
    ) -> None:
        target = getattr(fut, "_target_name", "<unknown>")
        current_depth = getattr(fut, "_current_depth", 0)

        try:
            result = fut.result(timeout=FUTURE_RESULT_TIMEOUT_S)

            if self.use_processes:
                nodes, edges, discovered, rpc_data = result
                self._merge_rpc_data(rpc_data)
            else:
                nodes, edges, discovered = result

            started = getattr(fut, "_start_time", None)
            elapsed = time.perf_counter() - started if started else 0.0
            if started:
                logger.info(
                    f"Finished {target} in {elapsed:.2f}s "
                    f"(nodes={len(nodes)}, edges={len(edges)}, imports={len(discovered)})"
                )

            if self.observer:
                edge_kind_counts: dict[str, int] = {}
                xmod_edge_count = 0
                for e in edges:
                    edge_kind_counts[e.kind] = edge_kind_counts.get(e.kind, 0) + 1
                    src_mod = e.src.split("!", 1)[0] if "!" in e.src else ""
                    dst_mod = e.dst.split("!", 1)[0] if "!" in e.dst else ""
                    if src_mod != dst_mod:
                        xmod_edge_count += 1
                self.observer.on_binary_completed(
                    name=target,
                    depth=current_depth,
                    node_count=len(nodes),
                    edge_count=len(edges),
                    import_count=len(discovered),
                    elapsed_s=elapsed,
                    discovered=list(discovered),
                    edge_kind_counts=edge_kind_counts,
                    xmod_edge_count=xmod_edge_count,
                )

            with self._lock:
                self._total_nodes += len(nodes)
                self._total_edges += len(edges)

            for n in nodes:
                writer.write_node(n)
            for e in edges:
                writer.write_edge(e)

            try:
                resolved_path = resolve_file_path(target, self.search_paths)
                sha = compute_sha256(resolved_path)
                file_version = self._extract_file_version(nodes)

                entry = ManifestEntry(
                    module=target.lower(),
                    path=resolved_path,
                    sha256=sha,
                    file_version=file_version,
                )
                manifest.add(entry)
                manifest.save()

                self.dependency_tracker.add_module(target.lower())
            except Exception:
                logger.warning("Failed to update manifest for %s", target, exc_info=True)

            self.dependency_tracker.add_dependencies(target.lower(), discovered)

            target_base = target.lower().rsplit(".", 1)[0] if "." in target.lower() else target.lower()

            # Auto-follow kernel chain: ntdll → ntoskrnl → securekernel
            auto_follow = []
            if target_base == "ntdll" and not self.no_kernel:
                auto_follow.append("ntoskrnl.exe")
            if target_base == "ntoskrnl":
                auto_follow.append("securekernel.exe")
            for extra in auto_follow:
                if self._try_enqueue(extra, current_depth + 1):
                    logger.info(f"Auto-added {extra} from {target_base}")

            if not self.single_binary and (self.depth is None or current_depth < self.depth):
                next_depth = current_depth + 1
                for mod in discovered:
                    if self.no_kernel and self._is_kernel_module(mod.lower()):
                        continue
                    self._try_enqueue(mod, next_depth)

        except concurrent.futures.TimeoutError:
            logger.error("Analysis of %s timed out after %ds", target, FUTURE_RESULT_TIMEOUT_S)
            if self.observer:
                self.observer.on_binary_error(target, current_depth, f"timed out after {FUTURE_RESULT_TIMEOUT_S}s")
        except FileNotFoundError as e:
            logger.warning(f"Skipping {target}: {e}")
            if self.observer:
                self.observer.on_binary_error(target, current_depth, str(e))
        except Exception as e:
            logger.exception(f"Error analyzing {target}: {e}")
            if self.observer:
                self.observer.on_binary_error(target, current_depth, str(e))

        self._submit_more_work(executor, futures)

    def _submit_more_work(
        self,
        executor: concurrent.futures.Executor,
        futures: set[concurrent.futures.Future],
    ) -> None:
        while len(futures) < self.max_workers and not self.work_q.empty():
            try:
                target, current_depth = self.work_q.get_nowait()
            except queue.Empty:
                break

            fut = self._submit_binary(executor, target, current_depth)
            if fut:
                futures.add(fut)

    def _merge_rpc_data(self, rpc_data: dict) -> None:
        if not self.rpc_registry or not rpc_data:
            return

        from ..core.rpc_models import RPCClientCall, RPCInterface, RPCProcedure

        for _iid, iface_data in rpc_data.get("interfaces", {}).items():
            procedures = {}
            for opnum, proc_data in iface_data.get("procedures", {}).items():
                procedures[int(opnum)] = RPCProcedure(
                    opnum=proc_data["opnum"],
                    address=proc_data["address"],
                    symbol=proc_data["symbol"],
                    function_name=proc_data["function_name"],
                )
            interface = RPCInterface(
                interface_id=iface_data["interface_id"],
                server_binary=iface_data["server_binary"],
                registration_function=iface_data["registration_function"],
                registration_api=iface_data["registration_api"],
                procedures=procedures,
                structure_address=iface_data.get("structure_address", 0),
            )
            self.rpc_registry.register_interface(interface)

        for cc_data in rpc_data.get("pending_clients", []):
            client_call = RPCClientCall(
                client_function=cc_data["client_function"],
                client_address=cc_data["client_address"],
                call_address=cc_data["call_address"],
                interface_id=cc_data["interface_id"],
                opnum=cc_data["opnum"],
                rpc_api=cc_data["rpc_api"],
            )
            self.rpc_registry.register_client_call(client_call)

    def _extract_file_version(self, nodes: list[Any]) -> str | None:
        try:
            for n in nodes:
                if n.props and "file_version" in n.props:
                    return str(n.props["file_version"]) if n.props["file_version"] else None
        except Exception:
            logger.debug("Failed to extract file version from nodes", exc_info=True)
        return None

    @staticmethod
    def _is_kernel_module(name: str) -> bool:
        try:
            base = Path(name).name.lower()
            if base.endswith((".dll", ".sys", ".exe")):
                base = base.rsplit(".", 1)[0]
            return base == "ntoskrnl"
        except Exception:
            return False
