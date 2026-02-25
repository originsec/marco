"""REST API routes for marco web UI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .state import AnalysisState
from .websocket import ConnectionManager, WebSocketObserver

logger = logging.getLogger(__name__)

router = APIRouter()

# These are set by the server module during app creation
_state: AnalysisState | None = None
_manager: ConnectionManager | None = None
_config: dict[str, Any] = {}
_analysis_thread: threading.Thread | None = None
_cluster_cache: dict | None = None
_cluster_lock = threading.Lock()


def configure(state: AnalysisState, manager: ConnectionManager, config: dict[str, Any]) -> None:
    """Configure routes with shared state."""
    global _state, _manager, _config
    _state = state
    _manager = manager
    _config = config


class AnalyzeRequest(BaseModel):
    seed: list[str] | None = None
    search_paths: list[str] | None = None
    workers: int | None = None
    depth: int | None = None
    no_kernel: bool = False
    single_binary: bool = False
    prewalk: bool = False
    load_neo4j: bool = False
    no_neo4j: bool = False
    cache_dir: str = ".marco_cache"
    no_cache: bool = False
    symbol_store: str = ".marco_symbols"
    no_pdb: bool = False
    use_processes: bool = False
    only: list[str] | None = None


class CypherRequest(BaseModel):
    cypher: str


def _resolve_config():
    """Resolve a Config object from the current app config path."""
    from ..core.config import Config

    config = None
    config_path = _config.get("config_path")
    with contextlib.suppress(Exception):
        config = Config.discover(config_path)
    return config


@router.get("/api/state")
async def get_state() -> dict:
    """Return current analysis state."""
    if _state is None:
        return {"type": "state_snapshot", "running": False, "binaries": [], "aggregates": {}}
    return _state.get_snapshot()


@router.get("/api/runs")
async def get_runs() -> list[dict]:
    """Return previous analysis run directories."""
    output_dir = _config.get("output_dir", "output")
    runs = []
    output_path = Path(output_dir)
    if not output_path.exists():
        return runs

    for d in sorted(output_path.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        info: dict[str, Any] = {"id": d.name, "path": str(d)}
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
                info["module_count"] = len(manifest)
            except Exception:
                pass
        # Check for nodes/edges files
        nodes_path = d / "nodes.jsonl"
        edges_path = d / "edges.jsonl"
        info["has_nodes"] = nodes_path.exists()
        info["has_edges"] = edges_path.exists()
        runs.append(info)

    return runs


@router.get("/api/runs/{run_id}/manifest")
async def get_run_manifest(run_id: str) -> dict:
    """Return manifest for a completed run."""
    output_dir = _config.get("output_dir", "output")
    manifest_path = Path(output_dir) / run_id / "manifest.json"
    if not manifest_path.exists():
        return {"error": "manifest not found"}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/runs/{run_id}/dependencies")
async def get_run_dependencies(run_id: str) -> dict:
    """Return dependency graph data for a run."""
    output_dir = _config.get("output_dir", "output")
    run_path = Path(output_dir) / run_id

    # Try to read dependency data from manifest
    manifest_path = run_path / "manifest.json"
    if not manifest_path.exists():
        return {"modules": [], "edges": []}

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        modules = [{"name": entry["module"], "path": entry.get("path", "")} for entry in manifest.values()]
        return {"modules": modules, "edges": []}
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/analyze")
async def start_analysis(request: AnalyzeRequest) -> dict:
    """Start a new analysis run."""
    global _analysis_thread, _cluster_cache

    if _state is None or _manager is None:
        return {"error": "server not initialized"}

    if _state.running:
        return {"error": "analysis already running"}

    if not request.seed and not request.only:
        return {"error": "either seed or only list must be provided"}

    _state.reset()
    with _cluster_lock:
        _cluster_cache = None  # Invalidate cluster cache for new analysis

    loop = asyncio.get_event_loop()
    observer = WebSocketObserver(_manager, _state, loop)

    def _run() -> None:
        try:
            from ..main import analyze_command

            config = _resolve_config()

            binaries = request.only if request.only else (request.seed or [])

            analyze_command(
                binaries=binaries,
                search_paths=request.search_paths or [],
                output_dir=_config.get("output_dir", "output"),
                log_level=_config.get("log_level", "INFO"),
                load_neo4j=request.load_neo4j,
                no_neo4j=request.no_neo4j,
                workers=request.workers,
                single_binary=request.single_binary,
                prewalk=request.prewalk,
                no_kernel=request.no_kernel,
                only_binaries=request.only,
                depth=request.depth,
                config=config,
                cache_dir=request.cache_dir,
                no_cache=request.no_cache,
                symbol_store=request.symbol_store,
                no_pdb=request.no_pdb,
                use_processes=request.use_processes,
                observer=observer,
            )
        except Exception:
            logger.exception("Analysis failed")
            if _state:
                _state.running = False
            observer.on_analysis_complete(0.0, 0, 0)

    _analysis_thread = threading.Thread(target=_run, daemon=True, name="marco-analysis")
    _analysis_thread.start()

    return {"status": "started"}


def _json_safe(val: Any) -> Any:
    """Convert a value to JSON-serializable form."""
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    if isinstance(val, (list, tuple)):
        return [_json_safe(v) for v in val]
    if isinstance(val, dict):
        return {str(k): _json_safe(v) for k, v in val.items()}
    return str(val)


def _extract_graph_data(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Extract nodes and relationships from Neo4j query results for graph visualization."""
    try:
        from neo4j.graph import Node, Path, Relationship
    except ImportError:
        return None

    nodes: dict[str, dict[str, Any]] = {}
    links: dict[str, dict[str, Any]] = {}

    def visit(val: Any) -> None:
        if isinstance(val, Node):
            eid = val.element_id
            if eid not in nodes:
                props = {k: _json_safe(v) for k, v in dict(val).items()}
                labels = list(val.labels)
                name = (
                    props.get("name")
                    or props.get("symbol")
                    or props.get("title")
                    or (labels[0] if labels else str(eid))
                )
                nodes[eid] = {"id": eid, "labels": labels, "properties": props, "name": str(name)}
        elif isinstance(val, Relationship):
            visit(val.start_node)
            visit(val.end_node)
            eid = val.element_id
            if eid not in links:
                props = {k: _json_safe(v) for k, v in dict(val).items()}
                links[eid] = {
                    "id": eid,
                    "source": val.start_node.element_id,
                    "target": val.end_node.element_id,
                    "type": val.type,
                    "properties": props,
                }
        elif isinstance(val, Path):
            for node in val.nodes:
                visit(node)
            for rel in val.relationships:
                visit(rel)
        elif isinstance(val, list):
            for item in val:
                visit(item)

    for rec in records:
        for v in rec.values():
            visit(v)

    if not nodes:
        return None

    return {
        "nodes": list(nodes.values()),
        "links": [link for link in links.values() if link["source"] in nodes and link["target"] in nodes],
    }


