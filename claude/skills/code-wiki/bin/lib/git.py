"""Git operations used by code-wiki: HEAD lookup, diff between SHAs, last-touch.

All operations are read-only on the user's repository. Errors raise
`NotAGitRepo` when the working tree is not a git repository, or `GitError`
for other git failures.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """Raised when a git operation fails for a reason other than missing repo."""


class NotAGitRepo(GitError):
    """Raised when the project root is not (inside) a git repository."""


@dataclass(frozen=True)
class Change:
    """One file-level change between two commits.

    Attributes:
        status: One of 'A' (added), 'M' (modified), 'D' (deleted), 'R' (renamed).
        path: For A/M/D, the affected path. For R, the *new* path.
        old_path: Only set for renames; the previous path of the file.
    """
    status: str
    path: Path
    old_path: Path | None = None


def current_sha(project_root: Path) -> str:
    """Return the SHA of HEAD as a 40-character hex string."""
    out = _run(["rev-parse", "HEAD"], project_root)
    return out.strip()


def diff(project_root: Path, from_sha: str, to_sha: str) -> list[Change]:
    """List file-level changes between two commits, oldest → newest.

    Uses `git diff --name-status -M`. Renames are detected by git heuristics.
    """
    out = _run(
        ["diff", "--name-status", "-M", f"{from_sha}..{to_sha}"],
        project_root,
    )
    changes: list[Change] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        raw_status = parts[0]
        # R and C come with a similarity score, e.g. "R100", "R85", "C90".
        # We collapse them to a single-character status.
        kind = raw_status[0]
        if kind == "R":
            if len(parts) < 3:
                raise GitError(f"unexpected rename line: {line!r}")
            changes.append(Change(status="R", path=Path(parts[2]), old_path=Path(parts[1])))
        elif kind == "C":
            # Copy: treat as add of the new path; mark old_path so callers can
            # track if needed.
            if len(parts) < 3:
                raise GitError(f"unexpected copy line: {line!r}")
            changes.append(Change(status="A", path=Path(parts[2]), old_path=Path(parts[1])))
        elif kind in {"A", "M", "D"}:
            if len(parts) < 2:
                raise GitError(f"unexpected status line: {line!r}")
            changes.append(Change(status=kind, path=Path(parts[1])))
        elif kind == "T":
            # Type change (e.g. file → symlink). Treat as modify.
            changes.append(Change(status="M", path=Path(parts[1])))
        else:
            raise GitError(f"unknown diff status {raw_status!r} in line: {line!r}")
    return changes


def last_touched(project_root: Path, path: str | Path) -> str | None:
    """Return the SHA of the last commit that touched `path`, or None if no
    commit has touched it (e.g. the file is uncommitted or doesn't exist)."""
    target = str(path)
    try:
        out = _run(
            ["log", "-1", "--format=%H", "--", target],
            project_root,
        )
    except GitError:
        return None
    out = out.strip()
    return out or None


def _run(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout. Translate failures to GitError /
    NotAGitRepo with helpful messages."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        raise GitError(f"git is not installed or not on PATH: {e}") from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").lower()
        if "not a git repository" in stderr:
            raise NotAGitRepo(f"{cwd} is not a git repository") from e
        raise GitError(
            f"git {' '.join(args)} failed (exit {e.returncode}): {e.stderr.strip()}"
        ) from e
    return result.stdout
