"""Shared test fixtures for marco tests."""

from __future__ import annotations

import pytest

from marco.core.rpc_models import RPCClientCall, RPCInterface, RPCProcedure
from marco.core.rpc_registry import RPCRegistry


@pytest.fixture
def rpc_procedure_factory():
    """Factory for creating RPCProcedure instances."""

    def _make(opnum: int = 0, address: int = 0x1000, symbol: str = "mod!Func", function_name: str = "Func"):
        return RPCProcedure(opnum=opnum, address=address, symbol=symbol, function_name=function_name)

    return _make


@pytest.fixture
def rpc_interface_factory(rpc_procedure_factory):
    """Factory for creating RPCInterface instances with optional procedures."""

    def _make(
        interface_id: str = "367ABB81-9844-35F1-AD32-98F038001003",
        server_binary: str = "server.dll",
        registration_function: str = "server!Register",
        registration_api: str = "RpcServerRegisterIfEx",
        procedures: dict[int, RPCProcedure] | None = None,
    ):
        if procedures is None:
            procedures = {0: rpc_procedure_factory(opnum=0)}
        return RPCInterface(
            interface_id=interface_id,
            server_binary=server_binary,
            registration_function=registration_function,
            registration_api=registration_api,
            procedures=procedures,
        )

    return _make


@pytest.fixture
def rpc_client_call_factory():
    """Factory for creating RPCClientCall instances."""

    def _make(
        client_function: str = "client!Call",
        client_address: int = 0x2000,
        call_address: int = 0x2010,
        interface_id: str = "367ABB81-9844-35F1-AD32-98F038001003",
        opnum: int = 0,
        rpc_api: str = "NdrClientCall2",
    ):
        return RPCClientCall(
            client_function=client_function,
            client_address=client_address,
            call_address=call_address,
            interface_id=interface_id,
            opnum=opnum,
            rpc_api=rpc_api,
        )

    return _make


@pytest.fixture
def populated_registry(rpc_interface_factory, rpc_client_call_factory, rpc_procedure_factory):
    """An RPCRegistry with one registered interface and one resolved client call."""
    registry = RPCRegistry()
    iface = rpc_interface_factory(
        procedures={
            0: rpc_procedure_factory(opnum=0, symbol="server!Proc0", function_name="Proc0"),
            1: rpc_procedure_factory(opnum=1, symbol="server!Proc1", function_name="Proc1"),
        }
    )
    registry.register_interface(iface)
    registry.register_client_call(rpc_client_call_factory(opnum=0))
    return registry
