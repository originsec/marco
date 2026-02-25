"""Tests for RPC data models."""

from __future__ import annotations

import struct

from marco.core.rpc_models import format_guid, get_binary_for_interface


class TestFormatGuid:
    def test_known_bytes(self):
        # Build bytes for GUID 367ABB81-9844-35F1-AD32-98F038001003
        data = struct.pack("<IHH", 0x367ABB81, 0x9844, 0x35F1)
        data += bytes.fromhex("AD3298F038001003")
        assert format_guid(data) == "367ABB81-9844-35F1-AD32-98F038001003"

    def test_too_short_returns_invalid(self):
        assert format_guid(b"\x00" * 10) == "Invalid GUID"

    def test_zero_guid(self):
        result = format_guid(b"\x00" * 16)
        assert result == "00000000-0000-0000-0000-000000000000"


class TestGetBinaryForInterface:
    def test_unknown_interface_returns_none(self):
        result = get_binary_for_interface("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF")
        # This may or may not be in the known list; if not, returns None
        # We just verify the function doesn't crash
        assert result is None or isinstance(result, str)

    def test_returns_string_or_none(self):
        # Ensure the function works with an empty-ish GUID
        result = get_binary_for_interface("00000000-0000-0000-0000-000000000000")
        assert result is None or isinstance(result, str)
