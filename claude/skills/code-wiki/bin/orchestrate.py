#!/usr/bin/env python3
"""Compute a dispatch plan from a code-wiki work list.

Input: a JSON array of work items (the output of `walk-tree.py` for build /
rebuild, or the `pages` field of `scan-changes.py` for sync).

Output (stdout): a JSON dispatch plan that the slash command's LLM consumes
to drive parallel agent dispatch. The plan groups items into topological waves
(a wave = items whose `child_wikis` are either already on disk or scheduled in
a strictly earlier wave) and pre-renders each item with the exact `Skill` name
and JSON-escaped args string ready to drop into a Skill(...) call.

Why this script exists
----------------------
Empirically, agents driven by a slash command that hand-loops over a long work
list and invokes `Skill(...)` repeatedly are flaky: a non-trivial fraction of
agents stop after the first Skill return, treating it as task completion. The
reliable pattern is **one agent per Skill call**, dispatched in concurrency
batches within each topological wave. That requires:

1. Pre-computing waves so the LLM never has to walk the dependency DAG itself.
2. Pre-rendering Skill args (folder_abs, JSON-escaped string, etc.) so the LLM
   never has to handcraft 100+ JSON-in-JSON strings.
3. Suggesting a concurrency cap so the LLM doesn't fire 100 agents at once.

This script does (1)-(3) deterministically in Python; the LLM only handles
agent dispatch and notification reconciliation.

Usage
-----
    python3 walk-tree.py --project-root . | \\
        python3 orchestrate.py --project-root . --operation build

    python3 orchestrate.py --project-root . --worklist /tmp/work.json \\
        --operation sync --concurrency 8 --skip-existing

Output shape
------------
    {
      "operation": "build",
      "project_root": "/abs/path",
      "wiki_language": "ko",
      "language_hints": [...],
      "concurrency": 10,
      "totals": {"items": 154, "waves": 5, "batches": 16, "leaves": 126, "parents": 28},
      "waves": [
        {
          "wave": 1,
          "size": 126,
          "batches": [
            {
              "batch": 1,
              "size": 10,
              "items": [
                {
                  "skill": "code-wiki:generate-leaf-page",
                  "wiki_path": "wiki/.../index.md",
                  "args_json": "{\\"folder_abs\\": ..., ...}"
                },
                ... 10 total ...
              ]
            },
            ... 13 batches in wave 1 (12 of size 10 + 1 of size 6) ...
          ]
        },
        {"wave": 2, "size": 17, "batches": [...]},
        ...
      ]
    }

The LLM iterates `waves` in order, and within each wave iterates `batches` in
order. For each batch, it dispatches all `items` in parallel and waits for
every agent to finish before starting the next batch. Waves themselves must
be processed strictly in order (a parent's children must exist on disk before
the parent is generated). Batches inside a wave have no inter-dependency and
exist solely to cap concurrency at `concurrency`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the lib package importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import config as cfg  # noqa: E402


SKILL_LEAF = "code-wiki:generate-leaf-page"
SKILL_PARENT = "code-wiki:generate-parent-page"


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _on_disk(project_root: Path, wiki_relpath: str) -> bool:
    target = project_root / wiki_relpath
    try:
        return target.is_file() and target.stat().st_size > 0
    except OSError:
        return False


def render_item(item: dict, *, project_root: Path, lang: str, hints: list[str]) -> dict:
    """Pre-render one work item into a dispatch entry.

    The `args_json` field is the *string* form of the JSON object, ready to be
    inserted as the value of a Skill(args="...") call. The caller still needs
    to escape inner double-quotes when embedding it in a slash-command prompt
    (e.g. `args=\"{...}\"` style) — but the JSON content itself is canonical.
    """
    args = {
        "folder_abs": str(project_root / item["folder_relpath"]),
        "folder_relpath": item["folder_relpath"],
        "source_root": item["source_root"],
        "loose_files": [_basename(s) for s in item.get("source_files", [])],
        "target_wiki_relpath": item["wiki_path"],
        "wiki_language": lang,
        "language_hints": hints,
    }
    if item["kind"] == "parent":
        args["child_wiki_paths"] = item.get("child_wikis", [])
        skill = SKILL_PARENT
    elif item["kind"] == "leaf":
        skill = SKILL_LEAF
    else:
        raise ValueError(f"unknown item kind: {item['kind']!r} for {item.get('wiki_path')}")

    return {
        "skill": skill,
        "wiki_path": item["wiki_path"],
        "args_json": json.dumps(args, ensure_ascii=False),
    }


def compute_waves(items: list[dict], *, project_root: Path) -> list[list[dict]]:
    """Group items into topological waves.

    An item is "ready" for a wave when every entry in its `child_wikis` list
    is either already present on disk (a non-empty file) or has been scheduled
    in a strictly earlier wave. Items with no children (typical leaves) land
    in wave 1 alongside any parents whose dependencies are already satisfied.

    Raises SystemExit(2) with a stderr diagnostic if any item's dependencies
    cannot be resolved (cycle or missing child wiki not in the work list).
    """
    on_disk = {x["wiki_path"] for x in items if _on_disk(project_root, x["wiki_path"])}

    # Also consider any child_wiki referenced by an item but not in the work list
    # — if its file exists on disk, it's a satisfied dep; otherwise it's an
    # unresolvable external dep and we surface it.
    referenced = {c for x in items for c in x.get("child_wikis", [])}
    for ref in referenced:
        if ref not in on_disk and not any(x["wiki_path"] == ref for x in items):
            if _on_disk(project_root, ref):
                on_disk.add(ref)

    waves: list[list[dict]] = []
    remaining = list(items)
    scheduled: set[str] = set()

    while remaining:
        ready = [
            x for x in remaining
            if all(c in on_disk or c in scheduled
                   for c in x.get("child_wikis", []))
        ]
        if not ready:
            unresolved = []
            for x in remaining:
                missing = [c for c in x.get("child_wikis", [])
                           if c not in on_disk and c not in scheduled]
                if missing:
                    unresolved.append((x["wiki_path"], missing))
            print(
                f"orchestrate.py: cannot resolve dependencies for {len(remaining)} item(s); "
                "cycle or external child wiki missing.",
                file=sys.stderr,
            )
            for wp, miss in unresolved[:10]:
                print(f"  {wp}: missing {miss}", file=sys.stderr)
            sys.exit(2)
        # Stable order within wave: preserve original work-list order
        ready.sort(key=lambda x: items.index(x))
        waves.append(ready)
        for x in ready:
            scheduled.add(x["wiki_path"])
        remaining = [x for x in remaining if x["wiki_path"] not in scheduled]

    return waves


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute a topological + per-page dispatch plan "
                    "from a code-wiki work list.",
    )
    parser.add_argument("--project-root", required=True, type=Path,
                        help="Absolute path to the project root.")
    parser.add_argument("--worklist", default="-",
                        help="Path to a work-list JSON file, or '-' for stdin (default).")
    parser.add_argument("--operation", default="build",
                        choices=["build", "rebuild", "sync"],
                        help="Operation tag included in the plan metadata (default: build).")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="Suggested max concurrent dispatches per wave (default: 10).")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Drop work items whose target wiki file already exists "
                             "(non-empty) on disk. Useful for resuming a partial build.")
    args = parser.parse_args()

    project_root = args.project_root.resolve()

    # Load the work list (stdin or file)
    try:
        if args.worklist == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.worklist).read_text(encoding="utf-8")
    except OSError as e:
        print(f"orchestrate.py: failed to read work list: {e}", file=sys.stderr)
        return 1

    raw = raw.strip()
    if not raw:
        print("orchestrate.py: work list is empty (no input on stdin or file empty).",
              file=sys.stderr)
        return 1

    try:
        items: list[dict] = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"orchestrate.py: failed to parse work list JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(items, list):
        print(f"orchestrate.py: expected a JSON array at the top level, got "
              f"{type(items).__name__}.", file=sys.stderr)
        return 1

    # Load wiki/config.yaml for language settings
    try:
        config = cfg.load(project_root)
    except cfg.ConfigError as e:
        print(f"orchestrate.py: {e}", file=sys.stderr)
        return 1

    lang: str = (config.get("wiki_language") or "en")
    hints: list[str] = list(config.get("language_hints") or [])

    leaves_total = sum(1 for x in items if x.get("kind") == "leaf")
    parents_total = sum(1 for x in items if x.get("kind") == "parent")

    # Optional: drop already-built items (resume support).
    skipped = 0
    if args.skip_existing:
        before = len(items)
        items = [x for x in items if not _on_disk(project_root, x["wiki_path"])]
        skipped = before - len(items)

    if not items:
        # Emit an empty-but-valid plan; the caller decides how to report.
        plan = {
            "operation": args.operation,
            "project_root": str(project_root),
            "wiki_language": lang,
            "language_hints": hints,
            "concurrency": args.concurrency,
            "totals": {
                "items": 0,
                "waves": 0,
                "batches": 0,
                "leaves": leaves_total,
                "parents": parents_total,
                "skipped_existing": skipped,
            },
            "waves": [],
        }
        json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    # Group into waves (topological).
    waves_raw = compute_waves(items, project_root=project_root)

    # Pre-render each item, then split each wave into concurrency-capped batches.
    plan_waves = []
    total_batches = 0
    for wi, wave_items in enumerate(waves_raw, start=1):
        rendered = [
            render_item(x, project_root=project_root, lang=lang, hints=hints)
            for x in wave_items
        ]
        cap = max(1, args.concurrency)
        batches = []
        for bi, start in enumerate(range(0, len(rendered), cap), start=1):
            chunk = rendered[start:start + cap]
            batches.append({"batch": bi, "size": len(chunk), "items": chunk})
        total_batches += len(batches)
        plan_waves.append({
            "wave": wi,
            "size": len(rendered),
            "batches": batches,
        })

    plan = {
        "operation": args.operation,
        "project_root": str(project_root),
        "wiki_language": lang,
        "language_hints": hints,
        "concurrency": args.concurrency,
        "totals": {
            "items": sum(w["size"] for w in plan_waves),
            "waves": len(plan_waves),
            "batches": total_batches,
            "leaves": leaves_total,
            "parents": parents_total,
            "skipped_existing": skipped,
        },
        "waves": plan_waves,
    }

    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
