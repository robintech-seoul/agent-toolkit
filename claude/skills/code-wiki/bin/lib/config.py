"""Read and validate wiki/config.yaml.

Schema reference: SPEC.md §5. The user owns this file; the plugin never auto-edits it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path("wiki/config.yaml")
RESERVED_DIRS = {"wiki", ".code-wiki"}
SCHEMA_VERSION = 1


class ConfigError(Exception):
    """Raised when config.yaml is missing, malformed, or fails validation."""


def load(project_root: Path) -> dict[str, Any]:
    """Load and validate config.yaml from `<project_root>/wiki/config.yaml`.

    Returns the parsed config dict on success. Raises ConfigError otherwise.
    """
    path = project_root / CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"{CONFIG_PATH} not found in {project_root}. "
            f"Run /code-wiki:init first."
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"{CONFIG_PATH} is not valid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_PATH} must be a YAML mapping at the top level.")

    validate(data, project_root)
    return data


def validate(config: dict[str, Any], project_root: Path) -> None:
    """Validate a parsed config against the v1 schema.

    Raises ConfigError on the first violation. Ordering of checks is deliberate:
    schema shape first, then source-root rules.
    """
    if config.get("version") != SCHEMA_VERSION:
        raise ConfigError(
            f"config.yaml version must be {SCHEMA_VERSION}; got {config.get('version')!r}"
        )

    source_roots = config.get("source_roots")
    if not isinstance(source_roots, list):
        raise ConfigError("config.yaml: source_roots must be a list")

    # Each source root entry must be a dict with a string `path`.
    paths: list[str] = []
    for i, entry in enumerate(source_roots):
        if not isinstance(entry, dict):
            raise ConfigError(
                f"config.yaml: source_roots[{i}] must be a mapping with `path:`"
            )
        path = entry.get("path")
        if not isinstance(path, str):
            raise ConfigError(
                f"config.yaml: source_roots[{i}].path must be a string"
            )
        _validate_source_root(path, project_root, idx=i)
        paths.append(path)

    _check_no_nesting(paths)

    # Optional fields type-checks.
    if "wiki_language" in config and not isinstance(config["wiki_language"], str):
        raise ConfigError("config.yaml: wiki_language must be a string")
    if "language_hints" in config:
        hints = config["language_hints"]
        if not isinstance(hints, list) or not all(isinstance(h, str) for h in hints):
            raise ConfigError("config.yaml: language_hints must be a list of strings")
    if "ignore_patterns" in config:
        patterns = config["ignore_patterns"]
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ConfigError("config.yaml: ignore_patterns must be a list of strings")
    if "per_file_pages" in config:
        pfp = config["per_file_pages"]
        if not isinstance(pfp, dict):
            raise ConfigError("config.yaml: per_file_pages must be a mapping")
        for key, expected_type in (
            ("enabled", bool),
            ("min_loc", int),
            ("max_files_per_folder", int),
        ):
            if key in pfp and not isinstance(pfp[key], expected_type):
                raise ConfigError(
                    f"config.yaml: per_file_pages.{key} must be {expected_type.__name__}"
                )


def _validate_source_root(path: str, project_root: Path, idx: int) -> None:
    """Apply source-root rules from SPEC §3."""
    if not path:
        raise ConfigError(f"config.yaml: source_roots[{idx}].path must not be empty")
    if path == ".":
        raise ConfigError(
            f'config.yaml: source_roots[{idx}].path cannot be "."; '
            f"specify a sub-directory."
        )
    p = Path(path)
    if p.is_absolute():
        raise ConfigError(
            f"config.yaml: source_roots[{idx}].path must be relative; got {path!r}"
        )
    # Disallow paths that escape the project root.
    parts = p.parts
    if ".." in parts:
        raise ConfigError(
            f"config.yaml: source_roots[{idx}].path must not contain '..'"
        )
    # Reserved top-level directories.
    if parts[0] in RESERVED_DIRS:
        raise ConfigError(
            f"config.yaml: source_roots[{idx}].path cannot be inside "
            f"{parts[0]!r} (reserved by code-wiki)"
        )
    # Must exist as a directory at validation time.
    full = project_root / p
    if not full.is_dir():
        raise ConfigError(
            f"config.yaml: source_roots[{idx}].path {path!r} is not a directory"
        )


def _check_no_nesting(paths: list[str]) -> None:
    """No source root may be a prefix of another (e.g. 'src' and 'src/api')."""
    normalized = [Path(p).as_posix() for p in paths]
    for i, a in enumerate(normalized):
        for j, b in enumerate(normalized):
            if i == j:
                continue
            if b == a or b.startswith(a + "/"):
                raise ConfigError(
                    f"config.yaml: source_roots[{j}] {paths[j]!r} nests inside "
                    f"source_roots[{i}] {paths[i]!r}"
                )
