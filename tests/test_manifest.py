"""Tests for Manifest."""

from __future__ import annotations

from marco.io.manifest import Manifest, ManifestEntry


class TestManifest:
    def test_add_and_has_sha(self, tmp_path):
        m = Manifest(str(tmp_path / "manifest.json"))
        entry = ManifestEntry(
            module="kernel32", path="C:\\Windows\\System32\\kernel32.dll", sha256="abc123", file_version="10.0"
        )
        m.add(entry)
        assert m.has_sha("abc123")
        assert not m.has_sha("other")

    def test_save_and_reload(self, tmp_path):
        path = str(tmp_path / "manifest.json")
        m = Manifest(path)
        entry = ManifestEntry(module="ntdll", path="/ntdll.dll", sha256="sha_ntdll", file_version=None)
        m.add(entry)
        m.save()

        m2 = Manifest(path)
        assert m2.has_sha("sha_ntdll")
        loaded = m2.get("sha_ntdll")
        assert loaded is not None
        assert loaded.module == "ntdll"

    def test_load_nonexistent_path_empty(self, tmp_path):
        m = Manifest(str(tmp_path / "nonexistent.json"))
        assert len(m.entries) == 0

    def test_load_corrupt_json_empty(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{{{INVALID")
        m = Manifest(str(path))
        assert len(m.entries) == 0

    def test_get_returns_entry_or_none(self, tmp_path):
        m = Manifest(str(tmp_path / "manifest.json"))
        assert m.get("missing") is None
        entry = ManifestEntry(module="x", path="/x", sha256="s1", file_version=None)
        m.add(entry)
        assert m.get("s1") is entry
