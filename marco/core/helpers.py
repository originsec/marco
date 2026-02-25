import hashlib
import os
import re
from collections.abc import Iterable
from pathlib import Path


def resolve_file_path(filename: str, search_paths: Iterable[str] = ()):  # windows-centric resolution
    if Path(filename).is_absolute() and Path(filename).exists():
        return filename

    # current dir
    if Path(filename).exists():
        return str(Path(filename).resolve())

    # PATH
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path, filename)
        if Path(candidate).exists():
            return candidate

    # System32, SysWOW64, drivers for Windows
    system_root = os.environ.get("SYSTEMROOT")
    if system_root:
        candidates = [
            os.path.join(system_root, "System32", filename),
            os.path.join(system_root, "SysWOW64", filename),
            os.path.join(system_root, "System32", "drivers", filename),
            os.path.join(system_root, "SysWOW64", "drivers", filename),
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate

    # user-provided paths
    for path in search_paths:
        candidate = os.path.join(path, filename)
        if Path(candidate).exists():
            return candidate

    # Retry with .dll extension if the bare name has no extension
    if not Path(filename).suffix:
        return resolve_file_path(filename + ".dll", search_paths)

    raise FileNotFoundError(f"Couldn't find {filename}")


def sanitize_for_fs(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    cleaned = cleaned.strip(" .") or "item"
    return cleaned


def compute_sha256(file_path: str) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(1024 * 1024)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()
