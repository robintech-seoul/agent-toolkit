#!/usr/bin/env python3
"""Reconstruct `.code-wiki/state.json` from a committed `wiki/` directory.

Used after a clone (`wiki/` is committed but `.code-wiki/` is not). Walks the
existing wiki, parses its outbound links to rebuild the source↔wiki indices,
computes content hashes, and infers `last_ingested_sha` from git log.

Output: writes `.code-wiki/state.json`. Prints a JSON summary on stdout.

Errors:
- `wiki/` missing → exit 1.
- `state.json` already exists and `--force` not supplied → exit 1.
- No commit touches `wiki/` → exit 1.
- Not a git repo → exit 1.
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
from lib import hashing  # noqa: E402
from lib import links as links_lib  # noqa: E402
from lib import state as st  # noqa: E402
from lib import wiki_path as wp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Soft-bootstrap state.json from wiki/.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing state.json.")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    wiki_root = project_root / "wiki"
    if not wiki_root.is_dir():
        print(f"Error: {wiki_root} does not exist. Run /code-wiki:init first.",
              file=sys.stderr)
        return 1
    if (project_root / ".code-wiki" / "state.json").exists() and not args.force:
        print("Error: .code-wiki/state.json already exists. Pass --force to overwrite.",
              file=sys.stderr)
        return 1

    try:
        config = cfg.load(project_root)
    except cfg.ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Step 1: infer last_ingested_sha from git log.
    last_sha = gitlib.last_touched(project_root, "wiki")
    if last_sha is None:
        print("Error: wiki/ has not been committed; run /code-wiki:build first.",
              file=sys.stderr)
        return 1

    # Step 2: walk source roots to learn structural facts (which folders are
    # leaf vs parent right now).
    source_roots: list[str] = [e["path"] for e in config["source_roots"]]
    ignore_patterns: list[str] = config.get("ignore_patterns", []) or []
    folder_info: dict[str, dict] = {}  # folder_relpath → {"is_leaf": bool, "child_dirs": [str], "loose_files": [str]}
    for root in source_roots:
        root_abs = project_root / root
        if not root_abs.is_dir():
            continue
        for info in fs.walk_source_root(root_abs, ignore_patterns):
            folder_relpath = root if not info.relpath else f"{root}/{info.relpath}"
            folder_info[folder_relpath] = {
                "is_leaf": info.is_leaf,
                "child_dirs": [c.name for c in info.child_dirs],
                "loose_files": [f.name for f in info.loose_files],
            }

    # Step 3: walk all wiki pages and reconstruct state.
    state = st.empty_state()
    state["last_ingested_sha"] = last_sha

    seen_source_files: set[str] = set()

    for wiki_file in sorted(wiki_root.rglob("*.md")):
        wiki_relpath = str(wiki_file.relative_to(project_root)).replace("\\", "/")

        # Skip the schema file. Its content is user-curated, not auto-generated.
        if wiki_relpath == "wiki/CLAUDE.md":
            continue

        # Skip config.yaml — though it has no .md extension, defensive.
        if wiki_relpath.endswith("config.yaml"):
            continue

        content = wiki_file.read_text(encoding="utf-8")
        outbound = links_lib.parse_outbound(
            content, page_relpath=wiki_relpath, source_roots=source_roots
        )
        source_files = sorted({l.target for l in outbound if l.kind == "source"})
        referenced_wikis = sorted({l.target for l in outbound if l.kind == "wiki"})

        # Classify by path.
        kind, child_wikis = _classify_page(wiki_relpath, folder_info, referenced_wikis)

        state["wiki_pages"][wiki_relpath] = {
            "kind": kind,
            "source_files": source_files,
            "child_wikis": child_wikis,
            "referenced_wikis": referenced_wikis if kind == "topic" else [],
            "content_hash": "sha256:" + hashing.sha256_file(wiki_file),
        }
        for sf in source_files:
            state["source_to_wiki"].setdefault(sf, []).append(wiki_relpath)
            seen_source_files.add(sf)

    # Step 4: compute source_hashes for all referenced source files that exist.
    for sf in seen_source_files:
        path = project_root / sf
        if path.is_file():
            state["source_hashes"][sf] = "sha256:" + hashing.sha256_file(path)

    st.save(project_root, state)

    print(json.dumps({
        "last_ingested_sha": last_sha,
        "wiki_pages": len(state["wiki_pages"]),
        "source_files": len(state["source_to_wiki"]),
    }))
    return 0


def _classify_page(
    wiki_relpath: str,
    folder_info: dict,
    referenced_wikis: list[str],
) -> tuple[str, list[str]]:
    """Decide the page's `kind` and (for parents) its `child_wikis`.

    Classification rules:
      - `wiki/topics/<name>.md` → topic.
      - `wiki/.../index.md` → leaf or parent based on the walk's folder_info;
        if not in folder_info (e.g. source folder gone), classify as leaf.
      - Other `wiki/.../<name>.md` (non-index) → perfile.
    """
    if wiki_relpath.startswith("wiki/topics/"):
        return "topic", []

    parts = wiki_relpath.split("/")
    if parts[-1] == "index.md":
        # Folder wiki. Map to source folder.
        source_folder = wp.wiki_to_source_folder(wiki_relpath)
        if source_folder is None:
            return "leaf", []
        sf = str(source_folder)
        info = folder_info.get(sf)
        if info is None:
            # Source folder no longer exists; treat as leaf (lint will catch
            # this later as phantom-wiki).
            return "leaf", []
        if info["is_leaf"]:
            return "leaf", []
        # Parent: derive child wiki paths from the walk's child_dirs.
        children = sorted(
            str(wp.source_folder_to_wiki(f"{sf}/{c}"))
            for c in info["child_dirs"]
        )
        return "parent", children
    # Per-file wiki.
    return "perfile", []


if __name__ == "__main__":
    sys.exit(main())
