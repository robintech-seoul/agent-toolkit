"""Tests for bin/lib/git.py.

Each test creates a fresh temp git repo so we can exercise diffs deterministically.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lib import git as gitlib


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Initialize a quiet git repo in tmp_path with author config."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, check=True
    )
    return tmp_path


def _commit(repo: Path, message: str = "c") -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=repo,
        check=True,
        env={"GIT_COMMITTER_DATE": "2026-01-01T00:00:00", "PATH": _path_env()},
    )
    return gitlib.current_sha(repo)


def _path_env() -> str:
    import os
    return os.environ.get("PATH", "/usr/bin:/bin")


def test_current_sha_returns_40_chars(repo: Path) -> None:
    (repo / "a.txt").write_text("hi")
    sha = _commit(repo)
    assert len(sha) == 40


def test_diff_modify(repo: Path) -> None:
    (repo / "a.txt").write_text("v1")
    s1 = _commit(repo, "init")
    (repo / "a.txt").write_text("v2")
    s2 = _commit(repo, "modify")
    changes = gitlib.diff(repo, s1, s2)
    assert len(changes) == 1
    assert changes[0].status == "M"
    assert changes[0].path == Path("a.txt")
    assert changes[0].old_path is None


def test_diff_add(repo: Path) -> None:
    (repo / "a.txt").write_text("v1")
    s1 = _commit(repo, "init")
    (repo / "b.txt").write_text("new")
    s2 = _commit(repo, "add")
    changes = gitlib.diff(repo, s1, s2)
    assert any(c.status == "A" and c.path == Path("b.txt") for c in changes)


def test_diff_delete(repo: Path) -> None:
    (repo / "a.txt").write_text("v1")
    s1 = _commit(repo, "init")
    (repo / "a.txt").unlink()
    s2 = _commit(repo, "delete")
    changes = gitlib.diff(repo, s1, s2)
    assert any(c.status == "D" and c.path == Path("a.txt") for c in changes)


def test_diff_rename(repo: Path) -> None:
    (repo / "old.txt").write_text("some content here\nlots of lines\nstable\nmore stuff\n")
    s1 = _commit(repo, "init")
    (repo / "new.txt").write_text("some content here\nlots of lines\nstable\nmore stuff\n")
    (repo / "old.txt").unlink()
    s2 = _commit(repo, "rename")
    changes = gitlib.diff(repo, s1, s2)
    rename = next((c for c in changes if c.status == "R"), None)
    assert rename is not None
    assert rename.path == Path("new.txt")
    assert rename.old_path == Path("old.txt")


def test_diff_empty_when_no_changes(repo: Path) -> None:
    (repo / "a.txt").write_text("v1")
    s1 = _commit(repo, "init")
    # No changes between s1 and itself.
    changes = gitlib.diff(repo, s1, s1)
    assert changes == []


def test_last_touched_returns_sha(repo: Path) -> None:
    (repo / "a.txt").write_text("v1")
    s1 = _commit(repo, "init")
    sha = gitlib.last_touched(repo, "a.txt")
    assert sha == s1


def test_last_touched_returns_latest(repo: Path) -> None:
    (repo / "a.txt").write_text("v1")
    _commit(repo, "init")
    (repo / "a.txt").write_text("v2")
    s2 = _commit(repo, "update")
    assert gitlib.last_touched(repo, "a.txt") == s2


def test_last_touched_returns_none_when_unknown(repo: Path) -> None:
    (repo / "a.txt").write_text("v1")
    _commit(repo, "init")
    assert gitlib.last_touched(repo, "nonexistent.txt") is None


def test_not_a_git_repo_raises(tmp_path: Path) -> None:
    with pytest.raises(gitlib.NotAGitRepo):
        gitlib.current_sha(tmp_path)
