"""Tests for bin/lib/state.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import state as st


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert st.load(tmp_path) is None


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    payload = st.empty_state()
    payload["last_ingested_sha"] = "abc123"
    payload["wiki_pages"]["wiki/src/index.md"] = {
        "kind": "leaf",
        "source_files": ["src/main.py"],
        "child_wikis": [],
        "content_hash": "sha256:deadbeef",
    }
    payload["source_to_wiki"]["src/main.py"] = ["wiki/src/index.md"]
    payload["source_hashes"]["src/main.py"] = "sha256:cafe"

    st.save(tmp_path, payload)
    loaded = st.load(tmp_path)
    assert loaded == payload


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    # .code-wiki/ does not exist yet; save should create it.
    state = st.empty_state()
    st.save(tmp_path, state)
    assert (tmp_path / ".code-wiki" / "state.json").exists()


def test_save_writes_atomically(tmp_path: Path) -> None:
    """The atomic write should leave no .tmp files behind on success."""
    state = st.empty_state()
    st.save(tmp_path, state)
    state_dir = tmp_path / ".code-wiki"
    leftover = list(state_dir.glob(".state.*.tmp"))
    assert leftover == []


def test_load_invalid_json_raises_corrupted(tmp_path: Path) -> None:
    path = tmp_path / ".code-wiki" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(st.StateCorrupted, match="not valid JSON"):
        st.load(tmp_path)


def test_load_wrong_version_raises_corrupted(tmp_path: Path) -> None:
    path = tmp_path / ".code-wiki" / "state.json"
    path.parent.mkdir(parents=True)
    bad = {"version": 99, "wiki_pages": {}, "source_to_wiki": {}, "source_hashes": {}}
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(st.StateCorrupted, match="version"):
        st.load(tmp_path)


def test_load_missing_required_field_raises(tmp_path: Path) -> None:
    path = tmp_path / ".code-wiki" / "state.json"
    path.parent.mkdir(parents=True)
    bad = {"version": 1, "wiki_pages": {}}  # missing source_to_wiki, source_hashes
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(st.StateCorrupted, match="missing required field"):
        st.load(tmp_path)


def test_save_rejects_bad_state(tmp_path: Path) -> None:
    bad = {"version": 1}  # missing required fields
    with pytest.raises(st.StateCorrupted):
        st.save(tmp_path, bad)


def test_empty_state_has_correct_shape() -> None:
    s = st.empty_state()
    assert s["version"] == st.SCHEMA_VERSION
    assert s["last_ingested_sha"] is None
    assert s["wiki_pages"] == {}
    assert s["source_to_wiki"] == {}
    assert s["source_hashes"] == {}


def test_save_overwrites_existing(tmp_path: Path) -> None:
    s1 = st.empty_state()
    s1["last_ingested_sha"] = "first"
    st.save(tmp_path, s1)
    s2 = st.empty_state()
    s2["last_ingested_sha"] = "second"
    st.save(tmp_path, s2)
    loaded = st.load(tmp_path)
    assert loaded["last_ingested_sha"] == "second"
