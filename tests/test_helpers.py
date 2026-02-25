"""Tests for core helpers."""

from __future__ import annotations

import pytest

from marco.core.helpers import compute_sha256, resolve_file_path


class TestComputeSha256:
    def test_known_content(self, tmp_path):
        f = tmp_path / "hello.bin"
        f.write_bytes(b"hello world")
        # SHA-256 of "hello world"
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert compute_sha256(str(f)) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert compute_sha256(str(f)) == expected


class TestResolveFilePath:
    def test_finds_file_in_search_path(self, tmp_path):
        f = tmp_path / "test.dll"
        f.write_bytes(b"MZ")
        result = resolve_file_path("test.dll", [str(tmp_path)])
        assert result == str(f)

    def test_raises_filenotfounderror(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_file_path("definitely_missing_binary.dll", [str(tmp_path)])

    def test_absolute_path(self, tmp_path):
        f = tmp_path / "abs.dll"
        f.write_bytes(b"MZ")
        result = resolve_file_path(str(f), [])
        assert result == str(f)

    def test_custom_search_paths_via_monkeypatch(self, tmp_path, monkeypatch):
        sub = tmp_path / "custom"
        sub.mkdir()
        f = sub / "mylib.dll"
        f.write_bytes(b"MZ")
        # Clear PATH and SystemRoot so only custom paths are searched
        monkeypatch.setenv("PATH", "")
        monkeypatch.delenv("SystemRoot", raising=False)
        result = resolve_file_path("mylib.dll", [str(sub)])
        assert result == str(f)
