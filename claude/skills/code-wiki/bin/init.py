#!/usr/bin/env python3
"""Bootstrap code-wiki in a user's project.

Creates `wiki/CLAUDE.md`, `wiki/config.yaml`, `.code-wiki/`, and appends
`.code-wiki/` to `.gitignore`. Aborts if `wiki/` already exists.

Invocation (from /code-wiki:init):
    python3 init.py \\
        --project-root /path/to/repo \\
        --source-roots src,packages/server \\
        --language en \\
        --language-hints typescript,react

The CLAUDE_PLUGIN_ROOT environment variable must point to the plugin directory
so we can find templates/. (Set automatically by Claude Code.)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add lib/ to sys.path. The bin script lives at code-wiki/bin/init.py, so
# its sibling lib/ is at code-wiki/bin/lib/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg  # noqa: E402


WIKI_GITIGNORE_LINE = ".code-wiki/"


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap code-wiki in a project.")
    parser.add_argument("--project-root", required=True, type=Path,
                        help="Absolute path to the user's project root.")
    parser.add_argument("--source-roots", required=True,
                        help="Comma-separated relative source root paths.")
    parser.add_argument("--language", default="en",
                        help="Wiki output language (default: en).")
    parser.add_argument("--language-hints", default="",
                        help="Comma-separated language/framework hints (optional).")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    plugin_root = _plugin_root()

    # 1. Check that wiki/ does not already exist.
    wiki_dir = project_root / "wiki"
    if wiki_dir.exists():
        return _fail(
            f"wiki/ already exists at {wiki_dir}. "
            f"Remove it first if you want to re-initialize."
        )

    # 2. Parse and validate source roots.
    source_roots = [s.strip() for s in args.source_roots.split(",") if s.strip()]
    if not source_roots:
        return _fail("--source-roots must list at least one directory.")
    try:
        _validate_source_roots(source_roots, project_root)
    except cfg.ConfigError as e:
        return _fail(str(e))

    # 3. Read templates.
    try:
        claude_template = (plugin_root / "templates" / "wiki-CLAUDE.md").read_text(encoding="utf-8")
        config_template = (plugin_root / "templates" / "config-default.yaml").read_text(encoding="utf-8")
    except FileNotFoundError as e:
        return _fail(f"plugin template missing: {e}. Reinstall the plugin?")

    # 4. Build the populated config.yaml content.
    hints_list = [h.strip() for h in args.language_hints.split(",") if h.strip()]
    populated = _populate_config(config_template, source_roots, args.language, hints_list)

    # 5. Write everything atomically-ish (in order; bail early if anything fails).
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "CLAUDE.md").write_text(claude_template, encoding="utf-8")
    (wiki_dir / "config.yaml").write_text(populated, encoding="utf-8")
    (project_root / ".code-wiki").mkdir(exist_ok=True)
    _ensure_gitignore_entry(project_root)

    # 6. Print next-step guidance to stdout.
    print(f"Initialized code-wiki at {project_root}")
    print(f"  - wiki/CLAUDE.md   (style guide; edit to taste)")
    print(f"  - wiki/config.yaml (configuration; review and adjust)")
    print(f"  - .code-wiki/      (local state; gitignored)")
    print(f"")
    print(f"Source roots configured:")
    for sr in source_roots:
        print(f"  - {sr}")
    print(f"")
    print(f"Next: run /code-wiki:build to generate the initial wiki.")
    return 0


def _plugin_root() -> Path:
    """Locate the plugin's root directory (containing templates/, bin/, etc.).

    Prefer CLAUDE_PLUGIN_ROOT (set by Claude Code) for robustness; fall back to
    the script's parent's parent (bin/init.py → bin/ → plugin root).
    """
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def _validate_source_roots(paths: list[str], project_root: Path) -> None:
    """Run config-level source-root validation without writing config.yaml yet.

    We construct a minimal config dict and call cfg.validate so the rules stay
    in one place.
    """
    fake_config = {
        "version": cfg.SCHEMA_VERSION,
        "source_roots": [{"path": p} for p in paths],
    }
    cfg.validate(fake_config, project_root)


def _populate_config(
    template: str,
    source_roots: list[str],
    language: str,
    hints: list[str],
) -> str:
    """Replace the placeholder fields in the default config template with the
    user's choices. Keeps the original comments intact.

    The default template has:
        source_roots: []
        wiki_language: en
        language_hints: []

    We replace those lines (in place) with populated equivalents.
    """
    out_lines: list[str] = []
    for line in template.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("source_roots:") and stripped.rstrip() == "source_roots: []":
            out_lines.append("source_roots:")
            for sr in source_roots:
                out_lines.append(f"  - path: {sr}")
        elif stripped.startswith("wiki_language:"):
            out_lines.append(f"wiki_language: {language}")
        elif stripped.startswith("language_hints:") and stripped.rstrip() == "language_hints: []":
            if not hints:
                out_lines.append("language_hints: []")
            else:
                out_lines.append("language_hints:")
                for h in hints:
                    out_lines.append(f"  - {h}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"


def _ensure_gitignore_entry(project_root: Path) -> None:
    """Append `.code-wiki/` to .gitignore if not already present.

    Idempotent: re-running init (after manually deleting wiki/) won't duplicate.
    Creates .gitignore if missing.
    """
    gitignore = project_root / ".gitignore"
    existing = ""
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
        # Match the entry exactly (with or without trailing slash, ignoring whitespace).
        for line in existing.splitlines():
            if line.strip() in {".code-wiki/", ".code-wiki"}:
                return
    # Append. Ensure preceding newline so we don't accidentally join lines.
    sep = "" if existing.endswith("\n") or not existing else "\n"
    gitignore.write_text(existing + sep + WIKI_GITIGNORE_LINE + "\n", encoding="utf-8")


def _fail(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
