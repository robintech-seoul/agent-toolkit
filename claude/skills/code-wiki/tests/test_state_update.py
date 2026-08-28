"""Tests for bin/state-update.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lib import state as st


STATE_UPDATE = Path(__file__).resolve().parents[1] / "bin" / "state-update.py"


def _run(project_root: Path, report: dict) -> dict:
    res = subprocess.run(
        [sys.executable, str(STATE_UPDATE), "--project-root", str(project_root)],
        input=json.dumps(report),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(res.stdout)


def _setup(tmp_path: Path) -> Path:
    """Create a project tree with one source file and one wiki page on disk."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "wiki" / "src").mkdir(parents=True)
    (tmp_path / "wiki" / "src" / "index.md").write_text("# src\n\nLeaf.\n", encoding="utf-8")
    return tmp_path


def test_creates_state_when_missing(tmp_path: Path) -> None:
    _setup(tmp_path)
    report = {
        "operation": "build",
        "ingested_sha": "abc123",
        "pages": [{
            "wiki_path": "wiki/src/index.md",
            "kind": "leaf",
            "source_files": ["src/main.py"],
            "child_wikis": [],
        }],
    }
    result = _run(tmp_path, report)
    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["last_ingested_sha"] == "abc123"

    state = st.load(tmp_path)
    assert state["last_ingested_sha"] == "abc123"
    assert "wiki/src/index.md" in state["wiki_pages"]
    entry = state["wiki_pages"]["wiki/src/index.md"]
    assert entry["kind"] == "leaf"
    assert entry["source_files"] == ["src/main.py"]
    assert entry["content_hash"].startswith("sha256:")
    assert state["source_to_wiki"]["src/main.py"] == ["wiki/src/index.md"]
    assert state["source_hashes"]["src/main.py"].startswith("sha256:")


def test_updates_existing_page(tmp_path: Path) -> None:
    _setup(tmp_path)
    # Initial state with the page already known.
    initial = st.empty_state()
    initial["wiki_pages"]["wiki/src/index.md"] = {
        "kind": "leaf",
        "source_files": ["src/main.py"],
        "child_wikis": [],
        "referenced_wikis": [],
        "content_hash": "sha256:dead",
    }
    initial["source_to_wiki"]["src/main.py"] = ["wiki/src/index.md"]
    initial["source_hashes"]["src/main.py"] = "sha256:beef"
    st.save(tmp_path, initial)

    report = {
        "operation": "rebuild",
        "pages": [{
            "wiki_path": "wiki/src/index.md",
            "kind": "leaf",
            "source_files": ["src/main.py"],
            "child_wikis": [],
        }],
    }
    result = _run(tmp_path, report)
    assert result["updated"] == 1
    assert result["created"] == 0

    state = st.load(tmp_path)
    # Hash should be refreshed from the actual file (no longer 'dead').
    assert state["wiki_pages"]["wiki/src/index.md"]["content_hash"] != "sha256:dead"


def test_drops_stale_reverse_links_when_source_removed(tmp_path: Path) -> None:
    _setup(tmp_path)
    # Pre-populate state with TWO source files, but the new report only has one.
    initial = st.empty_state()
    initial["wiki_pages"]["wiki/src/index.md"] = {
        "kind": "leaf",
        "source_files": ["src/main.py", "src/old.py"],
        "child_wikis": [],
        "referenced_wikis": [],
        "content_hash": "sha256:dead",
    }
    initial["source_to_wiki"]["src/main.py"] = ["wiki/src/index.md"]
    initial["source_to_wiki"]["src/old.py"] = ["wiki/src/index.md"]
    initial["source_hashes"]["src/old.py"] = "sha256:old"
    st.save(tmp_path, initial)

    report = {
        "operation": "sync",
        "pages": [{
            "wiki_path": "wiki/src/index.md",
            "kind": "leaf",
            "source_files": ["src/main.py"],   # src/old.py removed
            "child_wikis": [],
        }],
    }
    _run(tmp_path, report)

    state = st.load(tmp_path)
    # src/old.py should be cleared from indices.
    assert "src/old.py" not in state["source_to_wiki"]
    assert "src/old.py" not in state["source_hashes"]
    # src/main.py still present.
    assert state["source_to_wiki"]["src/main.py"] == ["wiki/src/index.md"]


def test_handles_deletion(tmp_path: Path) -> None:
    _setup(tmp_path)
    initial = st.empty_state()
    initial["wiki_pages"]["wiki/src/index.md"] = {
        "kind": "leaf",
        "source_files": ["src/main.py"],
        "child_wikis": [],
        "referenced_wikis": [],
        "content_hash": "sha256:dead",
    }
    initial["source_to_wiki"]["src/main.py"] = ["wiki/src/index.md"]
    initial["source_hashes"]["src/main.py"] = "sha256:old"
    st.save(tmp_path, initial)

    report = {
        "operation": "sync",
        "pages": [],
        "deletions": ["wiki/src/index.md"],
    }
    result = _run(tmp_path, report)
    assert result["deleted"] == 1

    state = st.load(tmp_path)
    assert "wiki/src/index.md" not in state["wiki_pages"]
    assert "src/main.py" not in state["source_to_wiki"]
    assert "src/main.py" not in state["source_hashes"]


def test_appends_to_log(tmp_path: Path) -> None:
    _setup(tmp_path)
    report = {
        "operation": "build",
        "ingested_sha": "abc",
        "pages": [{"wiki_path": "wiki/src/index.md", "kind": "leaf",
                   "source_files": ["src/main.py"], "child_wikis": []}],
    }
    _run(tmp_path, report)
    log = (tmp_path / ".code-wiki" / "log.md").read_text(encoding="utf-8")
    assert "build" in log
    assert "created: 1" in log
    assert "last_ingested_sha: abc" in log


def test_aborts_when_wiki_file_missing(tmp_path: Path) -> None:
    _setup(tmp_path)
    report = {
        "operation": "build",
        "pages": [{"wiki_path": "wiki/missing/index.md", "kind": "leaf",
                   "source_files": [], "child_wikis": []}],
    }
    res = subprocess.run(
        [sys.executable, str(STATE_UPDATE), "--project-root", str(tmp_path)],
        input=json.dumps(report),
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0


def test_multiple_pages_update(tmp_path: Path) -> None:
    _setup(tmp_path)
    # Add a second wiki file and source.
    (tmp_path / "src" / "auth").mkdir()
    (tmp_path / "src" / "auth" / "login.py").write_text("def login(): ...\n")
    (tmp_path / "wiki" / "src" / "auth").mkdir()
    (tmp_path / "wiki" / "src" / "auth" / "index.md").write_text("# auth\n", encoding="utf-8")

    report = {
        "operation": "build",
        "pages": [
            {"wiki_path": "wiki/src/auth/index.md", "kind": "leaf",
             "source_files": ["src/auth/login.py"], "child_wikis": []},
            {"wiki_path": "wiki/src/index.md", "kind": "parent",
             "source_files": ["src/main.py"],
             "child_wikis": ["wiki/src/auth/index.md"]},
        ],
    }
    result = _run(tmp_path, report)
    assert result["created"] == 2

    state = st.load(tmp_path)
    parent = state["wiki_pages"]["wiki/src/index.md"]
    assert parent["kind"] == "parent"
    assert parent["child_wikis"] == ["wiki/src/auth/index.md"]
