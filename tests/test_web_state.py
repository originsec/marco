"""Tests for marco.web.state."""

from marco.web.state import AnalysisState


class TestAnalysisState:
    def test_initial_state(self):
        state = AnalysisState()
        snap = state.get_snapshot()
        assert snap["running"] is False
        assert snap["binaries"] == []
        assert snap["aggregates"]["total"] == 0

    def test_binary_queued(self):
        state = AnalysisState()
        state.binary_queued("kernel32.dll", 0)
        snap = state.get_snapshot()
        assert len(snap["binaries"]) == 1
        assert snap["binaries"][0]["name"] == "kernel32.dll"
        assert snap["binaries"][0]["status"] == "queued"
        assert snap["running"] is True

    def test_binary_started(self):
        state = AnalysisState()
        state.binary_queued("ntdll.dll", 0)
        state.binary_started("ntdll.dll", 0)
        snap = state.get_snapshot()
        assert snap["binaries"][0]["status"] == "analyzing"

    def test_binary_completed(self):
        state = AnalysisState()
        state.binary_queued("kernel32.dll", 0)
        state.binary_started("kernel32.dll", 0)
        state.binary_completed(
            "kernel32.dll",
            0,
            node_count=100,
            edge_count=200,
            import_count=5,
            elapsed_s=3.5,
            discovered=["ntdll.dll"],
            edge_kind_counts={"CALLS": 180, "SYSCALL": 20},
        )
        snap = state.get_snapshot()
        assert snap["binaries"][0]["status"] == "completed"
        assert snap["binaries"][0]["node_count"] == 100
        assert snap["binaries"][0]["edge_count"] == 200
        assert snap["aggregates"]["total_nodes"] == 100
        assert snap["aggregates"]["total_edges"] == 200
        assert snap["aggregates"]["total_syscalls"] == 20

    def test_binary_error(self):
        state = AnalysisState()
        state.binary_queued("bad.dll", 0)
        state.binary_error("bad.dll", 0, "not found")
        snap = state.get_snapshot()
        assert snap["binaries"][0]["status"] == "error"
        assert snap["binaries"][0]["error"] == "not found"

    def test_analysis_complete(self):
        state = AnalysisState()
        state.binary_queued("x.dll", 0)
        state.analysis_complete(10.5, 500, 1000)
        snap = state.get_snapshot()
        assert snap["running"] is False
        assert snap["elapsed_s"] == 10.5
        assert snap["aggregates"]["total_nodes"] == 500

    def test_reset(self):
        state = AnalysisState()
        state.binary_queued("x.dll", 0)
        state.reset()
        snap = state.get_snapshot()
        assert snap["binaries"] == []
        assert snap["running"] is False

    def test_case_insensitive_keys(self):
        state = AnalysisState()
        state.binary_queued("Kernel32.DLL", 0)
        state.binary_started("kernel32.dll", 0)
        snap = state.get_snapshot()
        assert len(snap["binaries"]) == 1
        assert snap["binaries"][0]["status"] == "analyzing"

    def test_aggregates_accumulate(self):
        state = AnalysisState()
        state.binary_completed("a.dll", 0, 100, 50, 2, 1.0, [], {"CALLS": 50})
        state.binary_completed("b.dll", 1, 200, 80, 3, 2.0, [], {"CALLS": 70, "SYSCALL": 10})
        snap = state.get_snapshot()
        assert snap["aggregates"]["total_nodes"] == 300
        assert snap["aggregates"]["total_edges"] == 130
        assert snap["aggregates"]["total_syscalls"] == 10
        assert snap["aggregates"]["completed"] == 2
