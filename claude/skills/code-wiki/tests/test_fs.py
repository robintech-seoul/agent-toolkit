"""Tests for bin/lib/fs.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import fs


def make_tree(root: Path, layout: dict) -> None:
    """Create a directory tree from a nested dict.

    Keys ending in '/' are directories; others are files (the value is the
    file's content, or empty string).
    """
    root.mkdir(parents=True, exist_ok=True)
    for name, value in layout.items():
        path = root / name.rstrip("/")
        if name.endswith("/"):
            make_tree(path, value)
        else:
            path.write_text(value, encoding="utf-8")


def test_is_ignored_bare_name() -> None:
    assert fs.is_ignored("src/node_modules/foo.js", ["node_modules"])
    assert fs.is_ignored("node_modules/foo.js", ["node_modules"])
    assert not fs.is_ignored("src/lib/foo.js", ["node_modules"])


def test_is_ignored_segment_pattern() -> None:
    patterns = ["**/node_modules/**"]
    assert fs.is_ignored("src/node_modules/foo.js", patterns)
    assert fs.is_ignored("a/b/node_modules/c/d.js", patterns)
    # The directory itself is also flagged by segment-presence so the walker
    # skips it and doesn't recurse — this is intentionally more aggressive than
    # strict gitignore semantics.
    assert fs.is_ignored("src/node_modules", patterns)
    # But unrelated paths are not.
    assert not fs.is_ignored("src/lib/foo.js", patterns)


def test_is_ignored_extension_anywhere() -> None:
    patterns = ["**/*.lock"]
    assert fs.is_ignored("yarn.lock", patterns)
    assert fs.is_ignored("packages/foo/yarn.lock", patterns)
    assert not fs.is_ignored("packages/foo/yarn.json", patterns)


def test_is_ignored_prefix_pattern() -> None:
    patterns = ["build/**"]
    assert fs.is_ignored("build/output.js", patterns)
    assert fs.is_ignored("build/sub/file.js", patterns)
    assert not fs.is_ignored("src/build/file.js", patterns)


def test_walk_emits_single_leaf(tmp_path: Path) -> None:
    make_tree(tmp_path, {"src/": {"a.py": "x"}})
    src = tmp_path / "src"
    folders = list(fs.walk_source_root(src, []))
    assert len(folders) == 1
    info = folders[0]
    assert info.path == src
    assert info.relpath == ""
    assert info.is_leaf is True
    assert [p.name for p in info.loose_files] == ["a.py"]
    assert info.child_dirs == []


def test_walk_bottom_up_order(tmp_path: Path) -> None:
    make_tree(tmp_path, {
        "src/": {
            "main.py": "x",
            "auth/": {"login.py": "y", "logout.py": "z"},
            "users/": {"crud.py": "w"},
        }
    })
    folders = list(fs.walk_source_root(tmp_path / "src", []))
    relpaths = [f.relpath for f in folders]
    # Bottom-up: leaves before parent.
    assert relpaths.index("auth") < relpaths.index("")
    assert relpaths.index("users") < relpaths.index("")
    # Last yielded should be the root (relpath="").
    assert relpaths[-1] == ""


def test_walk_classifies_leaf_vs_parent(tmp_path: Path) -> None:
    make_tree(tmp_path, {
        "src/": {
            "main.py": "x",
            "auth/": {"login.py": "y"},
        }
    })
    by_relpath = {f.relpath: f for f in fs.walk_source_root(tmp_path / "src", [])}
    assert by_relpath["auth"].is_leaf is True
    assert by_relpath[""].is_leaf is False
    # The root (parent) must list `auth` as a surviving child.
    assert any(p.name == "auth" for p in by_relpath[""].child_dirs)
    # And keep `main.py` as a loose file.
    assert any(p.name == "main.py" for p in by_relpath[""].loose_files)


def test_walk_skips_ignored_subfolder(tmp_path: Path) -> None:
    make_tree(tmp_path, {
        "src/": {
            "main.py": "x",
            "node_modules/": {"junk.js": "y"},
        }
    })
    folders = list(fs.walk_source_root(tmp_path / "src", ["**/node_modules/**", "node_modules"]))
    relpaths = [f.relpath for f in folders]
    assert "node_modules" not in relpaths
    # The root should not list node_modules among surviving children.
    root = next(f for f in folders if f.relpath == "")
    assert all(p.name != "node_modules" for p in root.child_dirs)
    # And the root should still be a leaf because node_modules was its only sub-dir.
    assert root.is_leaf is True


def test_walk_skips_ignored_files(tmp_path: Path) -> None:
    make_tree(tmp_path, {"src/": {"main.py": "x", "yarn.lock": "y"}})
    folders = list(fs.walk_source_root(tmp_path / "src", ["**/*.lock"]))
    info = folders[0]
    names = [p.name for p in info.loose_files]
    assert "yarn.lock" not in names
    assert "main.py" in names


def test_walk_prunes_empty_folders_after_ignore(tmp_path: Path) -> None:
    make_tree(tmp_path, {
        "src/": {
            "main.py": "x",
            "junk/": {"a.lock": "y", "b.lock": "z"},
        }
    })
    folders = list(fs.walk_source_root(tmp_path / "src", ["**/*.lock"]))
    relpaths = [f.relpath for f in folders]
    # 'junk' folder ends up empty after ignoring all .lock files; should be pruned.
    assert "junk" not in relpaths


def test_walk_deep_nesting(tmp_path: Path) -> None:
    make_tree(tmp_path, {
        "src/": {"a/": {"b/": {"c/": {"file.py": "x"}}}}
    })
    folders = list(fs.walk_source_root(tmp_path / "src", []))
    relpaths = [f.relpath for f in folders]
    # All four levels yielded, deepest first.
    assert relpaths == ["a/b/c", "a/b", "a", ""]
    assert next(f for f in folders if f.relpath == "a/b/c").is_leaf is True


def test_walk_rejects_non_directory(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("hi")
    with pytest.raises(ValueError, match="not a directory"):
        list(fs.walk_source_root(f, []))


def test_walk_empty_directory_yields_nothing(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    folders = list(fs.walk_source_root(tmp_path / "src", []))
    assert folders == []


def test_walk_sorts_outputs(tmp_path: Path) -> None:
    make_tree(tmp_path, {
        "src/": {
            "a/": {"x.py": "x"},
            "b/": {"x.py": "x"},
            "c/": {"x.py": "x"},
        }
    })
    folders = list(fs.walk_source_root(tmp_path / "src", []))
    leaf_order = [f.relpath for f in folders if f.is_leaf]
    assert leaf_order == ["a", "b", "c"]
