"""Tests for bin/lint.py — content/state rules + --fix (T22)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from lib import state as st
from lib import hashing


LINT = Path(__file__).resolve().parents[1] / "bin" / "lint.py"


def _make(root: Path, layout: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, val in layout.items():
        path = root / name.rstrip("/")
        if name.endswith("/"):
            _make(path, val)
        else:
            path.write_text(val, encoding="utf-8")


def _setup(tmp_path: Path, layout: dict, source_roots: list[str]) -> Path:
    _make(tmp_path, layout)
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "config.yaml").write_text(
        yaml.safe_dump({
            "version": 1,
            "source_roots": [{"path": p} for p in source_roots],
        }, sort_keys=False),
        encoding="utf-8",
    )
    return tmp_path


def _run_lint(project_root: Path, rules: str | None = None, fix: bool = False) -> list[dict]:
    args = [sys.executable, str(LINT), "--project-root", str(project_root)]
    if rules:
        args += ["--rules", rules]
    if fix:
        args += ["--fix"]
    res = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(res.stdout)


# ---------------------------------------------------------------------------
# stale-wiki
# ---------------------------------------------------------------------------


def test_stale_wiki_detected_when_source_changes(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"main.py": "v1"}, "wiki/": {"src/": {"index.md": "# src\n"}}},
        ["src"],
    )
    # Seed state with the v1 hash, then change the source.
    state = st.empty_state()
    state["last_ingested_sha"] = "abc"
    state["wiki_pages"]["wiki/src/index.md"] = {
        "kind": "leaf", "source_files": ["src/main.py"], "child_wikis": [],
        "referenced_wikis": [], "content_hash": "sha256:dead",
    }
    state["source_to_wiki"]["src/main.py"] = ["wiki/src/index.md"]
    state["source_hashes"]["src/main.py"] = "sha256:" + hashing.sha256_text("v1")
    st.save(repo, state)

    # Modify source.
    (repo / "src" / "main.py").write_text("v2_changed")

    findings = _run_lint(repo, rules="stale-wiki")
    assert len(findings) == 1
    assert findings[0]["rule"] == "stale-wiki"
    assert findings[0]["path"] == "wiki/src/index.md"
    assert "src/main.py" in findings[0]["detail"]


def test_stale_wiki_skipped_when_state_missing(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {"src/": {"main.py": "v1"}, "wiki/": {"src/": {"index.md": "# src\n"}}},
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="stale-wiki")
    # Single info finding pointing at the missing state.
    assert len(findings) == 1
    assert findings[0]["rule"] == "stale-wiki"
    assert findings[0]["severity"] == "info"
    assert "state.json missing" in findings[0]["detail"]


def test_stale_wiki_no_finding_when_unchanged(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {"src/": {"main.py": "v1"}, "wiki/": {"src/": {"index.md": "# src\n"}}},
        ["src"],
    )
    state = st.empty_state()
    state["last_ingested_sha"] = "abc"
    state["wiki_pages"]["wiki/src/index.md"] = {
        "kind": "leaf", "source_files": ["src/main.py"], "child_wikis": [],
        "referenced_wikis": [], "content_hash": "sha256:dead",
    }
    state["source_to_wiki"]["src/main.py"] = ["wiki/src/index.md"]
    state["source_hashes"]["src/main.py"] = "sha256:" + hashing.sha256_text("v1")
    st.save(repo, state)

    findings = _run_lint(repo, rules="stale-wiki")
    assert findings == []


# ---------------------------------------------------------------------------
# length-too-short / length-too-long
# ---------------------------------------------------------------------------


def test_length_too_short(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {"src/": {"index.md": "# src\n"}},  # 1 line
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="length-too-short")
    assert len(findings) == 1
    assert findings[0]["rule"] == "length-too-short"
    assert findings[0]["severity"] == "info"


def test_length_too_long(tmp_path: Path) -> None:
    long_content = "# src\n\n" + "\n".join("filler" for _ in range(3050))
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {"src/": {"index.md": long_content}},
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="length-too-long")
    assert len(findings) == 1
    assert findings[0]["rule"] == "length-too-long"


def test_length_does_not_apply_to_topics(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {
                "src/": {"index.md": "# src\n\nReasonable content for the rule.\n" + "\n".join("x" for _ in range(40))},
                "topics/": {"trivial.md": "# trivial\n"},  # 1 line topic
            },
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="length-too-short")
    paths = [f["path"] for f in findings]
    assert "wiki/topics/trivial.md" not in paths


# ---------------------------------------------------------------------------
# topic-source-drift
# ---------------------------------------------------------------------------


def test_topic_source_drift_detected(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {
            "src/": {"auth.py": "v1"},
            "wiki/": {
                "src/": {"index.md": "# src\n"},
                "topics/": {"auth.md": "# auth\n\nSee `auth.py`.\n"},
            },
        },
        ["src"],
    )
    state = st.empty_state()
    state["last_ingested_sha"] = "abc"
    state["wiki_pages"]["wiki/topics/auth.md"] = {
        "kind": "topic", "source_files": ["src/auth.py"], "child_wikis": [],
        "referenced_wikis": [], "content_hash": "sha256:dead",
    }
    state["source_to_wiki"]["src/auth.py"] = ["wiki/topics/auth.md"]
    state["source_hashes"]["src/auth.py"] = "sha256:" + hashing.sha256_text("v1")
    st.save(repo, state)

    (repo / "src" / "auth.py").write_text("v2_drifted")
    findings = _run_lint(repo, rules="topic-source-drift")
    assert any(f["path"] == "wiki/topics/auth.md" and f["rule"] == "topic-source-drift"
               for f in findings)


def test_topic_source_drift_no_state_no_findings(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {"src/": {"main.py": "x"}, "wiki/": {"src/": {"index.md": "# src\n"},
                                              "topics/": {"auth.md": "# auth\n"}}},
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="topic-source-drift")
    assert findings == []


# ---------------------------------------------------------------------------
# --fix
# ---------------------------------------------------------------------------


def test_fix_removes_phantom_wiki(tmp_path: Path) -> None:
    repo = _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},  # only src/ exists; src/gone/ removed
            "wiki/": {
                "src/": {
                    "index.md": "# src\n",
                    "gone/": {"index.md": "# gone\n"},  # phantom
                },
            },
        },
        ["src"],
    )
    # Pre-populate state so --fix can clean up entries too.
    state = st.empty_state()
    state["wiki_pages"]["wiki/src/gone/index.md"] = {
        "kind": "leaf", "source_files": ["src/gone/old.py"], "child_wikis": [],
        "referenced_wikis": [], "content_hash": "sha256:abc",
    }
    state["source_to_wiki"]["src/gone/old.py"] = ["wiki/src/gone/index.md"]
    st.save(repo, state)

    findings = _run_lint(repo, fix=True)
    # The phantom-wiki finding was emitted AND the file should be gone now.
    assert not (repo / "wiki" / "src" / "gone" / "index.md").exists()
    # State should also be cleaned.
    state = st.load(repo)
    assert "wiki/src/gone/index.md" not in state["wiki_pages"]
    assert "src/gone/old.py" not in state["source_to_wiki"]
    # The finding's detail should mention the auto-fix.
    phantom = [f for f in findings if f["rule"] == "phantom-wiki"]
    assert phantom and "auto-fixed" in phantom[0]["detail"]


def test_fix_does_not_touch_other_findings(tmp_path: Path) -> None:
    """`--fix` should not act on broken-link or stale-wiki findings; those
    require user action."""
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {"src/": {"index.md": "# src\n\n[broken](./missing/index.md)\n"}},
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, fix=True)
    # Page should still exist (only phantom-wiki gets auto-fixed).
    assert (tmp_path / "wiki" / "src" / "index.md").is_file()
    # broken-link-wiki finding should still appear.
    assert any(f["rule"] == "broken-link-wiki" for f in findings)
