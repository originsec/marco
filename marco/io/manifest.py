from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# A manifest entry represents a module that has been analyzed.
# It's used to track which modules have been analyzed so that
# we don't re-analyze them unnecessarily.
@dataclass
class ManifestEntry:
    module: str
    path: str
    sha256: str
    file_version: str | None


class Manifest:
    def __init__(self, path: str):
        self.path = path
        self.entries: dict[str, ManifestEntry] = {}
        if Path(path).exists():
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                    for k, v in raw.items():
                        self.entries[k] = ManifestEntry(**v)
            except Exception:
                logger.warning("Failed to load manifest from %s, starting fresh", path, exc_info=True)
                self.entries = {}

    def has_sha(self, sha256: str) -> bool:
        return sha256 in self.entries

    def get(self, sha256: str) -> ManifestEntry | None:
        return self.entries.get(sha256)

    def add(self, entry: ManifestEntry) -> None:
        self.entries[entry.sha256] = entry

    def save(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in self.entries.items()}, f, indent=2)
