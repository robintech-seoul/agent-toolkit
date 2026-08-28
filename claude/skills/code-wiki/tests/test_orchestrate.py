"""Tests for bin/orchestrate.py.

Like the other bin/ tests, we exercise the script as a subprocess and parse its
JSON output. Edge cases focus on the wave computation (topological ordering,
on-disk dependency satisfaction, missing-dep diagnostics) and the per-item
rendering (Skill name selection, args_json correctness).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ORCHESTRATE = Path(__file__).resolve().parents[1] / "bin" / "orchestrate.py"


# ---- helpers ---------------------------------------------------------------


def _setup_project(tmp_path: Path, *, config: dict | None = None) -> Path:
    """Create a minimal project skeleton with wiki/config.yaml.

    Source roots and ignore patterns default to a single 'src' root.
    """
    if config is None:
        config = {
            "version": 1,
            "source_roots": [{"path": "src"}],
            "wiki_language": "ko",
            "language_hints": ["python"],
        }
    (tmp_path / "src").mkdir()
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    wiki.joinpath("config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    return tmp_path


def _run(project_root: Path, worklist: list[dict], *extra_args: str) -> tuple[int, dict | None, str]:
    """Run orchestrate.py with `worklist` on stdin. Return (rc, parsed-stdout, stderr)."""
    res = subprocess.run(
        [sys.executable, str(ORCHESTRATE),
         "--project-root", str(project_root),
         *extra_args],
        input=json.dumps(worklist),
        capture_output=True,
        text=True,
    )
    parsed: dict | None = None
    if res.returncode == 0 and res.stdout.strip():
        parsed = json.loads(res.stdout)
    return res.returncode, parsed, res.stderr


def _leaf(folder: str, *, source_root: str = "src", files: list[str] | None = None) -> dict:
    files = files or [f"{folder}/main.py"]
    return {
        "source_root": source_root,
        "folder_relpath": folder,
        "kind": "leaf",
        "source_files": files,
        "child_wikis": [],
        "wiki_path": f"wiki/{folder}/index.md",
    }


def _parent(folder: str, children: list[str], *,
            source_root: str = "src", loose: list[str] | None = None) -> dict:
    return {
        "source_root": source_root,
        "folder_relpath": folder,
        "kind": "parent",
        "source_files": loose or [],
        "child_wikis": [f"wiki/{c}/index.md" for c in children],
        "wiki_path": f"wiki/{folder}/index.md",
    }


# ---- empty / error inputs --------------------------------------------------


def test_empty_stdin_errors(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    res = subprocess.run(
        [sys.executable, str(ORCHESTRATE), "--project-root", str(tmp_path)],
        input="",
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "empty" in res.stderr.lower()


def test_invalid_json_errors(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    res = subprocess.run(
        [sys.executable, str(ORCHESTRATE), "--project-root", str(tmp_path)],
        input="not json",
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "parse" in res.stderr.lower() or "json" in res.stderr.lower()


def test_missing_config_errors(tmp_path: Path) -> None:
    # Project root without wiki/config.yaml.
    (tmp_path / "src").mkdir()
    rc, plan, err = _run(tmp_path, [_leaf("src/auth")])
    assert rc == 1
    assert "config" in err.lower()


# ---- basic plan structure --------------------------------------------------


def _wave_items(plan: dict, wave_idx: int) -> list[dict]:
    """Flatten all items across batches of a given wave (1-indexed in the plan)."""
    wave = plan["waves"][wave_idx]
    out = []
    for batch in wave["batches"]:
        out.extend(batch["items"])
    return out


def test_single_leaf_one_wave(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    rc, plan, err = _run(tmp_path, [_leaf("src/auth")])
    assert rc == 0, err
    assert plan["operation"] == "build"
    assert plan["wiki_language"] == "ko"
    assert plan["language_hints"] == ["python"]
    assert plan["totals"] == {
        "items": 1, "waves": 1, "batches": 1,
        "leaves": 1, "parents": 0, "skipped_existing": 0,
    }
    assert len(plan["waves"]) == 1
    wave = plan["waves"][0]
    assert wave["wave"] == 1 and wave["size"] == 1
    assert len(wave["batches"]) == 1
    batch = wave["batches"][0]
    assert batch["batch"] == 1 and batch["size"] == 1 and len(batch["items"]) == 1
    item = batch["items"][0]
    assert item["skill"] == "code-wiki:generate-leaf-page"
    assert item["wiki_path"] == "wiki/src/auth/index.md"
    args = json.loads(item["args_json"])
    assert args["folder_abs"] == str((tmp_path / "src/auth").resolve())
    assert args["folder_relpath"] == "src/auth"
    assert args["source_root"] == "src"
    assert args["loose_files"] == ["main.py"]
    assert args["target_wiki_relpath"] == "wiki/src/auth/index.md"
    assert args["wiki_language"] == "ko"
    assert args["language_hints"] == ["python"]
    assert "child_wiki_paths" not in args  # leaves don't carry child_wiki_paths


def test_parent_with_children_uses_parent_skill(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    items = [
        _leaf("src/api/auth"),
        _leaf("src/api/users"),
        _parent("src/api", ["src/api/auth", "src/api/users"]),
    ]
    rc, plan, err = _run(tmp_path, items)
    assert rc == 0, err
    # leaves go in wave 1, parent in wave 2
    assert len(plan["waves"]) == 2
    assert plan["waves"][0]["size"] == 2
    assert plan["waves"][1]["size"] == 1
    parent_items = _wave_items(plan, 1)
    assert len(parent_items) == 1
    parent_item = parent_items[0]
    assert parent_item["skill"] == "code-wiki:generate-parent-page"
    args = json.loads(parent_item["args_json"])
    assert args["child_wiki_paths"] == [
        "wiki/src/api/auth/index.md", "wiki/src/api/users/index.md",
    ]


# ---- topological wave computation ------------------------------------------


def test_wave_ordering_three_levels(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    items = [
        _leaf("src/api/v1/auth"),
        _parent("src/api/v1", ["src/api/v1/auth"]),
        _parent("src/api", ["src/api/v1"]),
    ]
    rc, plan, err = _run(tmp_path, items)
    assert rc == 0, err
    assert plan["totals"]["waves"] == 3
    paths_per_wave = [
        [it["wiki_path"] for it in _wave_items(plan, i)]
        for i in range(3)
    ]
    assert paths_per_wave[0] == ["wiki/src/api/v1/auth/index.md"]
    assert paths_per_wave[1] == ["wiki/src/api/v1/index.md"]
    assert paths_per_wave[2] == ["wiki/src/api/index.md"]


def test_wave_with_independent_siblings_grouped_together(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    items = [
        _leaf("src/a"),
        _leaf("src/b"),
        _leaf("src/c"),
        _parent("src", ["src/a", "src/b", "src/c"]),
    ]
    rc, plan, err = _run(tmp_path, items)
    assert rc == 0, err
    assert plan["totals"]["waves"] == 2
    assert plan["waves"][0]["size"] == 3
    # Stable order matches original work-list order.
    assert [it["wiki_path"] for it in _wave_items(plan, 0)] == [
        "wiki/src/a/index.md", "wiki/src/b/index.md", "wiki/src/c/index.md",
    ]
    assert plan["waves"][1]["size"] == 1


def test_existing_on_disk_satisfies_dependency(tmp_path: Path) -> None:
    """A parent whose children already exist on disk lands in wave 1."""
    _setup_project(tmp_path)
    # Pre-create the child wiki file on disk.
    (tmp_path / "wiki/src/api/auth").mkdir(parents=True)
    (tmp_path / "wiki/src/api/auth/index.md").write_text("# already there\n")

    items = [_parent("src/api", ["src/api/auth"])]
    rc, plan, err = _run(tmp_path, items)
    assert rc == 0, err
    # Only the parent in the work list; its child wiki is already on disk so
    # the parent is immediately ready.
    assert plan["totals"]["waves"] == 1
    assert _wave_items(plan, 0)[0]["wiki_path"] == "wiki/src/api/index.md"


def test_unresolved_dependency_exits_2(tmp_path: Path) -> None:
    """Parent referencing a child that is neither in the work list nor on disk."""
    _setup_project(tmp_path)
    items = [_parent("src/api", ["src/api/missing"])]
    rc, plan, err = _run(tmp_path, items)
    assert rc == 2
    assert "missing" in err.lower() or "resolve" in err.lower()


# ---- skip-existing flag ----------------------------------------------------


def test_skip_existing_drops_done_items(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    # Pretend src/a is already built.
    (tmp_path / "wiki/src/a").mkdir(parents=True)
    (tmp_path / "wiki/src/a/index.md").write_text("# a\n")

    items = [_leaf("src/a"), _leaf("src/b")]
    rc, plan, err = _run(tmp_path, items, "--skip-existing")
    assert rc == 0, err
    assert plan["totals"]["items"] == 1
    assert plan["totals"]["skipped_existing"] == 1
    assert _wave_items(plan, 0)[0]["wiki_path"] == "wiki/src/b/index.md"


def test_skip_existing_all_done_yields_empty_plan(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    (tmp_path / "wiki/src/a").mkdir(parents=True)
    (tmp_path / "wiki/src/a/index.md").write_text("# a\n")
    rc, plan, err = _run(tmp_path, [_leaf("src/a")], "--skip-existing")
    assert rc == 0, err
    assert plan["totals"]["items"] == 0
    assert plan["totals"]["waves"] == 0
    assert plan["waves"] == []


# ---- args rendering edge cases ---------------------------------------------


def test_loose_files_basenames_only(tmp_path: Path) -> None:
    """Source files in work list are project-root-relative; rendered loose_files
    are basenames (the leaf-page skill expects basenames)."""
    _setup_project(tmp_path)
    item = _leaf("src/util", files=[
        "src/util/string.py", "src/util/io.py", "src/util/__init__.py",
    ])
    rc, plan, err = _run(tmp_path, [item])
    assert rc == 0, err
    args = json.loads(_wave_items(plan, 0)[0]["args_json"])
    assert args["loose_files"] == ["string.py", "io.py", "__init__.py"]


def test_concurrency_flag_recorded(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    rc, plan, err = _run(tmp_path, [_leaf("src/x")], "--concurrency", "3")
    assert rc == 0, err
    assert plan["concurrency"] == 3


def test_operation_flag_recorded(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    rc, plan, err = _run(tmp_path, [_leaf("src/x")], "--operation", "sync")
    assert rc == 0, err
    assert plan["operation"] == "sync"


def test_unicode_paths_round_trip(tmp_path: Path) -> None:
    """Korean folder names should survive json.dumps without escaping."""
    _setup_project(tmp_path)
    item = _leaf("src/한글")
    rc, plan, err = _run(tmp_path, [item])
    assert rc == 0, err
    args_json = _wave_items(plan, 0)[0]["args_json"]
    # ensure_ascii=False path: literal unicode is preserved in args_json
    assert "한글" in args_json
    args = json.loads(args_json)
    assert args["folder_relpath"] == "src/한글"


def test_unknown_kind_errors(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    bad = {
        "source_root": "src", "folder_relpath": "src/x", "kind": "topic",
        "source_files": [], "child_wikis": [], "wiki_path": "wiki/src/x/index.md",
    }
    rc, plan, err = _run(tmp_path, [bad])
    # The error surfaces during render; exit code is non-zero (Python traceback).
    assert rc != 0


# ---- batch splitting -------------------------------------------------------


def test_wave_split_into_batches_at_concurrency_cap(tmp_path: Path) -> None:
    """A wave of 26 items with concurrency=10 should produce 3 batches:
    sizes 10, 10, 6, in original order."""
    _setup_project(tmp_path)
    items = [_leaf(f"src/m{i:02d}") for i in range(26)]
    rc, plan, err = _run(tmp_path, items, "--concurrency", "10")
    assert rc == 0, err
    assert plan["totals"]["items"] == 26
    assert plan["totals"]["waves"] == 1
    assert plan["totals"]["batches"] == 3
    wave = plan["waves"][0]
    assert wave["size"] == 26
    assert [b["size"] for b in wave["batches"]] == [10, 10, 6]
    assert [b["batch"] for b in wave["batches"]] == [1, 2, 3]
    # Original work-list order preserved across batch boundaries
    flat = _wave_items(plan, 0)
    assert [it["wiki_path"] for it in flat] == [
        f"wiki/src/m{i:02d}/index.md" for i in range(26)
    ]


def test_batch_size_equals_concurrency_when_evenly_divisible(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    items = [_leaf(f"src/m{i}") for i in range(20)]
    rc, plan, err = _run(tmp_path, items, "--concurrency", "5")
    assert rc == 0, err
    assert plan["totals"]["batches"] == 4
    assert all(b["size"] == 5 for b in plan["waves"][0]["batches"])


def test_concurrency_one_yields_one_item_per_batch(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    items = [_leaf(f"src/m{i}") for i in range(4)]
    rc, plan, err = _run(tmp_path, items, "--concurrency", "1")
    assert rc == 0, err
    assert plan["totals"]["batches"] == 4
    assert all(b["size"] == 1 for b in plan["waves"][0]["batches"])


def test_concurrency_larger_than_wave_yields_single_batch(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    items = [_leaf(f"src/m{i}") for i in range(3)]
    rc, plan, err = _run(tmp_path, items, "--concurrency", "100")
    assert rc == 0, err
    assert plan["totals"]["batches"] == 1
    assert plan["waves"][0]["batches"][0]["size"] == 3


def test_total_batches_aggregates_across_waves(tmp_path: Path) -> None:
    _setup_project(tmp_path)
    # 7 leaves → wave 1; 1 parent → wave 2. concurrency=3 → wave 1 has 3 batches (3,3,1), wave 2 has 1.
    items = [_leaf(f"src/a{i}") for i in range(7)] + [
        _parent("src", [f"src/a{i}" for i in range(7)])
    ]
    rc, plan, err = _run(tmp_path, items, "--concurrency", "3")
    assert rc == 0, err
    assert plan["totals"]["waves"] == 2
    assert plan["totals"]["batches"] == 3 + 1
    assert [b["size"] for b in plan["waves"][0]["batches"]] == [3, 3, 1]
    assert [b["size"] for b in plan["waves"][1]["batches"]] == [1]
