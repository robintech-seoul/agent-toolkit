"""Content hashing for source files and wiki pages.

Used by state.json to detect drift (source changed since last ingestion) and
by lint to flag stale wikis. SHA-256 is overkill for collision avoidance but
is fast enough and standard.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


_BLOCK_SIZE = 64 * 1024


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's binary contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_BLOCK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(content: str) -> str:
    """Return the hex SHA-256 digest of `content` as UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