def _serialize_table_value(val: Any) -> Any:
    """Convert a Neo4j value to a readable table cell."""
    try:
        from neo4j.graph import Node, Path, Relationship
    except ImportError:
        return str(val) if hasattr(val, "__dict__") else val

    if isinstance(val, Node):
        props = dict(val)
        module = props.get("module", "")
        name = props.get("name") or props.get("symbol") or props.get("title") or ""
        if module and name:
            return module + ":" + name
        if name:
            return name
        labels = list(val.labels)
        return (":" + ":".join(labels)) if labels else str(val.element_id)
    if isinstance(val, Relationship):
        return val.type
    if isinstance(val, Path):
        parts = []
        for node in val.nodes:
            p = dict(node)
            parts.append(p.get("name") or p.get("symbol") or str(node.element_id))
        return " \u2192 ".join(parts)
    if hasattr(val, "__dict__"):
        return str(val)
    return val


@router.post("/api/neo4j/query")
async def neo4j_query(request: CypherRequest) -> dict:
    """Proxy a Cypher query to Neo4j."""
    try:
        from ..core.config import get_neo4j_credentials
        from ..io.neo4j_loader import Neo4jLoader

        uri, user, password = get_neo4j_credentials(_resolve_config())

        loader = Neo4jLoader(uri, user, password)
        records = loader.query(request.cypher)
        loader.close()

        if not records:
            return {"columns": [], "rows": []}

        columns = list(records[0].keys())
        rows = []
        for rec in records:
            row = []
            for col in columns:
                row.append(_serialize_table_value(rec[col]))
            rows.append(row)

        result: dict[str, Any] = {"columns": columns, "rows": rows}
        graph = _extract_graph_data(records)
        if graph:
            result["graph"] = graph
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/neo4j/status")
async def neo4j_status() -> dict:
    """Check Neo4j connection status."""
    try:
        from ..core.config import get_neo4j_credentials
        from ..io.neo4j_loader import Neo4jLoader

        uri, user, password = get_neo4j_credentials(_resolve_config())

        Neo4jLoader.verify_connection(uri, user, password)
        return {"connected": True, "uri": uri}
    except SystemExit as e:
        return {"connected": False, "error": str(e)}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/api/clusters/compute")
def compute_clusters() -> dict:
    """Compute module clusters from Neo4j call graph via export-centric TF-IDF + Leiden.

    Results are cached after the first successful computation.
    Cache is cleared when a new analysis completes.
    """
    global _cluster_cache

    with _cluster_lock:
        if _cluster_cache is not None:
            return _cluster_cache

    try:
        from ..analysis.clusters import compute_module_clusters
        from ..core.config import get_neo4j_credentials
        from ..io.neo4j_loader import Neo4jLoader

        config = _resolve_config()
        uri, user, password = get_neo4j_credentials(config)

        def _get_key(key: str, default: str) -> str:
            if config:
                return config.get_with_env_fallback(key, default) or default
            return os.getenv(key, default)

        anthropic_key = _get_key("ANTHROPIC_API_KEY", "")

        loader = Neo4jLoader(uri, user, password)
        try:
            result = compute_module_clusters(loader, anthropic_api_key=anthropic_key or None)
        finally:
            loader.close()

        with _cluster_lock:
            _cluster_cache = result
        return result
    except ImportError as e:
        return {"error": str(e)}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/dependency-graph")
async def get_dependency_graph() -> dict:
    """Return current dependency graph from live analysis state."""
    if _state is None:
        return {"modules": [], "edges": []}

    modules = []
    edges = []
    seen_modules = set()

    for entry in _state.binaries.values():
        modules.append(
            {
                "name": entry.name,
                "depth": entry.depth,
                "status": entry.status.value,
                "node_count": entry.node_count,
                "edge_count": entry.edge_count,
                "edge_kind_counts": entry.edge_kind_counts,
                "xmod_edge_count": entry.xmod_edge_count,
            }
        )
        seen_modules.add(entry.name.lower())

        for dep in entry.discovered:
            edges.append({"source": entry.name.lower(), "target": dep.lower()})

    return {"modules": modules, "edges": edges}
