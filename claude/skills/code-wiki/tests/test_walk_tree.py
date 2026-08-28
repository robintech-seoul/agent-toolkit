"""Tests for bin/walk-tree.py.

We exercise the script as a subprocess (since it's a CLI tool) and parse its
JSON output. Where finer-grained assertions are needed, we use `make_tree` from
the existing fs tests pattern.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


WALK_TREE = Path(__file__).resolve().parents[1] / "bin" / "walk-tree.py"


def _setup_project(tmp_path: Path, layout: dict, config: dict) -> Path:
    """Create a project tree at `tmp_path` and write the config.yaml."""
    _make(tmp_path, layout)
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    wiki.joinpath("config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    return tmp_path


def _make(root: Path, layout: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, value in layout.items():
        path = root / name.rstrip("/")
        if name.endswith("/"):
            _make(path, value)
        else:
            path.write_text(value, encoding="utf-8")


def _run_walk(project_root: Path) -> list[dict]:
    res = subprocess.run(
        [sys.executable, str(WALK_TREE), "--project-root", str(project_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(res.stdout)


def test_walk_minimal_single_source_root(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {"src/": {"main.py": "x", "auth/": {"login.py": "y"}}},
        {"version": 1, "source_roots": [{"path": "src"}]},
    )
    work = _run_walk(tmp_path)
    relpaths = [w["folder_relpath"] for w in work]
    # Bottom-up: 'src/auth' before 'src'
    assert relpaths.index("src/auth") < relpaths.index("src")


def test_walk_classifies_leaf_and_parent(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {"src/": {"main.py": "x", "auth/": {"login.py": "y"}}},
        {"version": 1, "source_roots": [{"path": "src"}]},
    )
    work = _run_walk(tmp_path)
    by_relpath = {w["folder_relpath"]: w for w in work}
    assert by_relpath["src/auth"]["kind"] == "leaf"
    assert by_relpath["src"]["kind"] == "parent"
    assert by_relpath["src"]["child_wikis"] == ["wiki/src/auth/index.md"]
    assert by_relpath["src/auth"]["child_wikis"] == []


def test_walk_emits_correct_paths(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {"src/": {"auth/": {"login.py": "y"}}},
        {"version": 1, "source_roots": [{"path": "src"}]},
    )
    work = _run_walk(tmp_path)
    by_relpath = {w["folder_relpath"]: w for w in work}
    auth = by_relpath["src/auth"]
    assert auth["source_root"] == "src"
    assert auth["source_files"] == ["src/auth/login.py"]
    assert auth["wiki_path"] == "wiki/src/auth/index.md"


def test_walk_multiple_source_roots(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {
            "apps/": {"web/src/": {"App.tsx": "x"}, "api/src/": {"server.ts": "y"}},
            "packages/lib/": {"index.ts": "z"},
        },
        {"version": 1, "source_roots": [
            {"path": "apps/web/src"},
            {"path": "apps/api/src"},
            {"path": "packages/lib"},
        ]},
    )
    work = _run_walk(tmp_path)
    source_roots_seen = {w["source_root"] for w in work}
    assert source_roots_seen == {"apps/web/src", "apps/api/src", "packages/lib"}
    # Each root yields at least its own folder.
    for sr in ("apps/web/src", "apps/api/src", "packages/lib"):
        match = [w for w in work if w["folder_relpath"] == sr]
        assert match, f"missing root entry for {sr}"


def test_walk_honors_ignore_patterns(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {"src/": {"main.py": "x", "node_modules/": {"junk.js": "y"}}},
        {
            "version": 1,
            "source_roots": [{"path": "src"}],
            "ignore_patterns": ["**/node_modules/**", "node_modules"],
        },
    )
    work = _run_walk(tmp_path)
    relpaths = [w["folder_relpath"] for w in work]
    assert "src/node_modules" not in relpaths
    src = next(w for w in work if w["folder_relpath"] == "src")
    # Without the ignored sub-dir, src has no surviving children → leaf.
    assert src["kind"] == "leaf"


def test_walk_aborts_when_config_missing(tmp_path: Path) -> None:
    res = subprocess.run(
        [sys.executable, str(WALK_TREE), "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "config.yaml" in res.stderr


def test_walk_scope_path_includes_subtree_and_ancestors(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {"src/": {
            "main.py": "x",
            "auth/": {"login.py": "y", "strategies/": {"oauth.py": "z"}},
            "users/": {"crud.py": "w"},
        }},
        {"version": 1, "source_roots": [{"path": "src"}]},
    )
    res = subprocess.run(
        [sys.executable, str(WALK_TREE),
         "--project-root", str(tmp_path),
         "--scope-path", "src/auth"],
        check=True, capture_output=True, text=True,
    )
    work = json.loads(res.stdout)
    relpaths = sorted(w["folder_relpath"] for w in work)
    # Expected: auth's subtree (src/auth, src/auth/strategies) + ancestor (src).
    # NOT included: src/users (sibling of auth).
    assert "src/auth" in relpaths
    assert "src/auth/strategies" in relpaths
    assert "src" in relpaths  # ancestor of scope
    assert "src/users" not in relpaths


def test_walk_scope_path_rejects_invalid(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {"src/": {"main.py": "x"}},
        {"version": 1, "source_roots": [{"path": "src"}]},
    )
    res = subprocess.run(
        [sys.executable, str(WALK_TREE),
         "--project-root", str(tmp_path),
         "--scope-path", "elsewhere/place"],
        capture_output=True, text=True,
    )
    assert res.returncode != 0
    assert "not inside any configured source root" in res.stderr


def test_walk_deep_monorepo_path(tmp_path: Path) -> None:
    _setup_project(
        tmp_path,
        {"apps/web/src/": {"components/": {"Button.tsx": "b"}}},
        {"version": 1, "source_roots": [{"path": "apps/web/src"}]},
    )
    work = _run_walk(tmp_path)
    by_relpath = {w["folder_relpath"]: w for w in work}
    assert "apps/web/src/components" in by_relpath
    assert by_relpath["apps/web/src/components"]["wiki_path"] == \
        "wiki/apps/web/src/components/index.md"
    assert by_relpath["apps/web/src"]["child_wikis"] == \
        ["wiki/apps/web/src/components/index.md"]
