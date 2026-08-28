#!/usr/bin/env python3
"""Apply post-generation updates to `.code-wiki/state.json` and append to log.md.

Reads a JSON report on stdin describing which wiki pages were just (re)generated
and which were deleted, then atomically updates state.json:

- Recomputes `content_hash` for each updated wiki page (from the file on disk).
- Recomputes `source_hashes` for each referenced source file.
- Maintains the `source_to_wiki` reverse index (handles removed source refs).
- Removes deleted pages from all indices.
- Optionally sets `last_ingested_sha`.
- Appends a one-line entry to `.code-wiki/log.md`.

Stdin JSON shape:
{
  "operation": "build" | "sync" | "rebuild",         // for the log entry
  "ingested_sha": "abc123...",                        // optional; if present, sets last_ingested_sha
  "pages": [                                          // list of (re)generated pages
    {
      "wiki_path": "wiki/src/auth/index.md",
      "kind": "leaf" | "parent" | "topic" | "perfile",
      "source_files": ["src/auth/login.py", "src/auth/logout.py"],
      "child_wikis": ["wiki/src/auth/strategies/index.md"],   // optional, [] for non-parents
      "referenced_wikis": []                                  // optional; topics use this
    }
  ],
  "deletions": ["wiki/src/old/index.md"]              // optional
}
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg  # noqa: E402
from lib import hashing  # noqa: E402
from lib import links as links_lib  # noqa: E402
from lib import state as st  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Update state.json after wiki generation.")
    parser.add_argument("--project-root", required=True, type=Path,
                        help="Absolute path to the project root.")
    args = parser.parse_args()

    project_root = args.project_root.resolve()

    try:
        report = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: stdin is not valid JSON: {e}", file=sys.stderr)
        return 1

    operation = report.get("operation", "unknown")
    pages: list[dict] = report.get("pages", []) or []
    deletions: list[str] = report.get("deletions", []) or []
    ingested_sha = report.get("ingested_sha")

    state = st.load(project_root) or st.empty_state()

    # Read source_roots from config (used to classify outbound links).
    try:
        config = cfg.load(project_root)
        source_roots = [e["path"] for e in config["source_roots"]]
    except cfg.ConfigError:
        # Config invalid? Proceed with empty source_roots — outbound links will
        # only classify as wiki / external / other (not source).
        source_roots = []

    # Process deletions first so a wiki re-added in the same op doesn't get
    # accidentally removed.
    deletion_count = 0
    for wiki_path in deletions:
        if _remove_page(state, wiki_path):
            deletion_count += 1

    # Process additions/updates.
    updated_count = 0
    created_count = 0
    for page in pages:
        wiki_path = page["wiki_path"]
        existed = wiki_path in state["wiki_pages"]
        _apply_page(state, project_root, page, source_roots)
        if existed:
            updated_count += 1
        else:
            created_count += 1

    if ingested_sha is not None:
        state["last_ingested_sha"] = ingested_sha

    st.save(project_root, state)
    _append_log(project_root, operation, created_count, updated_count, deletion_count, ingested_sha)

    print(json.dumps({
        "operation": operation,
        "created": created_count,
        "updated": updated_count,
        "deleted": deletion_count,
        "last_ingested_sha": state["last_ingested_sha"],
    }))
    return 0


def _apply_page(
    state: dict,
    project_root: Path,
    page: dict,
    source_roots: list[str],
) -> None:
    """Add or update one page entry, maintaining source_to_wiki and source_hashes.

    `source_files` in the report represents the **structural** source files (the
    folder's loose files for a leaf, or any pre-declared sources for topics).
    Additional source references discovered by parsing the wiki's outbound
    markdown links are also recorded in `source_to_wiki` (per SPEC §7) so sync's
    cross-link propagation can find every wiki affected by a source change.
    """
    wiki_path: str = page["wiki_path"]
    kind: str = page["kind"]
    structural_sources: list[str] = list(page.get("source_files") or [])
    child_wikis: list[str] = list(page.get("child_wikis") or [])
    referenced_wikis: list[str] = list(page.get("referenced_wikis") or [])

    # Compute content hash from the wiki file on disk.
    abs_wiki = project_root / wiki_path
    if not abs_wiki.is_file():
        raise FileNotFoundError(f"expected generated wiki page at {abs_wiki}")
    content = abs_wiki.read_text(encoding="utf-8")
    content_hash = "sha256:" + hashing.sha256_text(content)

    # Parse outbound source links from the page; merge with structural list.
    outbound_sources: set[str] = set()
    if source_roots:
        for link in links_lib.parse_outbound(
            content, page_relpath=wiki_path, source_roots=source_roots
        ):
            if link.kind == "source":
                outbound_sources.add(link.target)

    all_sources = sorted(set(structural_sources) | outbound_sources)

    # If there was an old entry, drop reverse-index links for sources that no
    # longer appear in the new (structural + outbound) set.
    if wiki_path in state["wiki_pages"]:
        old_mapped = {
            src for src, wikis in state["source_to_wiki"].items()
            if wiki_path in wikis
        }
        new_set = set(all_sources)
        for stale in old_mapped - new_set:
            _drop_reverse_link(state, stale, wiki_path)

    # Write the new entry. Keep structural source_files separate from the
    # broader source_to_wiki coverage so callers can distinguish.
    state["wiki_pages"][wiki_path] = {
        "kind": kind,
        "source_files": structural_sources,
        "child_wikis": child_wikis,
        "referenced_wikis": referenced_wikis,
        "content_hash": content_hash,
    }

    # Reverse index + source hashes for ALL sources (structural + outbound).
    for src in all_sources:
        bucket = state["source_to_wiki"].setdefault(src, [])
        if wiki_path not in bucket:
            bucket.append(wiki_path)
        abs_src = project_root / src
        if abs_src.is_file():
            state["source_hashes"][src] = "sha256:" + hashing.sha256_file(abs_src)


def _remove_page(state: dict, wiki_path: str) -> bool:
    """Remove a page from all indices. Returns True if it existed."""
    entry = state["wiki_pages"].pop(wiki_path, None)
    if entry is None:
        return False
    for src in entry.get("source_files", []):
        _drop_reverse_link(state, src, wiki_path)
    return True


def _drop_reverse_link(state: dict, source: str, wiki_path: str) -> None:
    """Remove `wiki_path` from `source_to_wiki[source]`. If no wikis remain
    for that source, drop the source entry (and its hash) entirely."""
    bucket = state["source_to_wiki"].get(source)
    if not bucket:
        return
    if wiki_path in bucket:
        bucket.remove(wiki_path)
    if not bucket:
        state["source_to_wiki"].pop(source, None)
        state["source_hashes"].pop(source, None)


def _append_log(
    project_root: Path,
    operation: str,
    created: int,
    updated: int,
    deleted: int,
    ingested_sha: str | None,
) -> None:
    """Append a single timestamped block to log.md (creating it if missing)."""
    log = project_root / ".code-wiki" / "log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = (
        f"\n## {ts} {operation}\n"
        f"- created: {created}\n"
        f"- updated: {updated}\n"
        f"- deleted: {deleted}\n"
    )
    if ingested_sha:
        block += f"- last_ingested_sha: {ingested_sha}\n"
    with log.open("a", encoding="utf-8") as f:
        f.write(block)


if __name__ == "__main__":
    sys.exit(main())
