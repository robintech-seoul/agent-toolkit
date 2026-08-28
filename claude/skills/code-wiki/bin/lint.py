#!/usr/bin/env python3
"""Run lint checks against a code-wiki repository.

Outputs a JSON array of `Finding` objects on stdout. The companion
`commands/lint.md` parses and pretty-prints the results.

Findings:
{
  "rule":     "broken-link-wiki" | "broken-link-source" | ... ,
  "severity": "error" | "warning" | "info",
  "path":    "wiki/src/auth/index.md",   // wiki page or source path the finding applies to
  "detail":  "human-readable message"
}

Implemented in this task (T21 — graph integrity):
- broken-link-wiki   (Error)   wiki→wiki link to non-existent page
- broken-link-source (Error)   wiki→source link to non-existent file
- phantom-wiki       (Error)   wiki page whose source folder no longer exists
- missing-wiki       (Warning) source folder under a source root, not ignored, has no wiki page
- orphan-wiki        (Warning) wiki page with no inbound links and no corresponding source folder

T22 will add: stale-wiki, length-too-short, length-too-long, topic-source-drift,
config-invalid, plus the `--fix` flag.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg  # noqa: E402
from lib import fs  # noqa: E402
from lib import hashing  # noqa: E402
from lib import links as links_lib  # noqa: E402
from lib import state as st  # noqa: E402
from lib import wiki_path as wp  # noqa: E402


LENGTH_TOO_SHORT = 20
LENGTH_TOO_LONG = 3000


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str   # "error" | "warning" | "info"
    path: str
    detail: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Run code-wiki lint rules.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--rules", default=None,
                        help=("Comma-separated rule names to run; default = all. "
                              "Useful for testing a single rule."))
    parser.add_argument("--fix", action="store_true",
                        help=("Apply conservative auto-fixes: remove phantom wikis, "
                              "refresh content hashes after regeneration."))
    args = parser.parse_args()

    project_root = args.project_root.resolve()

    findings: list[Finding] = []

    # config-invalid is a meta-rule; without a valid config most others can't
    # run. Check it first; if config fails to load, return immediately.
    try:
        config = cfg.load(project_root)
    except cfg.ConfigError as e:
        findings.append(Finding(
            rule="config-invalid",
            severity="error",
            path="wiki/config.yaml",
            detail=str(e),
        ))
        _emit(findings)
        return 0

    source_roots: list[str] = [e["path"] for e in config["source_roots"]]
    ignore_patterns: list[str] = config.get("ignore_patterns", []) or []
    state = st.load(project_root)

    enabled = set((args.rules or "").split(",")) if args.rules else None

    def run(name: str, fn) -> None:
        if enabled is not None and name not in enabled:
            return
        findings.extend(fn(project_root, source_roots, ignore_patterns, state))

    # Graph integrity rules (T21).
    run("broken-link-wiki", _rule_broken_link_wiki)
    run("broken-link-source", _rule_broken_link_source)
    run("phantom-wiki", _rule_phantom_wiki)
    run("missing-wiki", _rule_missing_wiki)
    run("orphan-wiki", _rule_orphan_wiki)

    # Content / state rules (T22).
    run("stale-wiki", _rule_stale_wiki)
    run("length-too-short", _rule_length_too_short)
    run("length-too-long", _rule_length_too_long)
    run("topic-source-drift", _rule_topic_source_drift)

    if args.fix:
        _apply_fixes(project_root, findings, source_roots, ignore_patterns, state)

    _emit(findings)
    return 0


def _apply_fixes(
    project_root: Path,
    findings: list[Finding],
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> None:
    """Apply conservative fixes:
    - phantom-wiki  → delete the wiki file (and prune empty parent dirs).
    - update state.json's content_hashes for any wiki that was deleted.
    Annotates the affected findings with `(auto-fixed)` in the detail.
    """
    deleted: list[str] = []
    for f in findings:
        if f.rule != "phantom-wiki":
            continue
        target = project_root / f.path
        if target.is_file():
            target.unlink()
            deleted.append(f.path)
            # Prune empty ancestors up to wiki/.
            parent = target.parent
            wiki_root = (project_root / "wiki").resolve()
            while parent != wiki_root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            # Annotate the finding so the user knows we acted.
            object.__setattr__(f, "detail", f.detail + " (auto-fixed: removed)")

    # Drop deleted entries from state.
    if deleted and state is not None:
        for p in deleted:
            entry = state["wiki_pages"].pop(p, None)
            if entry:
                for src in entry.get("source_files", []):
                    bucket = state["source_to_wiki"].get(src, [])
                    if p in bucket:
                        bucket.remove(p)
                    if not bucket:
                        state["source_to_wiki"].pop(src, None)
                        state["source_hashes"].pop(src, None)
        st.save(project_root, state)


def _emit(findings: list[Finding]) -> None:
    json.dump([asdict(f) for f in findings], sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_wiki_pages(project_root: Path) -> list[Path]:
    """All `.md` files under `wiki/`, EXCEPT `wiki/CLAUDE.md` (user-curated)."""
    wiki_root = project_root / "wiki"
    if not wiki_root.is_dir():
        return []
    return [
        p for p in sorted(wiki_root.rglob("*.md"))
        if p.relative_to(project_root).as_posix() != "wiki/CLAUDE.md"
    ]


def _all_source_folders(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
) -> set[str]:
    """Return all surviving (non-ignored) folder relpaths across source roots."""
    out: set[str] = set()
    for root in source_roots:
        root_abs = project_root / root
        if not root_abs.is_dir():
            continue
        for info in fs.walk_source_root(root_abs, ignore_patterns):
            rel = root if not info.relpath else f"{root}/{info.relpath}"
            out.add(rel)
    return out


# ---------------------------------------------------------------------------
# Rules (T21)
# ---------------------------------------------------------------------------


def _rule_broken_link_wiki(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Wiki→wiki link to a non-existent wiki page."""
    findings: list[Finding] = []
    for page in _all_wiki_pages(project_root):
        relpath = page.relative_to(project_root).as_posix()
        try:
            content = page.read_text(encoding="utf-8")
        except OSError:
            continue
        for link in links_lib.parse_outbound(
            content, page_relpath=relpath, source_roots=source_roots
        ):
            if link.kind != "wiki":
                continue
            target = project_root / link.target
            if not target.is_file():
                findings.append(Finding(
                    rule="broken-link-wiki",
                    severity="error",
                    path=relpath,
                    detail=f"link to '{link.raw_target}' (resolved: {link.target}) — file does not exist",
                ))
    return findings


