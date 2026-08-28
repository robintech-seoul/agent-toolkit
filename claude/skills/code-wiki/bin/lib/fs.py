"""Filesystem traversal for code-wiki.

Walks a source root, applies gitignore-style ignore patterns, and yields each
non-empty folder in bottom-up order (post-order DFS) along with its direct
loose files and surviving sub-directories.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class FolderInfo:
    """One folder's view as seen by the walk.

    Attributes:
        path: Absolute path to the folder.
        relpath: POSIX path relative to the source root ("" for the root itself).
        is_leaf: True if the folder has no surviving sub-directories after
                 applying ignore patterns. (A folder whose only sub-directories
                 are all ignored is treated as a leaf.)
        loose_files: Absolute paths to files directly in this folder, with
                     ignored files filtered out. Sorted by name.
        child_dirs: Absolute paths to direct child directories that survived
                    pruning. Sorted by name.
    """
    path: Path
    relpath: str
    is_leaf: bool
    loose_files: list[Path] = field(default_factory=list)
    child_dirs: list[Path] = field(default_factory=list)


def walk_source_root(
    source_root: Path,
    ignore_patterns: list[str],
) -> Iterator[FolderInfo]:
    """Yield folders under `source_root` in bottom-up order.

    A folder is yielded only if it has at least one loose file or one surviving
    child directory after applying `ignore_patterns`. Empty/fully-ignored folders
    are pruned and never yielded.

    `ignore_patterns` follow gitignore-like syntax. Supported forms:
      - `name`            → matches any file/dir whose basename matches glob `name`
      - `**/name/**`      → matches any path that contains `name` as a segment
      - `**/glob`         → matches any path whose basename matches `glob`
      - `prefix/**`       → matches anything inside `prefix/`
      - `path/glob`       → fnmatch on the full relative path
    """
    if not source_root.is_dir():
        raise ValueError(f"source_root is not a directory: {source_root}")
    yield from _walk(source_root, "", ignore_patterns)


def is_ignored(relpath: str, patterns: list[str]) -> bool:
    """Check whether `relpath` (a POSIX path relative to the source root) should
    be ignored by `patterns`.

    The basename of the path is also tested against bare-name patterns (no `/`).
    """
    if not relpath:
        return False
    parts = relpath.split("/")
    name = parts[-1]

    for pattern in patterns:
        if "/" not in pattern:
            # Bare-name pattern: match any basename in the path against it.
            if any(fnmatch.fnmatchcase(part, pattern) for part in parts):
                return True
            continue

        # Path-aware patterns.
        if pattern.startswith("**/") and pattern.endswith("/**"):
            segment = pattern[3:-3]
            if segment in parts:
                return True
            continue

        if pattern.startswith("**/"):
            tail = pattern[3:]
            if fnmatch.fnmatchcase(name, tail):
                return True
            continue

        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if relpath == prefix or relpath.startswith(prefix + "/"):
                return True
            continue

        # Generic path glob.
        if fnmatch.fnmatchcase(relpath, pattern):
            return True

    return False


def _walk(
    folder: Path,
    relpath: str,
    patterns: list[str],
) -> Iterator[FolderInfo]:
    """Post-order DFS walker.

    `folder` is always reachable (the caller has already confirmed it isn't
    ignored). `relpath` is the POSIX-form path relative to the source root.
    """
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name)
    except OSError:
        return

    loose_files: list[Path] = []
    sub_dirs: list[Path] = []
    for entry in entries:
        # Build relative path for ignore checks.
        entry_rel = f"{relpath}/{entry.name}" if relpath else entry.name
        if is_ignored(entry_rel, patterns):
            continue
        if entry.is_dir():
            sub_dirs.append(entry)
        elif entry.is_file():
            loose_files.append(entry)
        # Symlinks/other special files are skipped.

    # Recurse into surviving sub-directories first (bottom-up emission).
    surviving_children: list[Path] = []
    for sd in sub_dirs:
        sd_rel = f"{relpath}/{sd.name}" if relpath else sd.name
        emitted_any = False
        for info in _walk(sd, sd_rel, patterns):
            yield info
            # Only count this subdir as "surviving" if its own root was emitted
            # (i.e. the child folder itself had loose files or surviving grand-
            # children). That happens when we see a FolderInfo whose path is sd.
            if info.path == sd:
                emitted_any = True
        if emitted_any:
            surviving_children.append(sd)

    # Decide whether to yield this folder. A folder is yielded if it has at
    # least one loose file or at least one surviving child directory.
    if not loose_files and not surviving_children:
        return

    yield FolderInfo(
        path=folder,
        relpath=relpath,
        is_leaf=not surviving_children,
        loose_files=loose_files,
        child_dirs=surviving_children,
    )
