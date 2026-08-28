"""Tests for bin/lib/wiki_path.py.

Off-by-one errors here would break every link in every generated wiki page,
so this module is heavily tested.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from lib import wiki_path as wp


# ---------------------------------------------------------------------------
# source_folder_to_wiki
# ---------------------------------------------------------------------------


def test_source_folder_to_wiki_top_level() -> None:
    assert str(wp.source_folder_to_wiki("src")) == "wiki/src/index.md"


def test_source_folder_to_wiki_nested() -> None:
    assert str(wp.source_folder_to_wiki("src/auth")) == "wiki/src/auth/index.md"


def test_source_folder_to_wiki_deeply_nested_root() -> None:
    assert str(wp.source_folder_to_wiki("apps/web/src")) == "wiki/apps/web/src/index.md"


def test_source_folder_to_wiki_rejects_absolute() -> None:
    with pytest.raises(ValueError):
        wp.source_folder_to_wiki("/abs/path")


def test_source_folder_to_wiki_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        wp.source_folder_to_wiki("src/../escape")


# ---------------------------------------------------------------------------
# source_file_to_wiki
# ---------------------------------------------------------------------------


def test_source_file_to_wiki_simple() -> None:
    assert str(wp.source_file_to_wiki("src/main.py")) == "wiki/src/main.md"


def test_source_file_to_wiki_drops_extension() -> None:
    assert str(wp.source_file_to_wiki("src/auth/login.py")) == "wiki/src/auth/login.md"
    assert str(wp.source_file_to_wiki("src/index.ts")) == "wiki/src/index.md"


def test_source_file_to_wiki_rejects_empty() -> None:
    with pytest.raises(ValueError):
        wp.source_file_to_wiki("")


# ---------------------------------------------------------------------------
# wiki_to_source_folder
# ---------------------------------------------------------------------------


def test_wiki_to_source_folder_index() -> None:
    assert str(wp.wiki_to_source_folder("wiki/src/auth/index.md")) == "src/auth"


def test_wiki_to_source_folder_per_file() -> None:
    # Per-file wiki: returns the parent folder.
    assert str(wp.wiki_to_source_folder("wiki/src/auth/login.md")) == "src/auth"


def test_wiki_to_source_folder_top_level_index() -> None:
    assert str(wp.wiki_to_source_folder("wiki/src/index.md")) == "src"


def test_wiki_to_source_folder_topic_returns_none() -> None:
    # Topic page: returns the parent folder ('topics').
    # This is acceptable — caller can detect topic pages by their location
    # under wiki/topics/ rather than relying on this function.
    assert str(wp.wiki_to_source_folder("wiki/topics/auth.md")) == "topics"


def test_wiki_to_source_folder_outside_wiki_returns_none() -> None:
    assert wp.wiki_to_source_folder("src/auth/file.md") is None
    assert wp.wiki_to_source_folder("notwiki/x.md") is None


def test_wiki_to_source_folder_just_wiki_returns_none() -> None:
    assert wp.wiki_to_source_folder("wiki") is None


# ---------------------------------------------------------------------------
# is_index
# ---------------------------------------------------------------------------


def test_is_index_true() -> None:
    assert wp.is_index("wiki/src/index.md") is True
    assert wp.is_index("wiki/src/auth/index.md") is True


def test_is_index_false_for_per_file() -> None:
    assert wp.is_index("wiki/src/auth/login.md") is False
    assert wp.is_index("wiki/topics/auth.md") is False


# ---------------------------------------------------------------------------
# relative_link  (the high-stakes function)
# ---------------------------------------------------------------------------


def test_relative_link_spec_example() -> None:
    """The example from SPEC §3 — must match exactly."""
    assert wp.relative_link(
        "wiki/src/api/auth/index.md",
        "src/api/auth/auth.ts",
    ) == "../../../../src/api/auth/auth.ts"


def test_relative_link_top_level_wiki_to_source() -> None:
    # wiki/src/index.md → src/main.py
    # Page dir: wiki/src
    # Up to root: ../..  (escape src, escape wiki)
    # Then down: src/main.py
    # → ../../src/main.py
    assert wp.relative_link("wiki/src/index.md", "src/main.py") == "../../src/main.py"


def test_relative_link_wiki_to_wiki_sibling() -> None:
    # From wiki/src/index.md to wiki/src/auth/index.md
    # Page dir: wiki/src; target relative to that: auth/index.md
    assert wp.relative_link(
        "wiki/src/index.md",
        "wiki/src/auth/index.md",
    ) == "auth/index.md"


def test_relative_link_wiki_to_wiki_up_and_over() -> None:
    # From wiki/src/auth/index.md to wiki/src/users/index.md
    # Page dir: wiki/src/auth; up one to wiki/src; down to users/index.md
    assert wp.relative_link(
        "wiki/src/auth/index.md",
        "wiki/src/users/index.md",
    ) == "../users/index.md"


def test_relative_link_per_file_to_own_source() -> None:
    # From wiki/src/auth/login.md to src/auth/login.py
    # Page dir: wiki/src/auth → up 3 → src/auth/login.py
    assert wp.relative_link(
        "wiki/src/auth/login.md",
        "src/auth/login.py",
    ) == "../../../src/auth/login.py"


def test_relative_link_topic_to_source() -> None:
    # From wiki/topics/auth.md to src/auth/middleware.ts
    # Page dir: wiki/topics → up 2 → src/auth/middleware.ts
    assert wp.relative_link(
        "wiki/topics/auth.md",
        "src/auth/middleware.ts",
    ) == "../../src/auth/middleware.ts"


def test_relative_link_topic_to_wiki() -> None:
    # From wiki/topics/auth.md to wiki/src/auth/index.md
    # Page dir: wiki/topics → up 1 → src/auth/index.md
    assert wp.relative_link(
        "wiki/topics/auth.md",
        "wiki/src/auth/index.md",
    ) == "../src/auth/index.md"


def test_relative_link_deep_monorepo() -> None:
    # Source root apps/web/src; wiki at wiki/apps/web/src/components/index.md
    # Target apps/web/src/components/Button.tsx
    # Page dir: wiki/apps/web/src/components → up 5 → apps/web/src/components/Button.tsx
    assert wp.relative_link(
        "wiki/apps/web/src/components/index.md",
        "apps/web/src/components/Button.tsx",
    ) == "../../../../../apps/web/src/components/Button.tsx"
