"""Tests for Config."""

from __future__ import annotations

import pytest

from marco.core.config import Config


class TestLoadFromFile:
    def test_load_valid_key_value(self, tmp_path):
        cfg_file = tmp_path / "test.config"
        cfg_file.write_text("KEY1=value1\nKEY2=value2\n")
        cfg = Config(str(cfg_file))
        assert cfg.get("KEY1") == "value1"
        assert cfg.get("KEY2") == "value2"

    def test_skip_comments_and_blank_lines(self, tmp_path):
        cfg_file = tmp_path / "test.config"
        cfg_file.write_text("# comment\n\nKEY=val\n")
        cfg = Config(str(cfg_file))
        assert cfg.get("KEY") == "val"
        assert cfg.get("#") is None

    def test_malformed_line_raises_valueerror(self, tmp_path):
        cfg_file = tmp_path / "test.config"
        cfg_file.write_text("NOEQUALS\n")
        with pytest.raises(ValueError):
            Config(str(cfg_file))

    def test_missing_file_raises_filenotfounderror(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Config(str(tmp_path / "missing.config"))


class TestGet:
    def test_get_returns_value(self, tmp_path):
        cfg_file = tmp_path / "test.config"
        cfg_file.write_text("A=1\n")
        cfg = Config(str(cfg_file))
        assert cfg.get("A") == "1"

    def test_get_returns_default_for_missing(self):
        cfg = Config()
        assert cfg.get("MISSING", "fallback") == "fallback"

    def test_get_returns_none_for_missing_no_default(self):
        cfg = Config()
        assert cfg.get("MISSING") is None


class TestGetWithEnvFallback:
    def test_prefers_config_over_env(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "test.config"
        cfg_file.write_text("MY_KEY=from_config\n")
        monkeypatch.setenv("MY_KEY", "from_env")
        cfg = Config(str(cfg_file))
        assert cfg.get_with_env_fallback("MY_KEY") == "from_config"

    def test_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "from_env")
        cfg = Config()
        assert cfg.get_with_env_fallback("MY_KEY") == "from_env"

    def test_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_KEY_12345", raising=False)
        cfg = Config()
        assert cfg.get_with_env_fallback("NONEXISTENT_KEY_12345", "default") == "default"


class TestDiscover:
    def test_discover_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "explicit.config"
        cfg_file.write_text("X=1\n")
        cfg = Config.discover(str(cfg_file))
        assert cfg.get("X") == "1"

    def test_discover_returns_empty_when_nothing_found(self, tmp_path, monkeypatch):
        # Change to a temp dir with no config files
        monkeypatch.chdir(tmp_path)
        cfg = Config.discover()
        assert cfg.get("anything") is None
