"""Parse outbound markdown links from wiki pages.

Used by:
- `bin/state-bootstrap.py`: reconstructs `source_to_wiki` and `child_wikis`
  from committed wiki content when state.json is missing.
- `bin/lint.py`: validates that wiki→wiki and wiki→source links resolve.

Links are classified as:
- 'wiki'     → the resolved target falls inside `wiki/` (project-root-relative)
- 'source'   → the resolved target falls inside one of the configured source roots
- 'external' → http(s):// URL, mailto:, or other absolute scheme
- 'other'    → anything else (relative paths that don't resolve cleanly into
               wiki/ or a source root — usually a broken link to flag at lint time)
"""

from __future__ import annotations

import os.path
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

import mistune


LinkKind = Literal["wiki", "source", "external", "other"]


@dataclass(frozen=True)
class Link:
    """One outbound markdown link from a wiki page."""
    target: str          # the resolved project-root-relative POSIX path, or the raw URL for external
    raw_target: str      # the link's href as written in the source (before resolution)
    display: str         # the link's display text
    kind: LinkKind


def parse_outbound(
    md_content: str,
    *,
    page_relpath: str | PurePosixPath,
    source_roots: list[str] | None = None,
) -> list[Link]:
    """Extract all outbound markdown links from `md_content`.

    Args:
        md_content: the markdown source of a wiki page.
        page_relpath: the wiki page's path relative to the project root
                      (used to resolve relative link targets).
        source_roots: list of project-root-relative source root paths, used to
                      classify links as 'source'. If None, only 'wiki' and
                      'external' classifications are produced; otherwise
                      relatively-resolved targets that fall inside a source
                      root are 'source'.

    Returns links in document order. Duplicates are preserved (callers can
    de-duplicate if needed).
    """
    page_path = PurePosixPath(str(page_relpath))
    page_dir = page_path.parent

    # Mistune 3.x exposes a markdown parser; we walk the AST.
    md = mistune.create_markdown(renderer=None)
    ast = md(md_content)

    out: list[Link] = []
    for token in _walk_tokens(ast):
        if token.get("type") != "link":
            continue
        href = token.get("attrs", {}).get("url", "")
        if not href:
            continue
        display = _link_text(token)
        kind, resolved = _classify(href, page_dir, source_roots or [])
        out.append(Link(target=resolved, raw_target=href, display=display, kind=kind))
    return out


def _walk_tokens(tokens):
    """Recursively walk mistune's AST yielding every token."""
    if not tokens:
        return
    for tok in tokens:
        yield tok
        children = tok.get("children")
        if children:
            yield from _walk_tokens(children)


def _link_text(link_token: dict) -> str:
    """Extract plain-text display from a link token."""
    children = link_token.get("children") or []
    parts: list[str] = []
    for c in children:
        if c.get("type") == "text":
            parts.append(c.get("raw", ""))
        elif c.get("type") == "codespan":
            parts.append(c.get("raw", ""))
        else:
            # Recurse — links can contain emphasis etc.
            nested = _link_text(c)
            if nested:
                parts.append(nested)
    return "".join(parts)


def _classify(
    href: str,
    page_dir: PurePosixPath,
    source_roots: list[str],
) -> tuple[LinkKind, str]:
    """Classify a link href and return (kind, resolved_target).

    For external links the resolved_target is the original href.
    For relative links it is the project-root-relative POSIX path.
    """
    # External / scheme-prefixed links.
    if "://" in href or href.startswith(("mailto:", "tel:", "#")):
        return "external", href

    # Strip URL fragments and query strings — they don't affect classification.
    bare = href.split("#", 1)[0].split("?", 1)[0]
    if not bare:
        return "external", href  # pure anchor link

    # Resolve relative to the page's directory.
    if bare.startswith("/"):
        # Absolute-from-host links — treat as external; markdown renderers
        # interpret these as host-rooted, not file-system-rooted.
        return "external", href

    resolved = os.path.normpath(str(page_dir / bare))
    # Normalize to POSIX
    resolved = resolved.replace(os.sep, "/")

    # Classify
    if resolved == "wiki" or resolved.startswith("wiki/"):
        return "wiki", resolved
    for root in source_roots:
        root_norm = root.rstrip("/")
        if resolved == root_norm or resolved.startswith(root_norm + "/"):
            return "source", resolved
    return "other", resolved
