from __future__ import annotations

from typing import Protocol

from ..core.models import ExtractionResult


class Extractor(Protocol):
    name: str

    def extract(self, **kwargs) -> ExtractionResult: ...
