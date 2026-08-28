"""Tests for bin/lib/links.py."""

from __future__ import annotations

from lib import links


def test_parse_outbound_classifies_wiki_link() -> None:
    # Sibling folder under wiki/src — use ./ to stay in current dir.
    md = "See [auth](./auth/index.md) for details."
    out = links.parse_outbound(md, page_relpath="wiki/src/index.md")
    assert len(out) == 1
    link = out[0]
    assert link.kind == "wiki"
    assert link.target == "wiki/src/auth/index.md"
    assert link.display == "auth"
    assert link.raw_target == "./auth/index.md"


def test_parse_outbound_classifies_source_link() -> None:
    md = "Source: [main.py](../../src/main.py)."
    out = links.parse_outbound(
        md,
        page_relpath="wiki/src/index.md",
        source_roots=["src"],
    )
    assert len(out) == 1
    assert out[0].kind == "source"
    assert out[0].target == "src/main.py"


def test_parse_outbound_classifies_external_http() -> None:
    md = "[Karpathy](https://example.com)"
    out = links.parse_outbound(md, page_relpath="wiki/index.md")
    assert len(out) == 1
    assert out[0].kind == "external"
    assert out[0].target == "https://example.com"


def test_parse_outbound_classifies_anchor_as_external() -> None:
    md = "[top](#top)"
    out = links.parse_outbound(md, page_relpath="wiki/index.md")
    assert len(out) == 1
    assert out[0].kind == "external"


def test_parse_outbound_classifies_unresolved_as_other() -> None:
    # Resolve to a location outside wiki/ and outside source_roots → "other".
    md = "[broken](../../somewhere/file.md)"
    out = links.parse_outbound(
        md, page_relpath="wiki/src/index.md", source_roots=["src"]
    )
    assert len(out) == 1
    assert out[0].kind == "other"
    assert out[0].target == "somewhere/file.md"


def test_parse_outbound_multiple_links() -> None:
    # From wiki/src/index.md:
    #   ./auth/index.md → wiki/src/auth/index.md (wiki)
    #   ../../src/main.py → src/main.py (source)
    #   https://... (external)
    md = """
- [auth](./auth/index.md) — auth folder
- [main.py](../../src/main.py) — main file
- [external](https://example.com)
"""
    out = links.parse_outbound(
        md, page_relpath="wiki/src/index.md", source_roots=["src"]
    )
    assert len(out) == 3
    kinds = [link.kind for link in out]
    assert "wiki" in kinds
    assert "source" in kinds
    assert "external" in kinds


def test_parse_outbound_link_with_codespan_display() -> None:
    md = "Open [`login.py`](../auth/login.py)."
    out = links.parse_outbound(
        md, page_relpath="wiki/src/index.md", source_roots=["src"]
    )
    assert len(out) == 1
    assert out[0].display == "login.py"


def test_parse_outbound_strips_query_and_fragment_for_classification() -> None:
    md = "[wiki](../auth/index.md#section)"
    out = links.parse_outbound(md, page_relpath="wiki/src/index.md")
    assert out[0].kind == "wiki"


def test_parse_outbound_absolute_url_is_external() -> None:
    md = "[abs](/some/host/relative/path)"
    out = links.parse_outbound(md, page_relpath="wiki/index.md")
    assert out[0].kind == "external"


def test_parse_outbound_empty_input() -> None:
    assert links.parse_outbound("", page_relpath="wiki/index.md") == []


def test_parse_outbound_no_links() -> None:
    md = "Just some prose, no links here."
    assert links.parse_outbound(md, page_relpath="wiki/index.md") == []


def test_parse_outbound_handles_per_file_page_link() -> None:
    md = "Implemented in [`login.py`](./login.md)."
    out = links.parse_outbound(
        md, page_relpath="wiki/src/auth/index.md", source_roots=["src"]
    )
    assert out[0].kind == "wiki"
    assert out[0].target == "wiki/src/auth/login.md"
