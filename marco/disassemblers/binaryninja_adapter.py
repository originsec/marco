from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import sys
import threading
from contextlib import contextmanager, suppress
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

from binaryninja import BinaryView, Settings, Symbol, SymbolType, load

from . import DisassemblerAdapter

if TYPE_CHECKING:
    from pyjectify import ApiSetSchema

logger = logging.getLogger(__name__)

_apiset_schema: ApiSetSchema | None = None


def _resolve_module_name(module_name: str) -> str:
    """
    Return a normalized filename for a module (ensures extension). This is for queueing and resolution.
    """
    global _apiset_schema
    name = module_name.lower()
    if name.startswith("api-ms-win") or name.startswith("ext-ms-win"):
        # Lazy import to avoid dependency at import time
        try:
            from pyjectify import ApiSetSchema

            query = name if name.endswith(".dll") else f"{name}.dll"
            if _apiset_schema is None:
                _apiset_schema = ApiSetSchema()
            resolved = _apiset_schema.resolve(query)
            if resolved:
                name = resolved
        except Exception:
            pass
    if not name.endswith((".dll", ".sys", ".exe")):
        name += ".dll"
    return name


def _cache_key(filepath: str) -> str:
    stat = Path(filepath).stat()
    raw = f"{Path(filepath).name}:{stat.st_size}:{stat.st_mtime}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _bndb_path(filepath: str, cache_dir: str) -> str:
    base = Path(filepath).stem
    return str(Path(cache_dir) / f"{base}_{_cache_key(filepath)}.bndb")


def configure_pdb_settings(symbol_store: str) -> None:
    abs_store = str(Path(symbol_store).resolve())
    # _NT_SYMBOL_PATH is the highest-priority source BN checks (ahead of its own
    # settings), and the standard format understood by all BN versions.
    os.environ["_NT_SYMBOL_PATH"] = f"srv*{abs_store}*https://msdl.microsoft.com/download/symbols"
    # Also configure via BN settings as a belt-and-suspenders fallback.
    s = Settings()
    s.set_string_list("pdb.files.symbolServerList", ["https://msdl.microsoft.com/download/symbols"])
    s.set_bool("pdb.files.localStoreCache", True)
    s.set_string("pdb.files.localStoreAbsolute", abs_store)


def _symbol_module_from_filename(filename: str) -> str:
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base:
        base = base.split(".")[0]
    return base.lower()


# Global lock serializing all Binary Ninja load/analysis operations.
# BN's analysis engine is not documented as thread-safe for concurrent
# multi-binary analysis and can cause access violations on Windows when
# multiple threads call load() or update_analysis_and_wait() concurrently.
# For parallel analysis, use subprocess mode (--use-processes) instead.
_BN_LOCK = threading.Lock()


