"""Binary processor for analyzing individual binaries."""

from __future__ import annotations

import logging
from typing import Any

from ..core.helpers import resolve_file_path
from ..core.models import Edge, Node
from ..core.rpc_registry import RPCRegistry
from ..disassemblers import DisassemblerAdapter

logger = logging.getLogger(__name__)


def process_binary(
    target: str,
    search_paths: list[str],
    adapter: DisassemblerAdapter,
    extractors: list[Any],
    rpc_registry: RPCRegistry | None = None,
) -> tuple[list[Node], list[Edge], set[str]]:
    file_path = resolve_file_path(target, search_paths)
    nodes: list[Node] = []
    edges: list[Edge] = []
    discovered_modules: set[str] = set()

    with adapter.open_binary(file_path) as bv:
        for extractor in extractors:
            if hasattr(extractor, "registry") and rpc_registry:
                extractor.registry = rpc_registry

            result = extractor.extract(bv=bv, adapter=adapter)
            nodes.extend(result.nodes)
            edges.extend(result.edges)
            discovered_modules.update(result.discovered_modules)

    if rpc_registry:
        edges.extend(rpc_registry.get_all_edges(final=False))

    return nodes, edges, discovered_modules


def _serialize_rpc_data(rpc_registry: RPCRegistry) -> dict:
    """Serialize RPC registry data into a pickleable dict for cross-process transfer."""
    interfaces = {}
    for iid, iface in rpc_registry.interfaces.items():
        interfaces[iid] = {
            "interface_id": iface.interface_id,
            "server_binary": iface.server_binary,
            "registration_function": iface.registration_function,
            "registration_api": iface.registration_api,
            "structure_address": iface.structure_address,
            "procedures": {
                opnum: {
                    "opnum": proc.opnum,
                    "address": proc.address,
                    "symbol": proc.symbol,
                    "function_name": proc.function_name,
                }
                for opnum, proc in iface.procedures.items()
            },
        }

    pending_clients = [
        {
            "client_function": cc.client_function,
            "client_address": cc.client_address,
            "call_address": cc.call_address,
            "interface_id": cc.interface_id,
            "opnum": cc.opnum,
            "rpc_api": cc.rpc_api,
        }
        for cc in rpc_registry.pending_clients
    ]

    return {"interfaces": interfaces, "pending_clients": pending_clients}


def process_binary_subprocess(
    target: str,
    search_paths: list[str],
    bn_linear_sweep_permissive: bool,
    bn_max_function_size: int | None,
    bn_max_function_update_count: int | None,
    cache_dir: str | None = None,
    symbol_store: str | None = None,
) -> tuple[list[Node], list[Edge], set[str], dict]:
    """Entry point for ProcessPoolExecutor workers. Constructs adapter/extractors locally to avoid pickling BN objects."""
    # Lazy imports inside subprocess to avoid pickling issues
    from ..core.rpc_registry import RPCRegistry
    from ..disassemblers.binaryninja_adapter import BinaryNinjaAdapter
    from ..extractors.calls import CallsExtractor
    from ..extractors.rpc_client import RPCClientExtractor
    from ..extractors.rpc_server import RPCServerExtractor
    from ..extractors.secure_call import SecureCallsExtractor
    from ..extractors.syscall import SyscallsExtractor

    adapter = BinaryNinjaAdapter(
        linear_sweep_permissive=bn_linear_sweep_permissive,
        max_function_size=bn_max_function_size,
        max_function_update_count=bn_max_function_update_count,
        cache_dir=cache_dir,
        symbol_store=symbol_store,
    )

    extractors = [
        CallsExtractor(),
        SyscallsExtractor(),
        SecureCallsExtractor(),
        RPCClientExtractor(),
        RPCServerExtractor(),
    ]

    rpc_registry = RPCRegistry()

    file_path = resolve_file_path(target, search_paths)
    nodes: list[Node] = []
    edges: list[Edge] = []
    discovered_modules: set[str] = set()

    with adapter.open_binary(file_path) as bv:
        for extractor in extractors:
            if hasattr(extractor, "registry"):
                extractor.registry = rpc_registry  # type: ignore[assignment]

            result = extractor.extract(bv=bv, adapter=adapter)
            nodes.extend(result.nodes)
            edges.extend(result.edges)
            discovered_modules.update(result.discovered_modules)

    rpc_data = _serialize_rpc_data(rpc_registry)

    return nodes, edges, discovered_modules, rpc_data
