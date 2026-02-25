"""Extract RPC client calls (NdrClientCall2/3) from PE binaries."""

from __future__ import annotations

import logging
import struct

from ..core.models import Edge, ExtractionResult
from ..core.rpc_models import RPCClientCall, format_guid, get_binary_for_interface
from ..disassemblers import DisassemblerAdapter
from ..utils.binary_analysis import (
    find_register_value_asm,
    get_call_references,
    get_containing_function,
    has_symbol,
)

logger = logging.getLogger(__name__)


class RPCClientExtractor:
    name = "rpc_client"

    NDR_CLIENT_APIS = [
        "NdrClientCall",
        "NdrClientCall2",
        "NdrClientCall3",
        "NdrAsyncClientCall",
        "NdrAsyncClientCall2",
    ]

    def __init__(self):
        self.registry = None

    def extract(self, *, bv, adapter: DisassemblerAdapter) -> ExtractionResult:
        result = ExtractionResult()
        module = adapter.get_module_name(bv)

        client_calls = self._find_all_client_calls(bv, adapter, module)

        for call in client_calls:
            if self.registry:
                self.registry.register_client_call(call)
            else:
                logger.warning(f"No RPC registry available for {call.client_function}")
                edge = Edge(
                    src=call.client_function,
                    dst=f"UNRESOLVED_RPC_{call.interface_id}_{call.opnum}",
                    kind="RPC_CLIENT_CALL",
                    props={
                        "interface_id": call.interface_id,
                        "opnum": call.opnum,
                        "rpc_api": call.rpc_api,
                        "call_address": call.call_address,
                        "unresolved": True,
                    },
                )
                result.edges.append(edge)

            server_binary = get_binary_for_interface(call.interface_id)
            if server_binary:
                logger.debug(
                    f"Adding server binary '{server_binary}' for interface {call.interface_id} to processing queue"
                )
                result.discovered_modules.add(server_binary)

        if len(client_calls) > 0:
            logger.debug(f"Found {len(client_calls)} RPC client calls in {module}")

        return result

    def _find_all_client_calls(self, bv, adapter: DisassemblerAdapter, module: str) -> list[RPCClientCall]:
        client_calls = []

        for api_name in self.NDR_CLIENT_APIS:
            if not has_symbol(bv, api_name):
                continue

            for call_addr in get_call_references(bv, api_name):
                containing_func = get_containing_function(bv, adapter, call_addr)
                if not containing_func:
                    continue

                if api_name == "NdrClientCall2":
                    call_info = self._extract_ndrclientcall2_info(bv, adapter, containing_func, call_addr, module)
                elif api_name == "NdrClientCall3":
                    call_info = self._extract_ndrclientcall3_info(bv, adapter, containing_func, call_addr, module)
                else:
                    logger.debug(f"Skipping unsupported API: {api_name}")
                    continue

                if call_info:
                    client_calls.append(call_info)

        return client_calls

    def _extract_ndrclientcall2_info(
        self, bv, adapter: DisassemblerAdapter, containing_func, call_addr: int, module: str
    ) -> RPCClientCall | None:
        # RCX=pStubDescriptor->PMIDL_STUB_DESC, RDX=pFormat
        # GUID at PMIDL_STUB_DESC+4; OpNum at pFormat+6
        try:
            rcx_value = self._find_register_value(bv, adapter, containing_func, call_addr, "rcx")
            rdx_value = self._find_register_value(bv, adapter, containing_func, call_addr, "rdx")

            if not rcx_value or not rdx_value:
                logger.debug(f"Could not find parameters for NdrClientCall2 at {hex(call_addr)}")
                return None

            pstub_desc_data = adapter.read_memory(bv, rcx_value, 8)
            if not pstub_desc_data:
                return None
            pstub_desc = struct.unpack("<Q", pstub_desc_data)[0]

            guid_data = adapter.read_memory(bv, pstub_desc + 4, 16)
            if not guid_data or len(guid_data) < 16:
                return None
            interface_id = format_guid(guid_data)

            opnum_data = adapter.read_memory(bv, rdx_value + 6, 2)
            opnum = -1 if not opnum_data or len(opnum_data) < 2 else struct.unpack("<H", opnum_data)[0]

            func_name = adapter.function_name(containing_func)
            return RPCClientCall(
                client_function=f"{module}!{func_name}",
                client_address=adapter.function_address(containing_func),
                call_address=call_addr,
                interface_id=interface_id,
                opnum=opnum,
                rpc_api="NdrClientCall2",
            )

        except Exception:
            logger.debug("NdrClientCall2 extraction failed at %#x", call_addr, exc_info=True)
            return None

    def _extract_ndrclientcall3_info(
        self, bv, adapter: DisassemblerAdapter, containing_func, call_addr: int, module: str
    ) -> RPCClientCall | None:
        # RCX=pProxyInfo (triple-deref to buffer), RDX=OpNum; GUID at buffer+4
        try:
            rcx_value = self._find_register_value(bv, adapter, containing_func, call_addr, "rcx")
            rdx_value = self._find_register_value(bv, adapter, containing_func, call_addr, "rdx")

            if not rcx_value:
                logger.debug(f"Could not find RCX for NdrClientCall3 at {hex(call_addr)}")
                return None

            level1_data = adapter.read_memory(bv, rcx_value, 8)
            if not level1_data:
                return None
            level1_ptr = struct.unpack("<Q", level1_data)[0]

            level2_data = adapter.read_memory(bv, level1_ptr, 8)
            if not level2_data:
                return None
            level2_ptr = struct.unpack("<Q", level2_data)[0]

            guid_data = adapter.read_memory(bv, level2_ptr + 4, 16)
            if not guid_data or len(guid_data) < 16:
                return None
            interface_id = format_guid(guid_data)

            opnum = rdx_value if rdx_value is not None else -1

            func_name = adapter.function_name(containing_func)
            return RPCClientCall(
                client_function=f"{module}!{func_name}",
                client_address=adapter.function_address(containing_func),
                call_address=call_addr,
                interface_id=interface_id,
                opnum=opnum,
                rpc_api="NdrClientCall3",
            )

        except Exception:
            logger.debug("NdrClientCall3 extraction failed at %#x", call_addr, exc_info=True)
            return None

    def _find_register_value(self, bv, adapter: DisassemblerAdapter, func, call_addr: int, register: str) -> int | None:
        if hasattr(adapter, "get_call_parameter"):
            param_idx = 0 if register == "rcx" else 1 if register == "rdx" else -1
            if param_idx >= 0:
                value = adapter.get_call_parameter(bv, func, call_addr, param_idx)
                if value is not None:
                    return value

        return find_register_value_asm(bv, adapter, func, call_addr, register)
