"""Function name demangling utilities."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def demangle_name(name: str, arch=None, platform=None) -> str:
    """
    Demangle a function name if it appears to be mangled.

    Supports:
    - Microsoft Visual C++ mangling (names starting with '?')
    - GNU/GCC mangling (names starting with '_Z')

    Args:
        name: Function name to demangle
        arch: Optional architecture object from Binary Ninja
        platform: Optional platform object from Binary Ninja

    Returns:
        Demangled name if successful, original name otherwise
    """
    if not name or len(name) < 2:
        return name

    # Check if name appears to be mangled
    if not _is_mangled(name):
        return name

    try:
        from binaryninja import demangle

        # Ensure we have arch or platform for demangling
        if not arch and not platform:
            logger.debug(f"No arch/platform provided for demangling {name}")
            return name

        # Try Microsoft demangling (for Windows C++ symbols)
        if name.startswith("?"):
            try:
                # demangle_ms returns (Type, list_of_name_parts) on success
                # or (None, original_name_string) on failure
                # Try with arch first (more commonly available), then platform
                demangle_obj = arch if arch else platform
                result = demangle.demangle_ms(demangle_obj, name)
                if result and len(result) >= 2:
                    type_obj, name_parts = result
                    # Check if demangling succeeded - name_parts should be a list
                    if name_parts and isinstance(name_parts, list) and type_obj is not None:
                        # Convert list like ['Foobar', 'testf'] to 'Foobar::testf'
                        demangled = demangle.get_qualified_name(name_parts)
                        if demangled and demangled != name:
                            logger.debug(f"Demangled MS: {name} → {demangled}")
                            return demangled
                    elif isinstance(name_parts, str) and name_parts == name:
                        # Demangling failed, Binary Ninja returned original name
                        logger.debug(f"Binary Ninja could not demangle: {name[:100]}{'...' if len(name) > 100 else ''}")
            except Exception as e:
                logger.warning(f"MS demangling failed for {name}: {e}")

        # Try GNU3 demangling (for GCC/MinGW symbols)
        if name.startswith("_Z"):
            try:
                if not arch:
                    logger.debug(f"No arch provided for GNU3 demangling {name}")
                    return name
                result = demangle.demangle_gnu3(arch, name)
                if result and len(result) >= 2:
                    type_obj, name_parts = result
                    # Check if demangling succeeded - name_parts should be a list
                    if name_parts and isinstance(name_parts, list) and type_obj is not None:
                        demangled = demangle.get_qualified_name(name_parts)
                        if demangled and demangled != name:
                            logger.debug(f"Demangled GNU3: {name} → {demangled}")
                            return demangled
                    elif isinstance(name_parts, str) and name_parts == name:
                        # Demangling failed, Binary Ninja returned original name
                        logger.debug(
                            f"Binary Ninja could not demangle GNU3: {name[:100]}{'...' if len(name) > 100 else ''}"
                        )
            except Exception as e:
                logger.warning(f"GNU3 demangling failed for {name}: {e}")

    except ImportError:
        logger.debug("Binary Ninja demangle module not available")
    except Exception as e:
        logger.debug(f"Demangling failed for {name}: {e}")

    # Return original name if demangling failed
    return name


def _is_mangled(name: str) -> bool:
    """
    Quick check if a name appears to be mangled.

    Common mangling patterns:
    - Microsoft MSVC: Starts with '?' (e.g., '?foo@@YAXXZ')
    - GNU GCC: Starts with '_Z' (e.g., '_ZN3foo3barEv')
    - Some other patterns include '@', '@@', or complex character sequences

    Args:
        name: Function name to check

    Returns:
        True if name appears to be mangled
    """
    if not name:
        return False

    # Microsoft mangling
    if name.startswith("?"):
        return True

    # GNU mangling
    if name.startswith("_Z"):
        return True

    # Additional heuristics for other mangling schemes
    # MSVC can also use '@' for fastcall/stdcall decorations like _foo@4
    return "@" in name and not name.endswith("@PLT")


def add_demangled_property(node_props: dict, name: str, arch=None, platform=None) -> None:
    """
    Add demangled name to node properties if applicable.

    Modifies the props dict in-place to add 'demangled_name' if the name
    was successfully demangled.

    Args:
        node_props: Node properties dictionary to modify
        name: Function name to demangle
        arch: Optional architecture from Binary Ninja
        platform: Optional platform from Binary Ninja
    """
    if _is_mangled(name):
        demangled = demangle_name(name, arch, platform)
        if demangled and demangled != name:
            node_props["demangled_name"] = demangled
            node_props["mangled_name"] = name