class BinaryNinjaAdapter(DisassemblerAdapter):
    def __init__(
        self,
        *,
        linear_sweep_permissive: bool = False,
        max_function_size: int | None = None,
        max_function_update_count: int | None = None,
        cache_dir: str | None = None,
        symbol_store: str | None = None,
    ):
        self._linear_sweep_permissive = linear_sweep_permissive
        self._max_function_size = max_function_size
        self._max_function_update_count = max_function_update_count
        self._cache_dir = cache_dir
        self._symbol_store = symbol_store

    @contextmanager
    def open_binary(self, path: str):
        # BinaryNinja core can crash when multiple loads happen concurrently.
        # Serialize loading and analysis to avoid access violations.
        bv = None
        try:
            with _BN_LOCK:
                logger.debug("Acquired BN lock for %s", path)
                # Apply requested BN settings before loading
                try:
                    if self._linear_sweep_permissive:
                        Settings().set_bool("analysis.linearSweep.permissive", True)
                    if self._max_function_size is not None and self._max_function_size >= 0:
                        # 0 may be treated as unlimited in BN; caller can set appropriately
                        try:
                            Settings().set_integer("analysis.limits.maxFunctionSize", int(self._max_function_size))
                        except Exception:
                            # Some BN versions may require unsigned; fallback to string API if needed
                            Settings().set("analysis.limits.maxFunctionSize", int(self._max_function_size))
                    if self._max_function_update_count is not None and self._max_function_update_count >= 0:
                        try:
                            Settings().set_integer(
                                "analysis.limits.maxFunctionUpdateCount", int(self._max_function_update_count)
                            )
                        except Exception:
                            Settings().set(
                                "analysis.limits.maxFunctionUpdateCount", int(self._max_function_update_count)
                            )
                except Exception:
                    logger.warning("Failed to apply Binary Ninja settings", exc_info=True)

                bndb = None
                if self._cache_dir:
                    bndb = _bndb_path(path, self._cache_dir)
                    if Path(bndb).exists():
                        logging.info(f"Loading from cache: {bndb}")
                        try:
                            bv = load(bndb)
                        except Exception as e:
                            logging.warning(f"Corrupt cache, reloading: {e}")
                            Path(bndb).unlink()
                            bndb = None
                            try:
                                bv = load(path, update_analysis=False)
                            except Exception:
                                bv = load(path)
                    else:
                        try:
                            bv = load(path, update_analysis=False)
                        except Exception:
                            bv = load(path)
                else:
                    try:
                        bv = load(path, update_analysis=False)
                    except Exception:
                        bv = load(path)

                # Configure PDB settings after load() — the PDB plugin registers
                # its settings keys only once a binary is open, so any set_* calls
                # before load() silently no-op on nonexistent keys.
                if self._symbol_store and bndb is None:
                    configure_pdb_settings(self._symbol_store)

                try:
                    bv.update_analysis_and_wait()
                except Exception:
                    logger.error("update_analysis_and_wait() failed for %s", path, exc_info=True)

                if bndb and not Path(bndb).exists():
                    try:
                        logging.info(f"Saving to cache: {bndb}")
                        bv.create_database(bndb)
                    except Exception as e:
                        logging.warning(f"Could not save cache: {e}")

            yield bv
        finally:
            if bv is not None:
                with suppress(Exception):
                    bv.file.close()

    def get_module_name(self, bv: BinaryView) -> str:
        binary_path = bv.file.original_filename
        name = binary_path.split("/")[-1].split("\\")[-1].split(".")[0]
        return name.lower()

    def get_file_version(self, bv: BinaryView) -> str | None:
        try:
            # Prefer PE metadata if available
            if hasattr(bv, "pe") and bv.pe is not None:
                vs = getattr(bv.pe, "version_info", None)
                if vs and getattr(vs, "file_version", None):
                    return str(vs.file_version)
            # Fallback to BinaryView metadata
            meta = getattr(bv, "file", None)
            if meta and hasattr(meta, "metadata"):
                mv = meta.metadata.get("FileVersion") or meta.metadata.get("ProductVersion")
                if mv:
                    return str(mv)
            # Windows-specific fallback: query version resource via WinAPI
            if sys.platform == "win32":
                try:
                    path = bv.file.original_filename
                    if path:
                        # Call WinAPI to fetch VS_FIXEDFILEINFO
                        get_size = ctypes.windll.version.GetFileVersionInfoSizeW
                        get_info = ctypes.windll.version.GetFileVersionInfoW
                        query_value = ctypes.windll.version.VerQueryValueW

                        dummy = wintypes.DWORD(0)
                        size = get_size(path, ctypes.byref(dummy))
                        if size:
                            data = ctypes.create_string_buffer(size)
                            if get_info(path, 0, size, data):
                                lp_buffer = ctypes.c_void_p()
                                u_len = wintypes.UINT()
                                if (
                                    query_value(data, "\\", ctypes.byref(lp_buffer), ctypes.byref(u_len))
                                    and lp_buffer.value
                                ):

                                    class FixedFileInfo(ctypes.Structure):  # noqa: N801
                                        _fields_ = [
                                            ("dwSignature", wintypes.DWORD),
                                            ("dwStrucVersion", wintypes.DWORD),
                                            ("dwFileVersionMS", wintypes.DWORD),
                                            ("dwFileVersionLS", wintypes.DWORD),
                                            ("dwProductVersionMS", wintypes.DWORD),
                                            ("dwProductVersionLS", wintypes.DWORD),
                                            ("dwFileFlagsMask", wintypes.DWORD),
                                            ("dwFileFlags", wintypes.DWORD),
                                            ("dwFileOS", wintypes.DWORD),
                                            ("dwFileType", wintypes.DWORD),
                                            ("dwFileSubtype", wintypes.DWORD),
                                            ("dwFileDateMS", wintypes.DWORD),
                                            ("dwFileDateLS", wintypes.DWORD),
                                        ]

                                    info = ctypes.cast(lp_buffer.value, ctypes.POINTER(FixedFileInfo)).contents

                                    def hiword(d: int) -> int:
                                        return (d >> 16) & 0xFFFF

                                    def loword(d: int) -> int:
                                        return d & 0xFFFF

                                    major = hiword(info.dwFileVersionMS)
                                    minor = loword(info.dwFileVersionMS)
                                    build = hiword(info.dwFileVersionLS)
                                    revision = loword(info.dwFileVersionLS)
                                    return f"{major}.{minor}.{build}.{revision}"
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def iter_functions(self, bv: BinaryView):
        return list(bv.functions)

    def function_name(self, fn) -> str:
        return fn.name

    def function_address(self, fn) -> int:
        return int(fn.start)

    def _get_internal_callees(self, bv: BinaryView, fn) -> set[str]:
        module = self.get_module_name(bv)
        return {f"{module}!{callee.name}" for callee in fn.callees}

    def _get_symbol_from_refs(self, bv: BinaryView, refs) -> Symbol | None:
        for ref in refs:
            symbol = bv.get_symbol_at(ref)
            if symbol is not None:
                return symbol
        return None

    def _get_external_callees(self, bv: BinaryView, fn) -> set[str]:
        callees: set[str] = set()
        if not fn.call_sites:
            return set()
        for call_site in set(fn.call_sites):
            refs_from = bv.get_code_refs_from(call_site.address)
            if not refs_from:
                continue
            symbol = self._get_symbol_from_refs(bv, refs_from)
            if symbol is None:
                continue
            if symbol.type == SymbolType.ImportAddressSymbol:
                # Robustly extract the library/module name from the symbol namespace
                module_name = None
                try:
                    ns = symbol.namespace
                    if hasattr(ns, "name"):
                        name_attr = ns.name
                        if isinstance(name_attr, (list, tuple)) and name_attr:
                            module_name = name_attr[0]
                        elif isinstance(name_attr, str):
                            module_name = name_attr.split("::")[0]
                    if not module_name and ns is not None:
                        module_name = str(ns).split("::")[0]
                except Exception:
                    pass
                if not module_name:
                    continue
                resolved_filename = _resolve_module_name(module_name)
                symbol_module = _symbol_module_from_filename(resolved_filename)
                symbol_name = f"{symbol_module}!{symbol.name}"
                callees.add(symbol_name)
        return callees

    def function_callees_symbols(self, bv: BinaryView, fn) -> list[str]:
        symbols = set()
        symbols.update(self._get_internal_callees(bv, fn))
        symbols.update(self._get_external_callees(bv, fn))
        return list(symbols)

    def imported_modules(self, bv: BinaryView) -> set[str]:
        imports = set()
        for module in bv.libraries:
            if not module:
                continue
            imports.add(_resolve_module_name(module))
        return imports

    def read_memory(self, bv: BinaryView, address: int, size: int) -> bytes | None:
        try:
            data = bv.read(address, size)
            if data and len(data) == size:
                return data
        except Exception:
            pass
        return None

    def iter_instructions(self, fn):
        """Yield (address, length, tokens) for each instruction via basic block iteration."""
        for block in fn.basic_blocks:
            start = block.start
            end = block.end
            addr = start

            while addr < end:
                # Read up to 16 bytes for the instruction
                data = fn.view.read(addr, 16)
                if not data:
                    break

                # Get instruction info (this returns length and other details)
                info = fn.arch.get_instruction_info(data, addr)
                if not info or info.length == 0:
                    break

                # Get disassembly tokens
                tokens, _ = fn.arch.get_instruction_text(data[: info.length], addr)
                yield (addr, info.length, tokens)

                addr += info.length

    def get_call_parameter(self, bv: BinaryView, fn, call_addr: int, param_idx: int) -> int | None:
        """Resolve a call parameter constant via HLIL then MLIL."""
        if fn.hlil:
            for instr in fn.hlil.instructions:
                if (
                    call_addr >= instr.address
                    and call_addr < instr.address + 10
                    and hasattr(instr, "params")
                    and len(instr.params) > param_idx
                ):
                    param = instr.params[param_idx]
                    if hasattr(param, "constant"):
                        return param.constant
                    elif hasattr(param, "value") and hasattr(param.value, "value"):
                        return param.value.value

        if fn.mlil:
            for instr in fn.mlil.instructions:
                if (
                    call_addr >= instr.address
                    and call_addr < instr.address + 10
                    and hasattr(instr, "params")
                    and len(instr.params) > param_idx
                ):
                    param = instr.params[param_idx]
                    if hasattr(param, "constant"):
                        return param.constant
                    elif hasattr(param, "value"):
                        if hasattr(param.value, "value"):
                            return param.value.value
                        elif hasattr(param.value, "constant"):
                            return param.value.constant
        return None
