"""Extract RPC server interfaces and dispatch tables from PE binaries."""

from __future__ import annotations

import logging
import struct

from ..core.models import ExtractionResult, Node
from ..core.rpc_models import RPCInterface, RPCProcedure, format_guid
from ..disassemblers import DisassemblerAdapter
from ..utils.binary_analysis import (
    find_register_value_asm,
    get_call_references,
    get_containing_function,
    get_function_name_at_address,
    has_symbol,
)

logger = logging.getLogger(__name__)


class RPCServerExtractor:
    name = "rpc_server"

    RPC_REGISTRATION_APIS = [
        "RpcServerRegisterIf",
        "RpcServerRegisterIfEx",
        "RpcServerRegisterIf2",
        "RpcServerRegisterIf3",
    ]

    def __init__(self):
        self.registry = None

    def extract(self, *, bv, adapter: DisassemblerAdapter) -> ExtractionResult:
        result = ExtractionResult()
        module = adapter.get_module_name(bv)

        interfaces = self._find_all_interfaces(bv, adapter, module)

        for interface in interfaces:
            for opnum, procedure in interface.procedures.items():
                node = Node(
                    symbol=procedure.symbol,
                    module=module,
                    name=procedure.function_name,
                    address=procedure.address,
                    kind="function",
                    props={
                        "source": "rpc_server",
                        "rpc_interface": interface.interface_id,
                        "rpc_opnum": opnum,
                        "registration_api": interface.registration_api,
                    },
                )
                result.nodes.append(node)

            if self.registry:
                self.registry.register_interface(interface)

        if len(interfaces) > 0:
            logger.debug(
                f"Found {len(interfaces)} RPC interfaces with "
                f"{sum(len(i.procedures) for i in interfaces)} procedures in {module}"
            )

        return result

    def _find_all_interfaces(self, bv, adapter: DisassemblerAdapter, module: str) -> list[RPCInterface]:
        interfaces = []

        for api_name in self.RPC_REGISTRATION_APIS:
            if not has_symbol(bv, api_name):
                continue

            for call_addr in get_call_references(bv, api_name):
                containing_func = get_containing_function(bv, adapter, call_addr)
                if not containing_func:
                    continue

                interface = self._extract_interface_from_call(bv, adapter, containing_func, call_addr, api_name, module)

                if interface:
                    interfaces.append(interface)

        return interfaces

    def _extract_interface_from_call(
        self, bv, adapter: DisassemblerAdapter, containing_func, call_addr: int, api_name: str, module: str
    ) -> RPCInterface | None:
        # RPC_SERVER_INTERFACE: GUID +0x04, dispatch table ptr +0x30, MIDL_SERVER_INFO ptr +0x50
        # MIDL_SERVER_INFO: dispatch table +0x08, format string offset table +0x18
        try:
            interface_addr = self._find_interface_address(bv, adapter, containing_func, call_addr)
            if not interface_addr:
                logger.debug(f"Could not find interface address for {api_name} at {hex(call_addr)}")
                return None

            struct_data = adapter.read_memory(bv, interface_addr, 0x60)
            if not struct_data or len(struct_data) < 0x60:
                return None

            guid_bytes = struct_data[0x04:0x14]
            interface_id = format_guid(guid_bytes)

            dispatch_table_ptr = struct.unpack("<Q", struct_data[0x30:0x38])[0]
            midl_info_ptr = struct.unpack("<Q", struct_data[0x50:0x58])[0]

            procedures = {}

            if dispatch_table_ptr and midl_info_ptr:
                count_data = adapter.read_memory(bv, dispatch_table_ptr, 8)
                if count_data:
                    proc_count = struct.unpack("<Q", count_data)[0]
                    if 1 <= proc_count <= 200:
                        procedures = self._parse_procedures(bv, adapter, midl_info_ptr, proc_count, module)

            func_name = adapter.function_name(containing_func)
            interface = RPCInterface(
                interface_id=interface_id,
                server_binary=module,
                registration_function=func_name,
                registration_api=api_name,
                procedures=procedures,
                structure_address=interface_addr,
            )

            return interface

        except Exception:
            logger.debug("Failed to parse %s call at %#x", api_name, call_addr, exc_info=True)
            return None

    def _parse_procedures(
        self, bv, adapter: DisassemblerAdapter, midl_info_ptr: int, proc_count: int, module: str
    ) -> dict[int, RPCProcedure]:
        procedures = {}

        try:
            midl_data = adapter.read_memory(bv, midl_info_ptr, 0x40)
            if not midl_data or len(midl_data) < 0x20:
                return procedures

            dispatch_ptr = struct.unpack("<Q", midl_data[0x08:0x10])[0]
            fmt_offset_ptr = struct.unpack("<Q", midl_data[0x18:0x20])[0]

            if not dispatch_ptr:
                return procedures

            dispatch_to_opnum = self._map_dispatch_to_opnum(bv, adapter, fmt_offset_ptr, proc_count)

            for i in range(proc_count):
                func_ptr_data = adapter.read_memory(bv, dispatch_ptr + (i * 8), 8)
                if func_ptr_data:
                    func_ptr = struct.unpack("<Q", func_ptr_data)[0]
                    if func_ptr:
                        opnum = dispatch_to_opnum.get(i, i)
                        func_name = get_function_name_at_address(bv, adapter, func_ptr)
                        if not func_name:
                            func_name = f"sub_{func_ptr:x}"

                        procedure = RPCProcedure(
                            opnum=opnum, address=func_ptr, symbol=f"{module}!{func_name}", function_name=func_name
                        )
                        procedures[opnum] = procedure

        except Exception:
            logger.debug("Procedure table parse failed at %#x", midl_info_ptr, exc_info=True)

        return procedures

    def _map_dispatch_to_opnum(
        self, bv, adapter: DisassemblerAdapter, fmt_offset_ptr: int, dispatch_count: int
    ) -> dict[int, int]:
        if not fmt_offset_ptr or fmt_offset_ptr == 0:
            return {i: i for i in range(dispatch_count)}

        dispatch_to_opnum = {}
        dispatch_idx = 0

        try:
            for opnum in range(min(200, dispatch_count * 2)):
                offset_data = adapter.read_memory(bv, fmt_offset_ptr + (opnum * 2), 2)
                if not offset_data or len(offset_data) < 2:
                    break

                offset = struct.unpack("<H", offset_data)[0]

                if offset == 0xFFFF:
                    continue

                if opnum > 0:
                    prev_offset_data = adapter.read_memory(bv, fmt_offset_ptr + ((opnum - 1) * 2), 2)
                    if prev_offset_data:
                        prev_offset = struct.unpack("<H", prev_offset_data)[0]
                        if offset == prev_offset:
                            continue

                if dispatch_idx < dispatch_count:
                    dispatch_to_opnum[dispatch_idx] = opnum
                    dispatch_idx += 1
                else:
                    break

        except Exception:
            logger.debug("OpNum mapping failed at %#x", fmt_offset_ptr, exc_info=True)

        while dispatch_idx < dispatch_count:
            if dispatch_idx not in dispatch_to_opnum:
                dispatch_to_opnum[dispatch_idx] = dispatch_idx
            dispatch_idx += 1

        return dispatch_to_opnum

    def _find_interface_address(self, bv, adapter: DisassemblerAdapter, func, call_addr: int) -> int | None:
        if hasattr(adapter, "get_call_parameter"):
            value = adapter.get_call_parameter(bv, func, call_addr, 0)
            if value is not None:
                return value

        return find_register_value_asm(bv, adapter, func, call_addr, "rcx")
