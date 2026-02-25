"""RPC-specific data models for tracking interfaces, procedures, and client/server relationships."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RPCProcedure:
    """Represents a single RPC procedure within an interface."""

    opnum: int
    address: int
    symbol: str  # Full symbol like "services!RCreateServiceW"
    function_name: str  # Just the function name like "RCreateServiceW"


@dataclass
class RPCInterface:
    """Represents an RPC interface registered by a server."""

    interface_id: str  # GUID format like "367ABB81-9844-35F1-AD32-98F038001003"
    server_binary: str  # Module name like "services.exe"
    registration_function: str  # Function that registered this interface
    registration_api: str  # API used (RpcServerRegisterIf, RpcServerRegisterIfEx, etc.)
    procedures: dict[int, RPCProcedure] = field(default_factory=dict)  # OpNum -> RPCProcedure
    structure_address: int = 0  # Address of RPC_SERVER_INTERFACE structure


@dataclass
class RPCClientCall:
    """Represents an RPC client call that needs to be resolved to a server procedure."""

    client_function: str  # Full symbol like "sechost!RCreateServiceW"
    client_address: int
    call_address: int  # Address of the actual NdrClientCall instruction
    interface_id: str  # GUID format
    opnum: int
    rpc_api: str  # API used (NdrClientCall2, NdrClientCall3, etc.)


def format_guid(data: bytes) -> str:
    """Convert 16 raw bytes to a GUID string like "367ABB81-9844-35F1-AD32-98F038001003"."""
    if len(data) < 16:
        return "Invalid GUID"

    # Parse components with proper endianness
    dword1 = struct.unpack("<I", data[0:4])[0]  # Little-endian
    word1 = struct.unpack("<H", data[4:6])[0]  # Little-endian
    word2 = struct.unpack("<H", data[6:8])[0]  # Little-endian
    bytes8 = data[8:16]  # Big-endian for last 8 bytes

    return (
        f"{dword1:08X}-{word1:04X}-{word2:04X}-"
        f"{bytes8[0]:02X}{bytes8[1]:02X}-"
        f"{bytes8[2]:02X}{bytes8[3]:02X}{bytes8[4]:02X}"
        f"{bytes8[5]:02X}{bytes8[6]:02X}{bytes8[7]:02X}"
    )


# Cache for known interfaces, loaded lazily from JSON file
_KNOWN_INTERFACES: dict[str, str] | None = None


def _load_known_interfaces() -> dict[str, str]:
    r"""
    Load known RPC interfaces from JSON data file (GUID -> binary name).

    To regenerate using NtObjectManager (as admin):
    ```powershell
    Get-ChildItem -Path C:\Windows\System32 -Recurse -Include *.dll,*.exe |
      Get-RpcServer -DbgHelpPath 'C:\Program Files (x86)\Windows Kits\10\bin\<version>\x64\DbgHelp.dll' |
      Select-Object @{n='interfaceid';e={$_.InterfaceId.ToString().ToLower()}}, @{n='name';e={$_.Name.ToLower()}}
    ```
    """
    data_file = Path(__file__).parent.parent / "data" / "known_rpc_interfaces.json"
    try:
        with open(data_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        import logging

        logging.warning(f"Could not load known RPC interfaces from {data_file}: {e}")
        return {}


def get_binary_for_interface(interface_id: str) -> str | None:
    global _KNOWN_INTERFACES
    if _KNOWN_INTERFACES is None:
        _KNOWN_INTERFACES = _load_known_interfaces()
    return _KNOWN_INTERFACES.get(interface_id.lower())
