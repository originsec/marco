"""Auto-discover Binary Ninja Python API for isolated environments (uv, uvx)."""

from __future__ import annotations

import logging
import os
import site
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def ensure_binaryninja_importable() -> None:
    """Add Binary Ninja's Python API to sys.path if not already importable."""
    try:
        import binaryninja  # noqa: F401

        return
    except ImportError:
        pass

    candidates: list[str] = []

    # 1. Explicit override via environment variable
    env = os.environ.get("BINJA_PATH")
    if env:
        candidates.append(env)

    # 2. Look for binaryninja.pth in the base Python's site-packages
    try:
        for sp in site.getsitepackages([sys.base_prefix]):
            pth = Path(sp) / "binaryninja.pth"
            if pth.is_file():
                with open(pth) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            candidates.append(line)
    except Exception:
        pass

    # 3. Platform-specific default install locations
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(os.path.join(local, "Vector35", "BinaryNinja", "python"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/Binary Ninja.app/Contents/Resources/python")
    else:
        candidates.append(str(Path("~/binaryninja/python").expanduser()))

    for path in candidates:
        if (Path(path) / "binaryninja").is_dir():
            logger.debug("Auto-discovered Binary Ninja API at %s", path)
            sys.path.insert(0, path)
            return
