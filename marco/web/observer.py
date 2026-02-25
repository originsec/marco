"""Observer protocol for analysis events."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AnalysisObserver(Protocol):
    """Protocol for observing analysis progress.

    Implementors receive callbacks as binaries move through the analysis pipeline.
    All methods are synchronous; async bridges should use run_coroutine_threadsafe.
    """

    def on_binary_queued(self, name: str, depth: int) -> None: ...

    def on_binary_started(self, name: str, depth: int) -> None: ...

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
    ) -> None: ...

    def on_binary_error(self, name: str, depth: int, error: str) -> None: ...

    def on_analysis_complete(self, elapsed_s: float, total_nodes: int, total_edges: int) -> None: ...

    def on_phase_started(self, phase: str) -> None: ...

    def on_phase_progress(self, phase: str, current: int, total: int) -> None: ...

    def on_phase_complete(self, phase: str) -> None: ...
