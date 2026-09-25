"""R3 / requirement 8: private local data layout with canonicalised, contained
paths. Directories are 0700, files 0600, and every open is preceded by a
containment check."""
from __future__ import annotations

import os
from pathlib import Path

from .ids import is_opaque_id


class PathSafetyError(ValueError):
    pass


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - platform dependent
        pass
    return path


def init_data_dirs(config) -> None:
    ensure_private_dir(config.data_dir)
    for sub in (config.files_dir, config.vectors_dir, config.work_dir, config.model_cache_dir):
        ensure_private_dir(sub)


def safe_child(root: Path, *parts: str) -> Path:
    """Resolve ``root/parts`` and prove it stays inside ``root``.

    Every component must be a server-generated opaque ID: that alone rejects
    ``..``, absolute paths and separators, but we re-validate structurally and
    then canonicalise (resolving symlinks) and verify containment.
    """
    root = root.resolve()
    for part in parts:
        if not is_opaque_id(part):
            raise PathSafetyError("path component is not a server-generated opaque id")
        if part in (".", "..") or "/" in part or "\\" in part or "\x00" in part:
            raise PathSafetyError("illegal path component")
    candidate = root.joinpath(*parts)
    if ".." in candidate.parts:
        raise PathSafetyError("path traversal rejected")
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise PathSafetyError("path escapes the private data root")
    # Reject symlinked components anywhere between root and the target.
    probe = resolved
    while probe != root:
        if probe.is_symlink():
            raise PathSafetyError("symlink component rejected")
        probe = probe.parent
    return resolved


def write_private_bytes(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def open_private_write(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "wb")
