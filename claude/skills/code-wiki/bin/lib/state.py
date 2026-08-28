"""Read and write `.code-wiki/state.json` atomically.

Schema reference: SPEC.md §7.

State is local/per-machine and not committed. If state.json is missing, callers
should soft-bootstrap (see bin/state-bootstrap.py) before performing operations
that depend on `last_ingested_sha`.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


STATE_PATH = Path(".code-wiki/state.json")
SCHEMA_VERSION = 1


class StateCorrupted(Exception):
    """Raised when state.json fails schema validation. The recommended recovery is
    to delete state.json and run `/code-wiki:sync` (which will soft-bootstrap)."""


def load(project_root: Path) -> dict[str, Any] | None:
    """Load state.json. Returns None if it does not exist (the caller should
    decide whether to bootstrap or fail). Raises StateCorrupted on schema error."""
    path = project_root / STATE_PATH
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise StateCorrupted(
            f"{STATE_PATH} is not valid JSON: {e}. "
            f"Delete it and run /code-wiki:sync to soft-bootstrap."
        ) from e

    _validate(data)
    return data


def save(project_root: Path, state: dict[str, Any]) -> None:
    """Write state.json atomically (temp file in same dir + os.replace).

    Atomic-ness matters because partial writes corrupt state and would force
    a costly rebuild.
    """
    _validate(state)
    target = project_root / STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file in the same directory so os.replace is atomic on POSIX.
    fd, tmp_name = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        # Best-effort cleanup; re-raise for the caller.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def empty_state() -> dict[str, Any]:
    """Return a fresh empty state suitable as a starting point."""
    return {
        "version": SCHEMA_VERSION,
        "last_ingested_sha": None,
        "wiki_pages": {},
        "source_to_wiki": {},
        "source_hashes": {},
    }


def _validate(state: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise StateCorrupted("state.json must be a JSON object at the top level")
    if state.get("version") != SCHEMA_VERSION:
        raise StateCorrupted(
            f"state.json version must be {SCHEMA_VERSION}; got {state.get('version')!r}"
        )
    for key, expected_type in (
        ("wiki_pages", dict),
        ("source_to_wiki", dict),
        ("source_hashes", dict),
    ):
        if key not in state:
            raise StateCorrupted(f"state.json missing required field {key!r}")
        if not isinstance(state[key], expected_type):
            raise StateCorrupted(
                f"state.json field {key!r} must be a {expected_type.__name__}"
            )
    # last_ingested_sha may be None (post-bootstrap-failure) or a string.
    sha = state.get("last_ingested_sha")
    if sha is not None and not isinstance(sha, str):
        raise StateCorrupted("state.json field 'last_ingested_sha' must be string or null")
