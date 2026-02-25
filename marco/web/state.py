"""In-memory analysis state tracking."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class BinaryStatus(str, Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class BinaryEntry:
    name: str
    depth: int
    status: BinaryStatus = BinaryStatus.QUEUED
    node_count: int = 0
    edge_count: int = 0
    import_count: int = 0
    elapsed_s: float = 0.0
    error: str | None = None
    started_at: float | None = None
    discovered: list[str] = field(default_factory=list)
    edge_kind_counts: dict[str, int] = field(default_factory=dict)
    xmod_edge_count: int = 0

    def to_dict(self) -> dict:
        d: dict = {
            "name": self.name,
            "depth": self.depth,
            "status": self.status.value,
        }
        if self.status == BinaryStatus.COMPLETED:
            d["node_count"] = self.node_count
            d["edge_count"] = self.edge_count
            d["import_count"] = self.import_count
            d["elapsed_s"] = round(self.elapsed_s, 2)
            d["discovered"] = self.discovered
            d["edge_kind_counts"] = self.edge_kind_counts
            d["xmod_edge_count"] = self.xmod_edge_count
        elif self.status == BinaryStatus.ANALYZING and self.started_at:
            d["elapsed_s"] = round(time.time() - self.started_at, 2)
        elif self.status == BinaryStatus.ERROR:
            d["error"] = self.error
        return d


class AnalysisState:
    """Thread-safe in-memory tracking of analysis progress."""

    def __init__(self):
        self._lock = threading.Lock()
        self.binaries: dict[str, BinaryEntry] = {}
        self.analysis_started_at: float | None = None
        self.analysis_elapsed_s: float | None = None
        self.throughput_history: list[float] = []  # timestamps of completions
        self._total_nodes: int = 0
        self._total_edges: int = 0
        self.running: bool = False
        self.current_phase: str | None = None
        self.phase_progress: tuple[int, int] | None = None  # (current, total)

    def reset(self) -> None:
        with self._lock:
            self.binaries.clear()
            self.analysis_started_at = None
            self.analysis_elapsed_s = None
            self.throughput_history.clear()
            self._total_nodes = 0
            self._total_edges = 0
            self.running = False
            self.current_phase = None
            self.phase_progress = None

    def binary_queued(self, name: str, depth: int) -> None:
        with self._lock:
            key = name.lower()
            if key not in self.binaries:
                self.binaries[key] = BinaryEntry(name=name, depth=depth)
                if self.analysis_started_at is None:
                    self.analysis_started_at = time.time()
                    self.running = True

    def binary_started(self, name: str, depth: int) -> None:
        with self._lock:
            key = name.lower()
            entry = self.binaries.get(key)
            if entry:
                entry.status = BinaryStatus.ANALYZING
                entry.started_at = time.time()
            else:
                self.binaries[key] = BinaryEntry(
                    name=name, depth=depth, status=BinaryStatus.ANALYZING, started_at=time.time()
                )

    def binary_completed(
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
        with self._lock:
            key = name.lower()
            entry = self.binaries.get(key)
            if entry:
                entry.status = BinaryStatus.COMPLETED
                entry.node_count = node_count
                entry.edge_count = edge_count
                entry.import_count = import_count
                entry.elapsed_s = elapsed_s
                entry.discovered = discovered
                entry.edge_kind_counts = edge_kind_counts
                entry.xmod_edge_count = xmod_edge_count
            else:
                self.binaries[key] = BinaryEntry(
                    name=name,
                    depth=depth,
                    status=BinaryStatus.COMPLETED,
                    node_count=node_count,
                    edge_count=edge_count,
                    import_count=import_count,
                    elapsed_s=elapsed_s,
                    discovered=discovered,
                    edge_kind_counts=edge_kind_counts,
                    xmod_edge_count=xmod_edge_count,
                )
            self._total_nodes += node_count
            self._total_edges += edge_count
            self.throughput_history.append(time.time())

    def binary_error(self, name: str, depth: int, error: str) -> None:
        with self._lock:
            key = name.lower()
            entry = self.binaries.get(key)
            if entry:
                entry.status = BinaryStatus.ERROR
                entry.error = error
            else:
                self.binaries[key] = BinaryEntry(name=name, depth=depth, status=BinaryStatus.ERROR, error=error)

    def analysis_complete(self, elapsed_s: float, total_nodes: int, total_edges: int) -> None:
        with self._lock:
            self.analysis_elapsed_s = elapsed_s
            self._total_nodes = total_nodes
            self._total_edges = total_edges
            self.running = False
            self.current_phase = None
            self.phase_progress = None

    def phase_started(self, phase: str) -> None:
        with self._lock:
            self.current_phase = phase
            self.phase_progress = None
            self.running = True

    def phase_update(self, phase: str, current: int, total: int) -> None:
        with self._lock:
            self.current_phase = phase
            self.phase_progress = (current, total)

    def phase_complete(self, phase: str) -> None:
        with self._lock:
            if self.current_phase == phase:
                self.current_phase = None
                self.phase_progress = None

    def get_snapshot(self) -> dict:
        with self._lock:
            completed = [e for e in self.binaries.values() if e.status == BinaryStatus.COMPLETED]
            analyzing = [e for e in self.binaries.values() if e.status == BinaryStatus.ANALYZING]
            queued = [e for e in self.binaries.values() if e.status == BinaryStatus.QUEUED]
            errored = [e for e in self.binaries.values() if e.status == BinaryStatus.ERROR]

            # Compute syscall/rpc/secure_call counts from edge_kind_counts
            total_syscalls = sum(e.edge_kind_counts.get("SYSCALL", 0) for e in completed)
            total_rpc = sum(e.edge_kind_counts.get("RPC_CLIENT_CALL", 0) for e in completed)
            total_secure = sum(e.edge_kind_counts.get("SECURE_CALL", 0) for e in completed)

            elapsed = self.analysis_elapsed_s
            if elapsed is None and self.analysis_started_at:
                elapsed = time.time() - self.analysis_started_at

            return {
                "type": "state_snapshot",
                "running": self.running,
                "elapsed_s": round(elapsed, 2) if elapsed else None,
                "binaries": [e.to_dict() for e in self.binaries.values()],
                "aggregates": {
                    "total_nodes": self._total_nodes,
                    "total_edges": self._total_edges,
                    "total_imports": sum(e.import_count for e in completed),
                    "total_syscalls": total_syscalls,
                    "total_rpc": total_rpc,
                    "total_secure_calls": total_secure,
                    "completed": len(completed),
                    "analyzing": len(analyzing),
                    "queued": len(queued),
                    "errored": len(errored),
                    "total": len(self.binaries),
                },
                "throughput_history": self.throughput_history[-60:],
                "current_phase": self.current_phase,
                "phase_progress": list(self.phase_progress) if self.phase_progress else None,
            }
