"""Tests for bin/state-bootstrap.py.

The most important test is the round-trip: build a wiki, snapshot state, delete
state.json, run bootstrap, and verify reconstruction matches enough of the
original to be useful for sync.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from lib import state as st


BOOTSTRAP = Path(__file__).resolve().parents[1] / "bin" / "state-bootstrap.py"


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


def _make(root: Path, layout: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, val in layout.items():
        path = root / name.rstrip("/")
        if name.endswith("/"):
            _make(path, val)
        else:
            path.write_text(val, encoding="utf-8")


def _setup_repo_with_wiki(tmp_path: Path) -> Path:
    """Build a minimal project with source files and a hand-authored wiki tree
    that mirrors the source structure."""
    _make(tmp_path, {
        "src/": {
            "main.py": "print('hi')",
            "auth/": {"login.py": "def login(): ..."},
        },
        "wiki/": {
            "config.yaml": yaml.safe_dump({
                "version": 1,
                "source_roots": [{"path": "src"}],
            }),
            "src/": {
                "index.md": (
                    "# src\n\n"
                    "Parent. Has [`main.py`](../../src/main.py) and child [auth](./auth/index.md).\n"
                ),
                "auth/": {
                    "index.md": (
                        "# auth\n\n"
                        "Leaf. See [`login.py`](../../../src/auth/login.py).\n"
                    ),
                },
            },
        },
    })
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "Test")
    _commit(tmp_path, "initial with wiki")
    return tmp_path


def _run(project_root: Path, *extra: str) -> dict:
    res = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--project-root", str(project_root), *extra],
        check=True, capture_output=True, text=True,
    )
    return json.loads(res.stdout)


def test_bootstrap_creates_state(tmp_path: Path) -> None:
    repo = _setup_repo_with_wiki(tmp_path)
    out = _run(repo)
    assert out["wiki_pages"] == 2
    assert out["last_ingested_sha"]

    state = st.load(repo)
    assert "wiki/src/index.md" in state["wiki_pages"]
    assert "wiki/src/auth/index.md" in state["wiki_pages"]


def test_bootstrap_classifies_leaf_and_parent(tmp_path: Path) -> None:
    repo = _setup_repo_with_wiki(tmp_path)
    _run(repo)
    state = st.load(repo)
    assert state["wiki_pages"]["wiki/src/auth/index.md"]["kind"] == "leaf"
    assert state["wiki_pages"]["wiki/src/index.md"]["kind"] == "parent"
    assert state["wiki_pages"]["wiki/src/index.md"]["child_wikis"] == \
        ["wiki/src/auth/index.md"]


def test_bootstrap_recovers_source_to_wiki(tmp_path: Path) -> None:
    repo = _setup_repo_with_wiki(tmp_path)
    _run(repo)
    state = st.load(repo)
    # main.py is referenced by the parent wiki only.
    assert state["source_to_wiki"]["src/main.py"] == ["wiki/src/index.md"]
    # login.py is referenced by the leaf wiki only.
    assert state["source_to_wiki"]["src/auth/login.py"] == ["wiki/src/auth/index.md"]


def test_bootstrap_sets_last_ingested_sha(tmp_path: Path) -> None:
    repo = _setup_repo_with_wiki(tmp_path)
    _run(repo)
    state = st.load(repo)
    assert state["last_ingested_sha"] == _git(repo, "rev-parse", "HEAD")


def test_bootstrap_aborts_when_state_exists(tmp_path: Path) -> None:
    repo = _setup_repo_with_wiki(tmp_path)
    _run(repo)
    # Re-run without --force.
    res = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--project-root", str(repo)],
        capture_output=True, text=True,
    )
    assert res.returncode == 1
    assert "already exists" in res.stderr


def test_bootstrap_force_overwrites(tmp_path: Path) -> None:
    repo = _setup_repo_with_wiki(tmp_path)
    _run(repo)
    # Modify state to detect overwrite.
    state = st.load(repo)
    state["last_ingested_sha"] = "fake_sha"
    st.save(repo, state)
    # Re-run with --force.
    _run(repo, "--force")
    state = st.load(repo)
    assert state["last_ingested_sha"] != "fake_sha"


def test_bootstrap_aborts_when_wiki_not_committed(tmp_path: Path) -> None:
    """If wiki/ exists on disk but no commit touches it, bootstrap can't infer
    last_ingested_sha and must error."""
    _make(tmp_path, {"src/": {"main.py": "x"}})
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@e.com")
    _git(tmp_path, "config", "user.name", "Test")
    _commit(tmp_path, "src only, no wiki")
    # Now write wiki/ to disk (uncommitted).
    _make(tmp_path / "wiki", {
        "config.yaml": yaml.safe_dump({"version": 1, "source_roots": [{"path": "src"}]}),
        "src/": {"index.md": "# src\n"},
    })
    res = subprocess.run(
        [sys.executable, str(BOOTSTRAP), "--project-root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert res.returncode == 1
    assert "not been committed" in res.stderr


def test_bootstrap_skips_claude_md_file(tmp_path: Path) -> None:
    """wiki/CLAUDE.md is user-curated and is not a wiki page; bootstrap must
    not register it in wiki_pages."""
    repo = _setup_repo_with_wiki(tmp_path)
    # Add a CLAUDE.md and re-commit so it's tracked.
    (repo / "wiki" / "CLAUDE.md").write_text("# Style\n\nUser content.\n")
    _commit(repo, "add CLAUDE.md")
    _run(repo)
    state = st.load(repo)
    assert "wiki/CLAUDE.md" not in state["wiki_pages"]


def test_bootstrap_handles_topic_pages(tmp_path: Path) -> None:
    repo = _setup_repo_with_wiki(tmp_path)
    # Add a topic page that references one source file.
    (repo / "wiki" / "topics").mkdir()
    (repo / "wiki" / "topics" / "auth.md").write_text(
        "# auth\n\nUses [`login.py`](../../src/auth/login.py).\n"
    )
    _commit(repo, "add topic")
    _run(repo)
    state = st.load(repo)
    assert "wiki/topics/auth.md" in state["wiki_pages"]
    entry = state["wiki_pages"]["wiki/topics/auth.md"]
    assert entry["kind"] == "topic"
    assert "src/auth/login.py" in entry["source_files"]
