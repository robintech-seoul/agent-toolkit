"""Tests for bin/scan-changes.py.

Each test sets up a small project tree, initializes git, runs build-equivalent
state population, makes a change, then exercises scan-changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from lib import state as st


SCAN = Path(__file__).resolve().parents[1] / "bin" / "scan-changes.py"


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
        env={**os.environ, "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"},
    )
    return res.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _setup(tmp_path: Path, layout: dict, source_roots: list[str]) -> Path:
    """Create a project tree, init git, write config.yaml, write initial state.json
    pointing at the first commit."""
    _make(tmp_path, layout)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")

    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "config.yaml").write_text(
        yaml.safe_dump({
            "version": 1,
            "source_roots": [{"path": p} for p in source_roots],
        }, sort_keys=False),
        encoding="utf-8",
    )
    sha = _commit(tmp_path, "initial")

    # Seed minimal state.json.
    state = st.empty_state()
    state["last_ingested_sha"] = sha
    st.save(tmp_path, state)
    return tmp_path


def _make(root: Path, layout: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, val in layout.items():
        path = root / name.rstrip("/")
        if name.endswith("/"):
            _make(path, val)
        else:
            path.write_text(val, encoding="utf-8")


def _run(project_root: Path) -> dict:
    res = subprocess.run(
        [sys.executable, str(SCAN), "--project-root", str(project_root)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(res.stdout)


def _seed_state_with_pages(project_root: Path, pages: list[dict]) -> None:
    """Populate state.json with full wiki_pages entries (for deletion / topic tests)."""
    state = st.load(project_root) or st.empty_state()
    for p in pages:
        state["wiki_pages"][p["wiki_path"]] = {
            "kind": p["kind"],
            "source_files": p.get("source_files", []),
            "child_wikis": p.get("child_wikis", []),
            "referenced_wikis": p.get("referenced_wikis", []),
            "content_hash": "sha256:placeholder",
        }
        for sf in p.get("source_files", []):
            state["source_to_wiki"].setdefault(sf, []).append(p["wiki_path"])
            state["source_hashes"][sf] = "sha256:src"
    st.save(project_root, state)


def test_modify_marks_leaf_and_parent_dirty(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"main.py": "v1", "auth/": {"login.py": "v1"}}},
        ["src"],
    )
    (repo / "src" / "auth" / "login.py").write_text("v2")
    _commit(repo, "modify login")

    out = _run(repo)
    relpaths = sorted(p["folder_relpath"] for p in out["pages"])
    assert "src/auth" in relpaths
    assert "src" in relpaths      # ancestor propagated
    assert out["deletions"] == []


def test_add_creates_new_leaf(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"main.py": "v1"}},
        ["src"],
    )
    (repo / "src" / "auth").mkdir()
    (repo / "src" / "auth" / "login.py").write_text("new")
    _commit(repo, "add auth folder")

    out = _run(repo)
    relpaths = sorted(p["folder_relpath"] for p in out["pages"])
    # New leaf and updated root parent.
    assert "src/auth" in relpaths
    assert "src" in relpaths


def test_delete_creates_deletion(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"main.py": "v1", "auth/": {"login.py": "v1"}}},
        ["src"],
    )
    # Pre-populate state to know about the auth wiki page.
    _seed_state_with_pages(repo, [
        {"wiki_path": "wiki/src/auth/index.md", "kind": "leaf",
         "source_files": ["src/auth/login.py"]},
        {"wiki_path": "wiki/src/index.md", "kind": "parent",
         "source_files": ["src/main.py"],
         "child_wikis": ["wiki/src/auth/index.md"]},
    ])
    # Delete the entire auth folder.
    (repo / "src" / "auth" / "login.py").unlink()
    (repo / "src" / "auth").rmdir()
    _commit(repo, "delete auth")

    out = _run(repo)
    assert "wiki/src/auth/index.md" in out["deletions"]
    # Parent should still appear in pages (re-synthesize without that child).
    assert any(p["folder_relpath"] == "src" for p in out["pages"])


def test_rename_treated_as_delete_plus_add(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"old.py": "x" * 200}},  # Long enough that git detects the rename
        ["src"],
    )
    # Rename via filesystem move.
    (repo / "src" / "old.py").rename(repo / "src" / "new.py")
    _commit(repo, "rename")

    out = _run(repo)
    # Both src (parent of file) marked dirty; nothing to do for non-folder rename.
    relpaths = sorted(p["folder_relpath"] for p in out["pages"])
    assert "src" in relpaths


def test_topic_dirty_when_source_changes(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"auth.py": "v1"}},
        ["src"],
    )
    _seed_state_with_pages(repo, [
        {"wiki_path": "wiki/topics/auth.md", "kind": "topic",
         "source_files": ["src/auth.py"]},
    ])
    (repo / "src" / "auth.py").write_text("v2")
    _commit(repo, "modify")

    out = _run(repo)
    assert "wiki/topics/auth.md" in out["dirty_topics"]


def test_topic_not_dirty_when_unrelated_change(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"auth.py": "v1", "main.py": "v1"}},
        ["src"],
    )
    _seed_state_with_pages(repo, [
        {"wiki_path": "wiki/topics/auth.md", "kind": "topic",
         "source_files": ["src/auth.py"]},
    ])
    (repo / "src" / "main.py").write_text("v2")
    _commit(repo, "modify main")

    out = _run(repo)
    assert "wiki/topics/auth.md" not in out["dirty_topics"]


def test_no_changes_yields_empty(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"main.py": "v1"}},
        ["src"],
    )
    out = _run(repo)
    assert out["pages"] == []
    assert out["deletions"] == []
    assert out["dirty_topics"] == []


def test_ignored_change_filtered_out(tmp_path: Path) -> None:
    """Changes that fall under ignore_patterns must not produce dirty work."""
    _make(tmp_path, {"src/": {"main.py": "v1"}})
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "config.yaml").write_text(
        yaml.safe_dump({
            "version": 1,
            "source_roots": [{"path": "src"}],
            "ignore_patterns": ["**/*.lock"],
        }, sort_keys=False),
        encoding="utf-8",
    )
    sha = _commit(tmp_path, "initial")
    state = st.empty_state()
    state["last_ingested_sha"] = sha
    st.save(tmp_path, state)

    # Now add an ignored file.
    (tmp_path / "src" / "yarn.lock").write_text("ignored content")
    _commit(tmp_path, "add ignored")

    out = _run(tmp_path)
    assert out["pages"] == []


def test_aborts_when_state_missing(tmp_path: Path) -> None:
    _make(tmp_path, {"src/": {"main.py": "v1"}, "wiki/": {}})
    (tmp_path / "wiki" / "config.yaml").write_text(
        yaml.safe_dump({"version": 1, "source_roots": [{"path": "src"}]}),
        encoding="utf-8",
    )
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "Test")
    _commit(tmp_path, "initial")

    res = subprocess.run(
        [sys.executable, str(SCAN), "--project-root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert res.returncode == 2
    assert "state.json" in res.stderr
