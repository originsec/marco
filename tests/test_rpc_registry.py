"""Tests for RPCRegistry."""

from __future__ import annotations

from marco.core.rpc_registry import RPCRegistry


class TestRegisterInterface:
    def test_register_interface_appears_in_registry(self, rpc_interface_factory):
        registry = RPCRegistry()
        iface = rpc_interface_factory()
        registry.register_interface(iface)
        assert iface.interface_id in registry.interfaces

    def test_register_duplicate_interface_overwrites(self, rpc_interface_factory):
        registry = RPCRegistry()
        iface1 = rpc_interface_factory(server_binary="a.dll")
        iface2 = rpc_interface_factory(server_binary="b.dll")
        registry.register_interface(iface1)
        registry.register_interface(iface2)
        assert registry.interfaces[iface1.interface_id].server_binary == "b.dll"


class TestRegisterClientCall:
    def test_client_call_with_known_interface_resolves(self, rpc_interface_factory, rpc_client_call_factory):
        registry = RPCRegistry()
        registry.register_interface(rpc_interface_factory())
        edge = registry.register_client_call(rpc_client_call_factory(opnum=0))
        assert edge is not None
        assert edge.kind == "RPC_CLIENT_CALL"

    def test_client_call_with_unknown_interface_returns_none(self, rpc_client_call_factory):
        registry = RPCRegistry()
        edge = registry.register_client_call(
            rpc_client_call_factory(interface_id="UNKNOWN-GUID-0000-0000-000000000000")
        )
        assert edge is None
        assert len(registry.pending_clients) == 1

    def test_pending_client_resolved_when_interface_registered(self, rpc_interface_factory, rpc_client_call_factory):
        registry = RPCRegistry()
        # Register client first — it will be pending
        registry.register_client_call(rpc_client_call_factory(opnum=0))
        assert len(registry.pending_clients) == 1
        assert len(registry.resolved_edges) == 0

        # Now register the interface — pending client should auto-resolve
        registry.register_interface(rpc_interface_factory())
        assert len(registry.pending_clients) == 0
        assert len(registry.resolved_edges) == 1


class TestGetAllEdges:
    def test_get_all_edges_non_final_returns_only_resolved(self, populated_registry):
        # Add an unresolved call
        from marco.core.rpc_models import RPCClientCall

        populated_registry.register_client_call(
            RPCClientCall(
                client_function="x!Y",
                client_address=0,
                call_address=0,
                interface_id="NO-SUCH-IFACE-0000-000000000000",
                opnum=99,
                rpc_api="NdrClientCall2",
            )
        )
        edges = populated_registry.get_all_edges(final=False)
        assert all(not e.props.get("unresolved") for e in edges)

    def test_get_all_edges_final_includes_unresolved(self, populated_registry):
        from marco.core.rpc_models import RPCClientCall

        populated_registry.register_client_call(
            RPCClientCall(
                client_function="x!Y",
                client_address=0,
                call_address=0,
                interface_id="NO-SUCH-IFACE-0000-000000000000",
                opnum=99,
                rpc_api="NdrClientCall2",
            )
        )
        edges = populated_registry.get_all_edges(final=True)
        unresolved = [e for e in edges if e.props.get("unresolved")]
        assert len(unresolved) >= 1

    def test_deduplication(self, rpc_interface_factory, rpc_client_call_factory):
        registry = RPCRegistry()
        registry.register_interface(rpc_interface_factory())
        registry.register_client_call(rpc_client_call_factory(opnum=0))
        # First call returns the edge
        edges1 = registry.get_all_edges(final=False)
        assert len(edges1) == 1
        # Second call returns nothing (already emitted)
        edges2 = registry.get_all_edges(final=False)
        assert len(edges2) == 0


class TestPersistence:
    def test_save_and_load_roundtrip(self, populated_registry, tmp_path):
        filepath = tmp_path / "registry.json"
        populated_registry.save_to_file(filepath)

        loaded = RPCRegistry.load_from_file(filepath)
        assert set(loaded.interfaces.keys()) == set(populated_registry.interfaces.keys())

    def test_load_nonexistent_file_returns_fresh(self, tmp_path):
        filepath = tmp_path / "does_not_exist.json"
        registry = RPCRegistry.load_from_file(filepath)
        assert len(registry.interfaces) == 0

    def test_load_corrupt_file_returns_fresh(self, tmp_path):
        filepath = tmp_path / "corrupt.json"
        filepath.write_text("NOT VALID JSON {{{{")
        registry = RPCRegistry.load_from_file(filepath)
        assert len(registry.interfaces) == 0


class TestStatistics:
    def test_get_statistics_counts(self, populated_registry):
        stats = populated_registry.get_statistics()
        assert stats["registered_interfaces"] == 1
        assert stats["total_procedures"] == 2
        assert stats["resolved_edges"] == 1

    def test_multiple_interfaces_multiple_clients(
        self, rpc_interface_factory, rpc_client_call_factory, rpc_procedure_factory
    ):
        registry = RPCRegistry()
        iface_a = rpc_interface_factory(
            interface_id="AAAA0000-0000-0000-0000-000000000000",
            procedures={0: rpc_procedure_factory(opnum=0, symbol="a!P0", function_name="P0")},
        )
        iface_b = rpc_interface_factory(
            interface_id="BBBB0000-0000-0000-0000-000000000000",
            procedures={0: rpc_procedure_factory(opnum=0, symbol="b!P0", function_name="P0")},
        )
        registry.register_interface(iface_a)
        registry.register_interface(iface_b)

        registry.register_client_call(
            rpc_client_call_factory(interface_id="AAAA0000-0000-0000-0000-000000000000", opnum=0)
        )
        registry.register_client_call(
            rpc_client_call_factory(
                client_function="client!Call2",
                interface_id="BBBB0000-0000-0000-0000-000000000000",
                opnum=0,
            )
        )
        stats = registry.get_statistics()
        assert stats["registered_interfaces"] == 2
        assert stats["resolved_edges"] == 2
