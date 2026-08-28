"""Tests for bin/lint.py — graph-integrity rules (T21).

Each test sets up a small project with a deliberate inconsistency and verifies
that the corresponding rule fires (and unrelated rules do not).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


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


def _run_lint(project_root: Path, rules: str | None = None) -> list[dict]:
    args = [sys.executable, str(LINT), "--project-root", str(project_root)]
    if rules:
        args += ["--rules", rules]
    res = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(res.stdout)


def test_broken_link_wiki_detected(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {"src/": {"index.md": (
                "# src\n\n"
                "See [missing](./does-not-exist/index.md).\n"
            )}},
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="broken-link-wiki")
    assert len(findings) == 1
    assert findings[0]["rule"] == "broken-link-wiki"
    assert findings[0]["severity"] == "error"
    assert "does-not-exist" in findings[0]["detail"]


def test_broken_link_source_detected(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {"src/": {"index.md": (
                "# src\n\n"
                "See [`gone.py`](../../src/gone.py).\n"
            )}},
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="broken-link-source")
    assert len(findings) == 1
    assert findings[0]["rule"] == "broken-link-source"
    assert "gone.py" in findings[0]["detail"]


def test_phantom_wiki_detected(tmp_path: Path) -> None:
    """Wiki page exists but its source folder does not."""
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},  # only src/ exists
            "wiki/": {
                "src/": {
                    "index.md": "# src\n",
                    "deleted_module/": {"index.md": "# deleted_module\n"},
                }
            },
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="phantom-wiki")
    assert any(
        f["path"] == "wiki/src/deleted_module/index.md"
        and f["rule"] == "phantom-wiki"
        for f in findings
    )


def test_missing_wiki_detected(tmp_path: Path) -> None:
    """Source folder exists but no wiki page for it."""
    _setup(
        tmp_path,
        {
            "src/": {
                "main.py": "x",
                "auth/": {"login.py": "y"},  # no wiki page
            },
            "wiki/": {"src/": {"index.md": "# src\n"}},  # only the root wiki
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="missing-wiki")
    paths = [f["path"] for f in findings]
    assert "src/auth" in paths
    # src/ itself has a wiki, so should not be flagged.
    assert "src" not in paths


def test_orphan_wiki_detected(tmp_path: Path) -> None:
    """Wiki page with no inbound links and no source folder."""
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {
                "src/": {"index.md": "# src\n"},
                "stray/": {"index.md": "# stray\n\nNobody links to this.\n"},
            },
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="orphan-wiki")
    paths = [f["path"] for f in findings]
    assert "wiki/stray/index.md" in paths


def test_orphan_excludes_topic_pages(tmp_path: Path) -> None:
    """Topic pages with no inbound links should not be flagged as orphans."""
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {
                "src/": {"index.md": "# src\n"},
                "topics/": {"auth.md": "# auth\n\nStandalone topic.\n"},
            },
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="orphan-wiki")
    paths = [f["path"] for f in findings]
    assert "wiki/topics/auth.md" not in paths


def test_orphan_excludes_pages_with_source_folder(tmp_path: Path) -> None:
    """A wiki page that has no inbound links is still NOT an orphan if its
    source folder exists."""
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {
                "src/": {
                    "index.md": "# src\n",  # nobody links to it but its folder exists
                },
            },
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="orphan-wiki")
    assert findings == []


def test_phantom_excludes_topic_pages(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        {
            "src/": {"main.py": "x"},
            "wiki/": {
                "src/": {"index.md": "# src\n"},
                "topics/": {"auth.md": "# auth\n"},
            },
        },
        ["src"],
    )
    findings = _run_lint(tmp_path, rules="phantom-wiki")
    assert all(f["path"] != "wiki/topics/auth.md" for f in findings)


def test_clean_repo_has_no_findings(tmp_path: Path) -> None:
    # Pad page bodies past the length-too-short (20 lines) threshold.
    body = "\n".join(f"line {i}" for i in range(25))
    _setup(
        tmp_path,
        {
            "src/": {
                "main.py": "x",
                "auth/": {"login.py": "y"},
            },
            "wiki/": {
                "src/": {
                    "index.md": (
                        "# src\n\n"
                        "Has child [auth](./auth/index.md).\n"
                        "See [`main.py`](../../src/main.py).\n"
                        + body + "\n"
                    ),
                    "auth/": {
                        "index.md": (
                            "# auth\n\n"
                            "See [`login.py`](../../../src/auth/login.py).\n"
                            + body + "\n"
                        ),
                    },
                },
            },
        },
        ["src"],
    )
    findings = _run_lint(tmp_path)
    blocking = [f for f in findings if f["severity"] in ("error", "warning")]
    assert blocking == [], f"expected no errors/warnings, got: {blocking}"


def test_config_invalid_blocks_other_rules(tmp_path: Path) -> None:
    """If config is invalid, only config-invalid is reported (other rules
    don't run because they need source_roots)."""
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "config.yaml").write_text("not: valid: at: all", encoding="utf-8")
    findings = _run_lint(tmp_path)
    rules = [f["rule"] for f in findings]
    assert rules == ["config-invalid"]
    assert findings[0]["severity"] == "error"
