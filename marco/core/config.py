from __future__ import annotations

import os
from pathlib import Path


def get_neo4j_credentials(config: Config | None = None) -> tuple[str, str, str]:
    """Resolve Neo4j credentials from config > env > defaults."""

    def _get(key: str, default: str) -> str:
        if config:
            return config.get_with_env_fallback(key, default) or default
        return os.getenv(key, default)

    return (
        _get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        _get("NEO4J_USER", "neo4j"),
        _get("NEO4J_PASSWORD", "neo4j"),
    )


class Config:
    """General configuration parser for marco. Supports KEY=VALUE format."""

    _AUTODISCOVER_PATHS = ["marco.config", "~/.marco.config"]

    def __init__(self, config_path: str | None = None):
        self._values: dict[str, str] = {}

        if config_path:
            self.load_from_file(config_path)

    @classmethod
    def discover(cls, explicit_path: str | None = None) -> Config:
        """Load config from an explicit path, or auto-discover from standard locations.

        Search order (first match wins):
          1. explicit_path (if provided)
          2. ./marco.config
          3. ~/.marco.config

        Returns an empty Config if no file is found.
        """
        candidates = [explicit_path] if explicit_path else cls._AUTODISCOVER_PATHS
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.exists():
                return cls(str(path))
        return cls()

    def load_from_file(self, config_path: str) -> None:
        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                if "=" not in line:
                    raise ValueError(f"Invalid config line {line_num}: {line}")

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                self._values[key] = value

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._values.get(key, default)

    def get_with_env_fallback(self, key: str, default: str | None = None) -> str | None:
        """Config file > environment variable > default."""
        config_value = self.get(key)
        if config_value is not None:
            return config_value

        env_value = os.getenv(key)
        if env_value is not None:
            return env_value

        return default

    def __repr__(self) -> str:
        return f"Config({len(self._values)} values)"