def _rule_broken_link_source(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Wiki→source link to a non-existent source file."""
    findings: list[Finding] = []
    for page in _all_wiki_pages(project_root):
        relpath = page.relative_to(project_root).as_posix()
        try:
            content = page.read_text(encoding="utf-8")
        except OSError:
            continue
        for link in links_lib.parse_outbound(
            content, page_relpath=relpath, source_roots=source_roots
        ):
            if link.kind != "source":
                continue
            target = project_root / link.target
            if not target.is_file():
                findings.append(Finding(
                    rule="broken-link-source",
                    severity="error",
                    path=relpath,
                    detail=f"link to '{link.raw_target}' (resolved: {link.target}) — file does not exist",
                ))
    return findings


def _rule_phantom_wiki(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Wiki page whose corresponding source folder no longer exists.

    Topic pages and per-file wikis whose parent folder is gone are also flagged.
    """
    findings: list[Finding] = []
    surviving = _all_source_folders(project_root, source_roots, ignore_patterns)
    for page in _all_wiki_pages(project_root):
        relpath = page.relative_to(project_root).as_posix()
        # Topic pages don't have source folders; skip.
        if relpath.startswith("wiki/topics/"):
            continue
        source_folder = wp.wiki_to_source_folder(relpath)
        if source_folder is None:
            continue
        sf = str(source_folder)
        # Only enforce when the wiki claims to be under a configured source root.
        if not any(sf == r or sf.startswith(r + "/") for r in source_roots):
            continue
        if sf not in surviving:
            findings.append(Finding(
                rule="phantom-wiki",
                severity="error",
                path=relpath,
                detail=f"corresponding source folder '{sf}' no longer exists or is fully ignored",
            ))
    return findings


def _rule_missing_wiki(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Source folder (under a source root, not ignored) has no wiki page."""
    findings: list[Finding] = []
    for folder_relpath in sorted(_all_source_folders(project_root, source_roots, ignore_patterns)):
        wiki_p = str(wp.source_folder_to_wiki(folder_relpath))
        if not (project_root / wiki_p).is_file():
            findings.append(Finding(
                rule="missing-wiki",
                severity="warning",
                path=folder_relpath,
                detail=f"source folder has no wiki page at '{wiki_p}'",
            ))
    return findings


def _rule_orphan_wiki(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Wiki page with no inbound links and no corresponding source folder.

    Topic pages are exempt — they're often standalone by design and can have
    zero inbound links without being "orphan" in the lint sense.
    """
    pages = _all_wiki_pages(project_root)
    page_relpaths = {p.relative_to(project_root).as_posix() for p in pages}

    # Build inbound-link graph: for each wiki page, who links to it?
    inbound: dict[str, set[str]] = {p: set() for p in page_relpaths}
    for page in pages:
        relpath = page.relative_to(project_root).as_posix()
        try:
            content = page.read_text(encoding="utf-8")
        except OSError:
            continue
        for link in links_lib.parse_outbound(
            content, page_relpath=relpath, source_roots=source_roots
        ):
            if link.kind == "wiki" and link.target in inbound:
                inbound[link.target].add(relpath)

    surviving_folders = _all_source_folders(project_root, source_roots, ignore_patterns)
    findings: list[Finding] = []
    for relpath in page_relpaths:
        # Skip topics — they intentionally may have no inbound links.
        if relpath.startswith("wiki/topics/"):
            continue
        # Has inbound links?
        if inbound.get(relpath):
            continue
        # Has corresponding source folder? Then it's structurally rooted, not orphan.
        sf = wp.wiki_to_source_folder(relpath)
        if sf is not None and str(sf) in surviving_folders:
            continue
        findings.append(Finding(
            rule="orphan-wiki",
            severity="warning",
            path=relpath,
            detail="page has no inbound wiki links and no corresponding source folder",
        ))
    return findings


# ---------------------------------------------------------------------------
# Rules (T22 — content / state)
# ---------------------------------------------------------------------------


def _rule_stale_wiki(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Source file's current hash differs from `state.source_hashes`.

    Skipped (with a single info finding) when state.json is missing.
    """
    if state is None:
        return [Finding(
            rule="stale-wiki",
            severity="info",
            path=".code-wiki/state.json",
            detail="state.json missing; cannot detect stale wiki content. Run sync.",
        )]
    findings: list[Finding] = []
    for source, recorded in state.get("source_hashes", {}).items():
        path = project_root / source
        if not path.is_file():
            # Phantom-wiki rule covers folder removal; for a single missing file
            # we just skip (would emit a misleading finding).
            continue
        current = "sha256:" + hashing.sha256_file(path)
        if current != recorded:
            # Find which wiki(s) reference this source so the message is actionable.
            wikis = state.get("source_to_wiki", {}).get(source, [])
            for wiki_p in wikis:
                findings.append(Finding(
                    rule="stale-wiki",
                    severity="warning",
                    path=wiki_p,
                    detail=f"source '{source}' has changed since last ingest "
                           f"(hash differs); regenerate via /code-wiki:sync",
                ))
    return findings


def _rule_length_too_short(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Leaf wiki page < 20 lines (Info)."""
    return _length_check(project_root, source_roots, ignore_patterns, state,
                         predicate=lambda n: n < LENGTH_TOO_SHORT,
                         rule="length-too-short",
                         msg=lambda n: f"only {n} lines; consider whether the folder warrants a wiki page")


def _rule_length_too_long(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Leaf wiki page > 3000 lines (Info)."""
    return _length_check(project_root, source_roots, ignore_patterns, state,
                         predicate=lambda n: n > LENGTH_TOO_LONG,
                         rule="length-too-long",
                         msg=lambda n: f"{n} lines; consider per-file pages or splitting the folder")


def _length_check(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
    *,
    predicate,
    rule: str,
    msg,
) -> list[Finding]:
    # Identify which folder relpaths are leaves right now.
    leaf_paths: set[str] = set()
    for root in source_roots:
        root_abs = project_root / root
        if not root_abs.is_dir():
            continue
        for info in fs.walk_source_root(root_abs, ignore_patterns):
            rel = root if not info.relpath else f"{root}/{info.relpath}"
            if info.is_leaf:
                leaf_paths.add(rel)
    findings: list[Finding] = []
    for sf in leaf_paths:
        wiki_p = str(wp.source_folder_to_wiki(sf))
        f = project_root / wiki_p
        if not f.is_file():
            continue
        try:
            n = len(f.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
        if predicate(n):
            findings.append(Finding(
                rule=rule, severity="info", path=wiki_p, detail=msg(n),
            ))
    return findings


def _rule_topic_source_drift(
    project_root: Path,
    source_roots: list[str],
    ignore_patterns: list[str],
    state: dict | None,
) -> list[Finding]:
    """Topic page references a source whose content has changed since last
    ingest. Distinct from stale-wiki because it specifically calls out topics
    (which sync's v1 doesn't auto-regenerate)."""
    if state is None:
        return []
    findings: list[Finding] = []
    for wiki_p, entry in state.get("wiki_pages", {}).items():
        if entry.get("kind") != "topic":
            continue
        for src in entry.get("source_files", []):
            recorded = state.get("source_hashes", {}).get(src)
            if not recorded:
                continue
            path = project_root / src
            if not path.is_file():
                findings.append(Finding(
                    rule="topic-source-drift",
                    severity="warning",
                    path=wiki_p,
                    detail=f"references '{src}' which no longer exists",
                ))
                continue
            current = "sha256:" + hashing.sha256_file(path)
            if current != recorded:
                findings.append(Finding(
                    rule="topic-source-drift",
                    severity="warning",
                    path=wiki_p,
                    detail=f"references '{src}' whose content has changed; "
                           f"run /code-wiki:topic <name> to refresh",
                ))
    return findings


if __name__ == "__main__":
    sys.exit(main())
