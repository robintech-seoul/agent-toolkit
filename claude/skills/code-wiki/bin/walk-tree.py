#!/usr/bin/env python3
"""Emit a bottom-up ordered work list for `/code-wiki:build` and friends.

Reads `wiki/config.yaml` to find source roots and ignore patterns, then walks
each source root and emits one JSON object per folder that needs a wiki page.

Output is a JSON array on stdout, one object per folder, ordered so that every
leaf precedes its parents (post-order DFS within each source root). Source
roots are processed in the order they appear in config.yaml.

Each work item:
{
  "source_root":         "src",                            // config-declared source root path
  "folder_relpath":      "src/api",                        // project-root-relative
  "kind":                "leaf" | "parent",
  "source_files":        ["src/api/server.ts"],            // project-root-relative; loose files only
  "child_wikis":         ["wiki/src/api/auth/index.md"],   // direct-child wiki paths; [] for leaves
  "wiki_path":           "wiki/src/api/index.md"           // target output path for this folder's page
}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the lib package importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg  # noqa: E402
from lib import fs  # noqa: E402
from lib import wiki_path as wp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit bottom-up wiki work list as JSON.")
    parser.add_argument("--project-root", required=True, type=Path,
                        help="Absolute path to the project root.")
    parser.add_argument("--scope-path", default=None,
                        help=("Restrict output to folders at or under this path, "
                              "plus their ancestors up to the source root. The "
                              "path is project-root-relative."))
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    scope = args.scope_path.rstrip("/") if args.scope_path else None

    try:
        config = cfg.load(project_root)
    except cfg.ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    ignore_patterns: list[str] = config.get("ignore_patterns", []) or []
    work: list[dict] = []

    # If scoping, find the scope's containing source root upfront.
    scope_root: str | None = None
    if scope is not None:
        for entry in config["source_roots"]:
            sr = entry["path"]
            if scope == sr or scope.startswith(sr + "/"):
                scope_root = sr
                break
        if scope_root is None:
            print(f"Error: --scope-path {scope!r} is not inside any configured source root",
                  file=sys.stderr)
            return 1

    for entry in config["source_roots"]:
        source_root_relpath: str = entry["path"]
        # When scoping, only walk the source root that contains the scope.
        if scope_root is not None and source_root_relpath != scope_root:
            continue
        source_root_abs = project_root / source_root_relpath
        if not source_root_abs.is_dir():
            print(f"Error: source root {source_root_relpath!r} no longer exists",
                  file=sys.stderr)
            return 1

        for info in fs.walk_source_root(source_root_abs, ignore_patterns):
            # `info.relpath` is relative to the source root; convert to project-root-relative.
            if info.relpath:
                folder_relpath = f"{source_root_relpath}/{info.relpath}"
            else:
                folder_relpath = source_root_relpath

            source_files = sorted(
                f"{folder_relpath}/{p.name}" for p in info.loose_files
            )

            child_wikis = sorted(
                str(wp.source_folder_to_wiki(
                    f"{folder_relpath}/{child.name}"
                )) for child in info.child_dirs
            )

            wiki_path = str(wp.source_folder_to_wiki(folder_relpath))

            # If scoping, include only folders at-or-below the scope OR
            # ancestors of the scope (up to the source root).
            if scope is not None:
                at_or_below = (
                    folder_relpath == scope or folder_relpath.startswith(scope + "/")
                )
                is_ancestor = (
                    scope == folder_relpath
                    or scope.startswith(folder_relpath + "/")
                )
                if not (at_or_below or is_ancestor):
                    continue

            work.append({
                "source_root": source_root_relpath,
                "folder_relpath": folder_relpath,
                "kind": "leaf" if info.is_leaf else "parent",
                "source_files": source_files,
                "child_wikis": child_wikis,
                "wiki_path": wiki_path,
            })

    json.dump(work, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
