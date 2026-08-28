"""Path math for code-wiki: source ↔ wiki mapping and relative-link computation.

All paths in this module are project-root-relative POSIX paths unless explicitly
labeled. Off-by-one errors in `relative_link` would break every source link in
every generated wiki page, so the actual relative computation delegates to
`os.path.relpath` (battle-tested) rather than counting slashes by hand.
"""

from __future__ import annotations

import os.path
from pathlib import Path, PurePosixPath


WIKI_DIR = PurePosixPath("wiki")
INDEX_NAME = "index.md"


def source_folder_to_wiki(folder_relpath: str | Path) -> PurePosixPath:
    """Map a source folder (project-root-relative) to its wiki index path.

    Examples:
        'src'           → 'wiki/src/index.md'
        'src/auth'      → 'wiki/src/auth/index.md'
        'apps/web/src'  → 'wiki/apps/web/src/index.md'
    """
    p = PurePosixPath(str(folder_relpath))
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"folder_relpath must be a clean relative path: {folder_relpath!r}")
    return WIKI_DIR / p / INDEX_NAME


def source_file_to_wiki(file_relpath: str | Path) -> PurePosixPath:
    """Map a source file path to its per-file wiki page path.

    The file's extension is dropped; the wiki page uses `.md`. The wiki page
    lives in the same directory as the leaf folder's `index.md`.

    Examples:
        'src/auth/login.py'  → 'wiki/src/auth/login.md'
        'src/main.ts'        → 'wiki/src/main.md'

    Note: if a folder has both `foo.py` and a sub-folder `foo/`, the per-file
    page `wiki/.../foo.md` does not collide with `wiki/.../foo/index.md`. But
    if it has `foo.py` AND `foo.ts` in the same folder, both would produce
    `foo.md` — that pathology is detected at generation time.
    """
    p = PurePosixPath(str(file_relpath))
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"file_relpath must be a clean relative path: {file_relpath!r}")
    if not p.parts:
        raise ValueError("file_relpath must not be empty")
    return WIKI_DIR / p.parent / f"{p.stem}.md"


def wiki_to_source_folder(wiki_relpath: str | Path) -> PurePosixPath | None:
    """Inverse of `source_folder_to_wiki` (and a partial inverse of
    `source_file_to_wiki`).

    For a folder index page (`wiki/X/Y/index.md`) → returns `X/Y`.
    For a per-file page    (`wiki/X/Y/foo.md`)   → returns `X/Y` (the parent
                                                   folder; the original file's
                                                   extension is lost).
    For paths not under `wiki/`, returns `None`.

    Returns `None` rather than the empty path when the input is exactly
    `wiki/index.md` (i.e. there is no enclosing source folder under wiki).
    """
    p = PurePosixPath(str(wiki_relpath))
    if not p.parts or p.parts[0] != "wiki":
        return None
    inner = p.parts[1:]  # drop the 'wiki' prefix
    if not inner:
        return None
    if inner[-1] == INDEX_NAME:
        # Folder wiki: drop the index.md to get the folder.
        folder_parts = inner[:-1]
    else:
        # Per-file wiki: drop the file's basename to get the parent folder.
        folder_parts = inner[:-1]
    if not folder_parts:
        return None
    return PurePosixPath(*folder_parts)


def is_index(wiki_relpath: str | Path) -> bool:
    """True if the wiki page is a folder's `index.md` (vs. a per-file page)."""
    p = PurePosixPath(str(wiki_relpath))
    return p.name == INDEX_NAME


def relative_link(from_wiki: str | Path, to_target: str | Path) -> str:
    """Compute a markdown-friendly relative path from a wiki page to a target.

    Both inputs are paths relative to the project root. Returns a POSIX-style
    forward-slash path suitable to drop into a markdown link.

    The wiki page's "location" for relative-link resolution is its containing
    directory. So the link is computed from `dirname(from_wiki)` to `to_target`.

    Examples:
        from_wiki='wiki/src/api/auth/index.md', to_target='src/api/auth/auth.ts'
            → '../../../../src/api/auth/auth.ts'
        from_wiki='wiki/src/index.md', to_target='wiki/src/auth/index.md'
            → 'auth/index.md'
    """
    from_dir = str(PurePosixPath(str(from_wiki)).parent)
    target = str(PurePosixPath(str(to_target)))
    rel = os.path.relpath(target, from_dir)
    # os.path.relpath uses os.sep; force POSIX for consistent markdown.
    return rel.replace(os.sep, "/")
