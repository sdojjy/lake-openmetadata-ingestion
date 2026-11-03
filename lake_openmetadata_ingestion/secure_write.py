"""Helpers for writing secrets to disk without a permissions race.

``Path.write_text()`` creates the file at the prevailing umask (commonly 0644) and only a later
``chmod(0o600)`` narrows it: between the two calls the secret on disk is world-readable, and the same
call follows symlinks. Everything here writes through ``mkstemp`` (created 0600 by ``os.open``) and
renames into place, so the secret is never observable with looser permissions and a pre-existing
symlink at the destination is replaced rather than followed.

Windows: ``os.fchmod`` is Unix-only and POSIX permission bits do not really exist there, so the mode
is best-effort (``os.chmod`` on Windows only toggles the read-only bit); ``mkstemp`` already creates
the file with the closest equivalent of 0600.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

DEFAULT_SECRET_MODE = 0o600


def write_secret_file(path: str | Path, data: str, mode: int = DEFAULT_SECRET_MODE) -> Path:
    """Atomically write ``data`` to ``path`` with permissions ``mode`` (default 0600)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        # os.fchmod is Unix-only (it does not exist on Windows). mkstemp already made the file 0600,
        # so the fallback narrows the temp path with os.chmod *before* anything is written to it.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        else:  # pragma: no cover - Windows only
            os.chmod(tmp_name, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        # Same-directory rename: atomic, and it replaces a symlink instead of writing through it.
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return path


def token_fingerprint(token: str) -> str:
    """Short, non-reversible identifier for a token, safe to print to a log or stdout."""
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
