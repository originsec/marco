"""Shared binary analysis utilities used across extractors.

This module contains common functions for analyzing binaries with disassemblers,
particularly for finding register values, symbols, and function references.
"""

from __future__ import annotations

import logging

from ..disassemblers import DisassemblerAdapter

logger = logging.getLogger(__name__)


def find_register_value_asm(bv, adapter: DisassemblerAdapter, func, call_addr: int, register: str) -> int | None:
    """Search backwards from call site for a mov/lea assignment to the given register."""
    try:
        instructions = list(adapter.iter_instructions(func))

        call_idx = -1
        for i, (addr, _size, _tokens) in enumerate(instructions):
            if addr == call_addr:
                call_idx = i
                break

        if call_idx == -1:
            return None

        for i in range(call_idx - 1, max(0, call_idx - 50), -1):
            addr, size, tokens = instructions[i]

            text_tokens = []
            value_token = None

            for token in tokens:
                text_tokens.append(token.text if hasattr(token, "text") else str(token))
                # Look for address/value tokens
                if (
                    hasattr(token, "value")
                    and hasattr(token, "type")
                    and ("Address" in str(token.type) or "Integer" in str(token.type))
                ):
                    value_token = token.value

            token_text = " ".join(text_tokens).lower()

            if (
                register in token_text
                and ("lea" in token_text or "mov" in token_text)
                and value_token
                and value_token > 0x100000000
            ):
                return value_token

        return None

    except Exception as e:
        logger.debug(f"Error in assembly analysis: {e}")
        return None


def get_containing_function(bv, adapter: DisassemblerAdapter, address: int):
    """Return the function containing the given address, or None."""
    for func in adapter.iter_functions(bv):
        func_start = adapter.function_address(func)
        if hasattr(func, "lowest_address") and hasattr(func, "highest_address"):
            if func.lowest_address <= address <= func.highest_address:
                return func
        elif func_start <= address <= func_start + 0x10000:
            return func
    return None


def has_symbol(bv, symbol_name: str) -> bool:
    try:
        symbols = bv.symbols.get(symbol_name, [])
        return len(symbols) > 0
    except Exception:
        return False


def get_call_references(bv, symbol_name: str) -> list[int]:
    references = []
    try:
        symbols = bv.symbols.get(symbol_name, [])
        for symbol in symbols:
            if hasattr(symbol, "address"):
                # Get code references to this symbol
                refs = bv.get_code_refs(symbol.address)
                for ref in refs:
                    if hasattr(ref, "address"):
                        references.append(ref.address)
    except Exception as e:
        logger.debug(f"Error getting references for {symbol_name}: {e}")
    return references


def get_function_name_at_address(bv, adapter: DisassemblerAdapter, address: int) -> str | None:
    try:
        func = bv.get_function_at(address) if hasattr(bv, "get_function_at") else None
        if func:
            return adapter.function_name(func)

        symbol = bv.get_symbol_at(address) if hasattr(bv, "get_symbol_at") else None
        if symbol:
            return symbol.name if hasattr(symbol, "name") else str(symbol)

    except Exception as e:
        logger.debug(f"Error getting function name at {hex(address)}: {e}")

    return None
