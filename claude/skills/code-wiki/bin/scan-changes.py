#!/usr/bin/env python3
"""Compute the dirty work-set for `/code-wiki:sync` from git diff + current state.

Reads `wiki/config.yaml` and `.code-wiki/state.json`, then runs
`git diff --name-status -M <last_ingested_sha>..HEAD` to find changed source
files. Maps changes to wiki pages, propagates dirty-marks up to source roots,
and identifies wiki pages whose source folder has disappeared (deletions).

Output (stdout, JSON):
{
  "from_sha":   "...",
  "to_sha":     "...",
  "pages":      [<work items, same shape as walk-tree.py>],   // dirty leaves + parents to (re)generate
  "deletions":  ["wiki/src/old/index.md", ...],               // wiki pages whose source folder is gone
  "dirty_topics": ["wiki/topics/auth.md", ...]                // topics whose recorded sources changed
}

Errors:
- state.json missing → exit 2 (caller should soft-bootstrap first).
- last_ingested_sha not set → exit 2 (no prior ingest).
- not a git repo → exit 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg  # noqa: E402
from lib import fs  # noqa: E402
from lib import git as gitlib  # noqa: E402
from lib import state as st  # noqa: E402
from lib import wiki_path as wp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute dirty work-set for sync.")
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()

    project_root = args.project_root.resolve()

    state = st.load(project_root)
    if state is None:
        print("Error: .code-wiki/state.json not found. Run state-bootstrap first.",
              file=sys.stderr)
        return 2
    last_sha = state.get("last_ingested_sha")
    if not last_sha:
        print("Error: state.json has no last_ingested_sha. Run /code-wiki:build first.",
              file=sys.stderr)
        return 2

    try:
        config = cfg.load(project_root)
    except cfg.ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        head_sha = gitlib.current_sha(project_root)
        changes = gitlib.diff(project_root, last_sha, head_sha)
    except gitlib.NotAGitRepo as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except gitlib.GitError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    ignore_patterns: list[str] = config.get("ignore_patterns", []) or []
    source_roots: list[str] = [e["path"] for e in config["source_roots"]]

    # 1. Reduce changes to (project-root-relative path, kind, optional old path).
    #    For renames: old-path is treated as deletion, new-path as add.
    changed_paths: set[str] = set()
    deleted_paths: set[str] = set()
    for change in changes:
        if change.status == "D":
            deleted_paths.add(_to_posix(change.path))
        elif change.status == "R":
            # Old vanishes, new appears.
            if change.old_path is not None:
                deleted_paths.add(_to_posix(change.old_path))
            changed_paths.add(_to_posix(change.path))
        else:
            # A or M
            changed_paths.add(_to_posix(change.path))

    # 2. Filter to source-root membership and not-ignored.
    def in_source_root(p: str) -> str | None:
        for root in source_roots:
            if p == root or p.startswith(root + "/"):
                return root
        return None

    def keep(p: str) -> bool:
        root = in_source_root(p)
        if root is None:
            return False
        rel_to_root = p[len(root) + 1:] if p != root else ""
        if rel_to_root and fs.is_ignored(rel_to_root, ignore_patterns):
            return False
        return True

    changed_paths = {p for p in changed_paths if keep(p)}
    deleted_paths = {p for p in deleted_paths if keep(p)}

    # 3. Build dirty folder set.
    #    (a) Folder-based: parent folder of each changed/deleted file, plus
    #        all ancestors up to the source root.
    #    (b) Cross-link-based (per SPEC §7): for any wiki that source_to_wiki
    #        says references the changed file, mark its folder dirty too. This
    #        catches cross-references from one folder's wiki to a source file
    #        that lives in another folder.
    dirty_folders: set[str] = set()

    def _add_ancestors(start: str) -> None:
        cur = start
        while cur:
            root = in_source_root(cur)
            if root is None:
                break
            dirty_folders.add(cur)
            if cur == root:
                break
            cur = _parent(cur)

    for path in changed_paths | deleted_paths:
        _add_ancestors(_parent(path))
        # Cross-link propagation: every wiki that references this file is dirty.
        for wiki_p in state["source_to_wiki"].get(path, []):
            sf = wp.wiki_to_source_folder(wiki_p)
            if sf is None:
                continue  # topics handled separately below
            _add_ancestors(str(sf))

    # 4. Walk each source root that has any dirty folder; emit work items for
    #    folders that are dirty.
    pages: list[dict] = []
    folders_seen_now: set[str] = set()  # project-root-relative

    for root in source_roots:
        # Quick skip: if no dirty folder under this root, skip walking it.
        if not any(d == root or d.startswith(root + "/") for d in dirty_folders):
            continue
        root_abs = project_root / root
        if not root_abs.is_dir():
            continue
        for info in fs.walk_source_root(root_abs, ignore_patterns):
            folder_relpath = root if not info.relpath else f"{root}/{info.relpath}"
            folders_seen_now.add(folder_relpath)
            if folder_relpath not in dirty_folders:
                continue
            source_files = sorted(
                f"{folder_relpath}/{p.name}" for p in info.loose_files
            )
            child_wikis = sorted(
                str(wp.source_folder_to_wiki(f"{folder_relpath}/{c.name}"))
                for c in info.child_dirs
            )
            wiki_p = str(wp.source_folder_to_wiki(folder_relpath))
            pages.append({
                "source_root": root,
                "folder_relpath": folder_relpath,
                "kind": "leaf" if info.is_leaf else "parent",
                "source_files": source_files,
                "child_wikis": child_wikis,
                "wiki_path": wiki_p,
            })

    # 5. Deletions: any wiki page in state whose source folder is no longer
    #    present in the current walk (and whose path is under one of the
    #    walked source roots).
    deletions: list[str] = []
    for wiki_p, entry in state["wiki_pages"].items():
        if entry.get("kind") == "topic":
            continue  # topics are tracked separately
        # Map wiki path → source folder (project-root-relative).
        source_folder = wp.wiki_to_source_folder(wiki_p)
        if source_folder is None:
            continue
        sf = str(source_folder)
        # Is this folder under a source root we walked? If so and we didn't
        # see it, it's been deleted.
        root = in_source_root(sf)
        if root is None:
            continue
        if not any(d == root or d.startswith(root + "/") for d in dirty_folders):
            # We didn't walk this root at all; can't conclude deletion.
            continue
        if sf not in folders_seen_now:
            deletions.append(wiki_p)

    # 6. Dirty topics: any topic whose source_files intersect changed files.
    changed_or_deleted = changed_paths | deleted_paths
    dirty_topics: list[str] = []
    for wiki_p, entry in state["wiki_pages"].items():
        if entry.get("kind") != "topic":
            continue
        if any(sf in changed_or_deleted for sf in entry.get("source_files", [])):
            dirty_topics.append(wiki_p)

    # Output
    json.dump({
        "from_sha": last_sha,
        "to_sha": head_sha,
        "pages": pages,
        "deletions": sorted(deletions),
        "dirty_topics": sorted(dirty_topics),
    }, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _to_posix(p) -> str:
    return str(p).replace("\\", "/")


def _parent(p: str) -> str:
    """Return the POSIX-style parent of `p`, or '' if there is no parent within
    the relative-path namespace (i.e. `p` has no slash)."""
    idx = p.rfind("/")
    return p[:idx] if idx > 0 else ""


if __name__ == "__main__":
    sys.exit(main())
