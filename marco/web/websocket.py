"""WebSocket connection manager and observer bridge."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import WebSocket

from .observer import AnalysisObserver
from .state import AnalysisState

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        with contextlib.suppress(ValueError):
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict[str, Any]) -> None:
        message = json.dumps(data)
        stale: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                stale.append(connection)
        for conn in stale:
            with contextlib.suppress(ValueError):
                self.active_connections.remove(conn)


class WebSocketObserver:
    """Bridges synchronous orchestrator callbacks to async WebSocket broadcasts.

    The orchestrator runs in a background thread. This observer uses
    asyncio.run_coroutine_threadsafe() to push events into the FastAPI event loop.
    """

    def __init__(self, manager: ConnectionManager, state: AnalysisState, loop: asyncio.AbstractEventLoop):
        self._manager = manager
        self._state = state
        self._loop = loop

    def _broadcast(self, event: dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(self._manager.broadcast(event), self._loop)

    def on_binary_queued(self, name: str, depth: int) -> None:
        self._state.binary_queued(name, depth)
        self._broadcast({"type": "binary_queued", "name": name, "depth": depth})

    def on_binary_started(self, name: str, depth: int) -> None:
        self._state.binary_started(name, depth)
        self._broadcast({"type": "binary_started", "name": name, "depth": depth})

    def on_binary_completed(
        self,
        name: str,
        depth: int,
        node_count: int,
        edge_count: int,
        import_count: int,
        elapsed_s: float,
        discovered: list[str],
        edge_kind_counts: dict[str, int],
        xmod_edge_count: int = 0,
    ) -> None:
        self._state.binary_completed(
            name,
            depth,
            node_count,
            edge_count,
            import_count,
            elapsed_s,
            discovered,
            edge_kind_counts,
            xmod_edge_count,
        )
        self._broadcast(
            {
                "type": "binary_completed",
                "name": name,
                "depth": depth,
                "node_count": node_count,
                "edge_count": edge_count,
                "import_count": import_count,
                "elapsed_s": round(elapsed_s, 2),
                "discovered": discovered,
                "syscall_count": edge_kind_counts.get("SYSCALL", 0),
                "rpc_count": edge_kind_counts.get("RPC_CLIENT_CALL", 0),
                "secure_call_count": edge_kind_counts.get("SECURE_CALL", 0),
                "edge_kind_counts": edge_kind_counts,
                "xmod_edge_count": xmod_edge_count,
            }
        )

    def on_binary_error(self, name: str, depth: int, error: str) -> None:
        self._state.binary_error(name, depth, error)
        self._broadcast({"type": "binary_error", "name": name, "depth": depth, "error": error})

    def on_analysis_complete(self, elapsed_s: float, total_nodes: int, total_edges: int) -> None:
        self._state.analysis_complete(elapsed_s, total_nodes, total_edges)
        self._broadcast(
            {
                "type": "analysis_complete",
                "elapsed_s": round(elapsed_s, 2),
                "total_nodes": total_nodes,
                "total_edges": total_edges,
            }
        )

    def on_phase_started(self, phase: str) -> None:
        self._state.phase_started(phase)
        self._broadcast({"type": "phase_started", "phase": phase})

    def on_phase_progress(self, phase: str, current: int, total: int) -> None:
        self._state.phase_update(phase, current, total)
        self._broadcast({"type": "phase_progress", "phase": phase, "current": current, "total": total})

    def on_phase_complete(self, phase: str) -> None:
        self._state.phase_complete(phase)
        self._broadcast({"type": "phase_complete", "phase": phase})


# Ensure WebSocketObserver satisfies the protocol
assert isinstance(WebSocketObserver.__new__(WebSocketObserver), AnalysisObserver)  # type: ignore[arg-type]
