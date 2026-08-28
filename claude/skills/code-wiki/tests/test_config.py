"""Tests for bin/lib/config.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lib import config as cfg


def _write_config(project_root: Path, data: dict) -> None:
    wiki_dir = project_root / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "config.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_source_dir(project_root: Path, path: str) -> None:
    (project_root / path).mkdir(parents=True, exist_ok=True)


def test_load_returns_valid_config(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, "src")
    _write_config(tmp_path, {
        "version": 1,
        "source_roots": [{"path": "src"}],
        "wiki_language": "en",
        "language_hints": ["typescript"],
        "ignore_patterns": ["**/node_modules/**"],
        "per_file_pages": {"enabled": True, "min_loc": 800, "max_files_per_folder": 20},
    })
    out = cfg.load(tmp_path)
    assert out["version"] == 1
    assert out["source_roots"] == [{"path": "src"}]


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="not found"):
        cfg.load(tmp_path)


def test_load_invalid_yaml_raises(tmp_path: Path) -> None:
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "config.yaml").write_text("not: valid: yaml: at: all", encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="not valid YAML"):
        cfg.load(tmp_path)


def test_validate_rejects_wrong_version(tmp_path: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="version"):
        cfg.validate({"version": 99, "source_roots": []}, tmp_path)


def test_validate_rejects_dot_source_root(tmp_path: Path) -> None:
    with pytest.raises(cfg.ConfigError, match='"\\."'):
        cfg.validate({"version": 1, "source_roots": [{"path": "."}]}, tmp_path)


def test_validate_rejects_absolute_source_root(tmp_path: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="relative"):
        cfg.validate({"version": 1, "source_roots": [{"path": "/etc"}]}, tmp_path)


def test_validate_rejects_reserved_dir_wiki(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, "wiki/sub")
    with pytest.raises(cfg.ConfigError, match="reserved"):
        cfg.validate({"version": 1, "source_roots": [{"path": "wiki/sub"}]}, tmp_path)


def test_validate_rejects_reserved_dir_code_wiki(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, ".code-wiki/sub")
    with pytest.raises(cfg.ConfigError, match="reserved"):
        cfg.validate({"version": 1, "source_roots": [{"path": ".code-wiki/sub"}]}, tmp_path)


def test_validate_rejects_nonexistent_dir(tmp_path: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="not a directory"):
        cfg.validate({"version": 1, "source_roots": [{"path": "src"}]}, tmp_path)


def test_validate_rejects_nesting(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, "src/api")
    with pytest.raises(cfg.ConfigError, match="nests inside"):
        cfg.validate(
            {"version": 1, "source_roots": [{"path": "src"}, {"path": "src/api"}]},
            tmp_path,
        )


def test_validate_rejects_duplicate_paths(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, "src")
    with pytest.raises(cfg.ConfigError, match="nests inside"):
        cfg.validate(
            {"version": 1, "source_roots": [{"path": "src"}, {"path": "src"}]},
            tmp_path,
        )


def test_validate_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="\\.\\."):
        cfg.validate({"version": 1, "source_roots": [{"path": "../escape"}]}, tmp_path)


def test_validate_accepts_nested_distinct_paths(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, "apps/web/src")
    _make_source_dir(tmp_path, "apps/api/src")
    cfg.validate(
        {"version": 1, "source_roots": [{"path": "apps/web/src"}, {"path": "apps/api/src"}]},
        tmp_path,
    )  # should not raise


def test_validate_rejects_per_file_pages_wrong_type(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, "src")
    with pytest.raises(cfg.ConfigError, match="min_loc"):
        cfg.validate(
            {
                "version": 1,
                "source_roots": [{"path": "src"}],
                "per_file_pages": {"min_loc": "lots"},
            },
            tmp_path,
        )


def test_validate_rejects_language_hints_non_list(tmp_path: Path) -> None:
    _make_source_dir(tmp_path, "src")
    with pytest.raises(cfg.ConfigError, match="language_hints"):
        cfg.validate(
            {"version": 1, "source_roots": [{"path": "src"}], "language_hints": "typescript"},
            tmp_path,
        )
