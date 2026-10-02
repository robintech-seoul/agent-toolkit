#!/usr/bin/env python3
"""Is the architecture map fresh, and is the code-wiki fresh?

Read-only: this never writes to the work tree, `wiki/` or `.code-wiki/`,
except for `record`, which writes the map's sidecar on request. (Checking a
change map built with uncommitted work snapshots the work tree into git's
object store through a temporary index; the user's index is never touched.)

    status.py check  --root <repo> --map <index.html> [--wiki <dir> …] [--against <commit>]
    status.py record --root <repo> --map <index.html> --scope <path> [--scope …]

`check` prints {"kind", "map": {...}, "wiki": {...}, "wikis": [...]} as JSON.
`wiki` is the combined state; `wikis` has one entry per wiki directory, each
with `dir`.

`kind` is "build" for a map from /arch-explorer:build and "diff" for a change
map from /arch-explorer:diff, recognised by its own sidecar
`<stem>.arch-explorer.json` (see diff_session.py). For a change map, `map`
says whether the branch moved since the map was drawn, and the wiki is judged
against the merge-base: the branch's own changes are what the map explains,
not something the wiki is behind on. `--against` judges the wiki against
that commit before the change map exists (diff --open checks the wiki first).

`--wiki <dir>` names a directory, relative to the repo root, that holds a
code-wiki (`<dir>/wiki/config.yaml`, `<dir>/.code-wiki/state.json`) — for a
monorepo whose wikis live next to each sub-project. Repeat it for several;
without it the wiki is the one at the repo root (`.`). When the root has no
wiki and no `--wiki` was given, `wiki.candidates` lists the directories that
hold a committed `wiki/config.yaml`.

Map states:  missing | unknown | stale | fresh
Wiki states: missing | unknown | stale | fresh
(`no-plugin` is decided by the open skill, which can see installed skills.)

The wiki check reads code-wiki's on-disk contract only — `wiki/config.yaml`
and `.code-wiki/state.json` (schema v1) — and never imports or runs code-wiki.
It is conservative: `ignore_patterns` are not applied, so it may call a wiki
stale when only ignored files changed (sync then reports "up to date"), but
it never calls a stale wiki fresh.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_NAME = "arch-explorer.json"
SIDECAR_VERSION = 1
WIKI_STATE_VERSION = 1
SAMPLE = 10
# Never counted as source changes: they are outputs, not inputs.
ALWAYS_EXCLUDED = ("wiki/", ".code-wiki/")
DEFAULT_WIKI = "."
# Worst first: the combined state of several wikis is the worst of them.
WIKI_RANK = {"missing": 3, "unknown": 2, "stale": 1, "fresh": 0}
DIFF_SIDECAR_SUFFIX = ".arch-explorer.json"
DIFF_SIDECAR_VERSION = 1


def _git(root: Path, *args: str, env: dict | None = None) -> str | None:
    """Run git in `root`; None when git fails (not a repo, unknown sha, …)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=True,
            env={**os.environ, **env} if env else None,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout


def _head(root: Path) -> str | None:
    out = _git(root, "rev-parse", "HEAD")
    return out.strip() if out else None


def _is_commit(root: Path, sha: str) -> bool:
    return _git(root, "cat-file", "-e", f"{sha}^{{commit}}") is not None


def _rev(root: Path, ref: str) -> str | None:
    """The commit `ref` names, or None."""
    out = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.strip() if out else None


def _is_ancestor(root: Path, older: str, newer: str) -> bool:
    return _git(root, "merge-base", "--is-ancestor", older, newer) is not None


def snapshot_tree(root: Path, exclude: list[str] | None = None) -> str | None:
    """A tree object of the work tree as `git add -A` would stage it.

    Staged through a copy of the index, so the user's own index is never
    touched. `.gitignore` is honoured; `exclude` (repo-relative paths) are left
    out — the change map's own files, which would otherwise count as changes.
    """
    tmp = tempfile.mkdtemp(prefix="archx-index-")
    try:
        index = Path(tmp) / "index"
        real = _git(root, "rev-parse", "--git-path", "index")
        if real:
            src = Path(real.strip())
            src = src if src.is_absolute() else root / src
            if src.is_file():
                shutil.copyfile(src, index)
        env = {"GIT_INDEX_FILE": str(index)}
        spec = ["--", "."] + [f":(exclude,literal){p}" for p in exclude or []]
        if _git(root, "add", "-A", *spec, env=env) is None:
            return None
        out = _git(root, "write-tree", env=env)
        return out.strip() if out else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _changed(root: Path, base: str, paths: list[str], exclude: list[str],
             to: str = "HEAD") -> list[str] | None:
    """Files changed between `base` and `to` under `paths`, minus `exclude` prefixes."""
    out = _git(root, "diff", "--name-only", base, to, "--", *paths)
    if out is None:
        return None
    prefixes = [p if p.endswith("/") else p + "/" for p in exclude]
    return [
        f for f in out.splitlines()
        if f and not any(f == p.rstrip("/") or f.startswith(p) for p in prefixes)
    ]


def _rel(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _under(dir_: str, rel: str) -> str:
    """`rel` inside the repo-relative directory `dir_` (`.` is the repo root)."""
    rel = rel.strip("/")
    if rel in ("", "."):
        return dir_
    return rel if dir_ == "." else f"{dir_}/{rel}"


def wiki_location(dir_: str) -> str:
    """Where the pages of the wiki held by `dir_` live, repo-relative: `web/api/wiki/`."""
    return _under(dir_, "wiki") + "/"


def normalize_wiki_dirs(root: Path, dirs: list[str] | None) -> list[str]:
    """Repo-relative POSIX paths, deduplicated in order; `["."]` when none given.

    A directory outside the repository is an error: freshness is read from this
    repository's git history, which says nothing about it.
    """
    out: list[str] = []
    for d in dirs or [DEFAULT_WIKI]:
        p = Path(d)
        rel = _rel(root, p if p.is_absolute() else root / p)
        if rel is None:
            raise SystemExit(f"--wiki {d}: not inside the repository {root}")
        if rel not in out:
            out.append(rel)
    return out


def wiki_excludes(wiki_dirs: list[str] | None) -> list[str]:
    """The wiki output directories of every wiki: never counted as source changes."""
    out = []
    for d in wiki_dirs or [DEFAULT_WIKI]:
        out += [_under(d, "wiki/") + "/", _under(d, ".code-wiki/") + "/"]
    return out


def _changes_result(changed: list[str], base: str) -> dict:
    if changed:
        return {"state": "stale", "sha": base, "changed": len(changed),
                "sample": changed[:SAMPLE]}
    return {"state": "fresh", "sha": base}


# ---------------------------------------------------------------- map

def map_status(root: Path, map_path: Path, wiki_dirs: list[str] | None = None) -> dict:
    if not map_path.is_file():
        return {"state": "missing"}
    sidecar = map_path.parent / SIDECAR_NAME
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"state": "unknown", "reason": "no sidecar (map built before 0.3.0)"}
    except (OSError, json.JSONDecodeError) as e:
        return {"state": "unknown", "reason": f"unreadable sidecar: {e}"}
    if not isinstance(meta, dict) or meta.get("version") != SIDECAR_VERSION:
        return {"state": "unknown", "reason": "unsupported sidecar version"}
    if meta.get("dirty"):
        return {"state": "unknown", "sha": meta.get("sha"),
                "reason": "built from uncommitted changes"}
    sha = meta.get("sha")
    if not isinstance(sha, str) or not _is_commit(root, sha):
        return {"state": "unknown", "reason": f"build commit {sha!r} not found"}
    scope = meta.get("scope") or ["."]
    exclude = list(ALWAYS_EXCLUDED) + wiki_excludes(wiki_dirs)
    out_dir = _rel(root, map_path.parent)
    if out_dir and out_dir != ".":
        exclude.append(out_dir)
    changed = _changed(root, sha, scope, exclude)
    if changed is None:
        return {"state": "unknown", "reason": "git diff failed"}
    result = _changes_result(changed, sha)
    result["built_at"] = meta.get("built_at")
    result["scope"] = scope
    return result


def record(root: Path, map_path: Path, scope: list[str]) -> dict:
    """Write the sidecar next to the map: which commit and scope it was built from."""
    head = _head(root)
    if head is None:
        raise SystemExit("record: not a git repository (or no commits yet)")
    scope = scope or ["."]
    porcelain = _git(root, "status", "--porcelain", "--", *scope) or ""
    out_dir = _rel(root, map_path.parent)
    dirty = any(
        line and not (out_dir and out_dir != "." and line[3:].startswith(out_dir + "/"))
        for line in porcelain.splitlines()
    )
    meta = {
        "version": SIDECAR_VERSION,
        "sha": head,
        "scope": scope,
        "dirty": dirty,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (map_path.parent / SIDECAR_NAME).write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


# ---------------------------------------------------------------- change map

def diff_sidecar_path(map_path: Path) -> Path:
    """`feature-x-vs-main.html` → `feature-x-vs-main.arch-explorer.json`, next to it."""
    return map_path.with_name(map_path.stem + DIFF_SIDECAR_SUFFIX)


def load_diff_sidecar(map_path: Path) -> dict | None:
    """The change map's sidecar, or None when the map is not a change map."""
    try:
        meta = json.loads(diff_sidecar_path(map_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (not isinstance(meta, dict) or meta.get("kind") != "diff"
            or meta.get("version") != DIFF_SIDECAR_VERSION):
        return None
    return meta


def diff_map_status(root: Path, map_path: Path, meta: dict | None = None) -> dict:
    """Whether the branch (or, for a map with uncommitted work, the work tree)
    is still where it was when the change map was drawn."""
    if not map_path.is_file():
        return {"state": "missing"}
    meta = meta or load_diff_sidecar(map_path)
    if meta is None:
        return {"state": "unknown", "reason": "no change-map sidecar"}
    info = {k: meta.get(k) for k in ("head", "base", "mb", "uncommitted", "built_at")}
    info["session"] = bool(meta.get("session"))
    head_sha = meta.get("head_sha")
    if not isinstance(head_sha, str) or not _is_commit(root, head_sha):
        return {**info, "state": "unknown", "reason": f"head commit {head_sha!r} not found"}
    now = _rev(root, str(meta.get("head")))
    if now is None:
        return {**info, "state": "unknown", "reason": f"branch {meta.get('head')!r} not found"}
    if now != head_sha:
        if _is_ancestor(root, head_sha, now):
            n = (_git(root, "rev-list", "--count", f"{head_sha}..{now}") or "0").strip()
            return {**info, "state": "stale", "reason": "advanced", "commits": int(n or 0)}
        return {**info, "state": "stale", "reason": "rewritten"}
    if meta.get("uncommitted"):
        after = meta.get("after")
        if not isinstance(after, str) or _git(root, "cat-file", "-e", after) is None:
            return {**info, "state": "unknown", "reason": "work-tree snapshot not found"}
        own = [p for p in (_rel(root, map_path), _rel(root, diff_sidecar_path(map_path))) if p]
        if snapshot_tree(root, own) != after:
            return {**info, "state": "stale", "reason": "worktree"}
    return {**info, "state": "fresh"}


def check(root: Path, map_path: Path, wiki_dirs: list[str] | None = None,
          against: str | None = None) -> dict:
    """Everything `check` reports: map kind and state, and the wikis' state."""
    meta = load_diff_sidecar(map_path)
    if meta is not None:
        combined, each = wikis_status(root, wiki_dirs, against=against or meta.get("mb"))
        return {"kind": "diff", "map": diff_map_status(root, map_path, meta),
                "wiki": combined, "wikis": each}
    combined, each = wikis_status(root, wiki_dirs, against=against)
    return {"kind": "build", "map": map_status(root, map_path, wiki_dirs),
            "wiki": combined, "wikis": each}


# ---------------------------------------------------------------- wiki

def _source_roots(base: Path) -> list[str] | None:
    """source_roots from <base>/wiki/config.yaml, relative to `base`.

    None when PyYAML is absent or the file is odd.
    """
    try:
        import yaml  # code-wiki's own dependency; optional here
    except ImportError:
        return None
    try:
        data = yaml.safe_load((base / "wiki/config.yaml").read_text(encoding="utf-8"))
    except Exception:
        return None
    entries = data.get("source_roots") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return None
    paths = []
    for e in entries:
        p = e.get("path") if isinstance(e, dict) else e
        if not isinstance(p, str) or not p:
            return None
        paths.append(p)
    return paths


def wiki_status(root: Path, wiki_dir: str = DEFAULT_WIKI, against: str | None = None) -> dict:
    """State of the code-wiki held by `wiki_dir` (repo-relative; `.` is the root).

    code-wiki's paths — `source_roots`, the `wiki/` it infers from — are relative
    to the directory that holds the wiki, so they are rebased onto the repo root
    before asking git, which reports paths from the root.

    `against` is the commit the wiki should describe — a change map's
    merge-base — instead of HEAD. When the wiki was ingested before it, only
    the gap up to it counts. When the wiki was ingested on the branch after
    it, the wiki is judged against HEAD as usual and `includes_branch` says it
    may already describe some of the branch's changes.
    """
    base_dir = root / wiki_dir
    if not (base_dir / "wiki/config.yaml").is_file():
        return {"state": "missing"}
    state_path = base_dir / ".code-wiki/state.json"
    base, basis = None, None
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"state": "unknown", "reason": "unreadable .code-wiki/state.json"}
        if not isinstance(state, dict) or state.get("version") != WIKI_STATE_VERSION:
            return {"state": "unknown", "reason": "unsupported code-wiki state version"}
        base, basis = state.get("last_ingested_sha"), "state"
    else:
        # Same inference code-wiki's bootstrap uses, without writing state.json.
        out = _git(root, "log", "-1", "--format=%H", "--", _under(wiki_dir, "wiki/"))
        base, basis = (out.strip() or None) if out else None, "inferred"
    if not base:
        return {"state": "unknown", "reason": "no ingest commit recorded or inferable"}
    if not _is_commit(root, base):
        return {"state": "unknown", "reason": f"ingest commit {base} not found"}
    roots = _source_roots(base_dir)
    scope = [_under(wiki_dir, r) for r in roots] if roots else [wiki_dir]
    target, includes_branch = "HEAD", False
    if against:
        if _is_ancestor(root, base, against):
            target = against
        elif _is_ancestor(root, against, base):
            includes_branch = True
    changed = _changed(root, base, scope, list(ALWAYS_EXCLUDED) + wiki_excludes([wiki_dir]),
                       to=target)
    if changed is None:
        return {"state": "unknown", "reason": "git diff failed"}
    result = _changes_result(changed, base)
    if against:
        result["against"] = target
    if includes_branch:
        result["includes_branch"] = True
    result["basis"] = basis
    result["source_roots"] = roots  # None means "the wiki's whole directory" (conservative)
    return result


def wiki_candidates(root: Path) -> list[str]:
    """Directories below the root holding a committed code-wiki (`<dir>/wiki/config.yaml`)."""
    out = _git(root, "ls-files", "--", ":(glob)**/wiki/config.yaml") or ""
    dirs = []
    for f in out.splitlines():
        d = f[: -len("/wiki/config.yaml")] if f.endswith("/wiki/config.yaml") else ""
        if d and d not in dirs:
            dirs.append(d)
    return dirs


def wikis_status(root: Path, wiki_dirs: list[str] | None = None,
                 against: str | None = None) -> tuple[dict, list[dict]]:
    """(combined, per-wiki). With one wiki the combined state is that wiki's own."""
    dirs = wiki_dirs or [DEFAULT_WIKI]
    each = [{"dir": d, **wiki_status(root, d, against)} for d in dirs]
    if len(each) == 1:
        combined = {k: v for k, v in each[0].items() if k != "dir"}
    else:
        worst = max(each, key=lambda w: WIKI_RANK[w["state"]])["state"]
        combined = {"state": worst}
        if any(w.get("includes_branch") for w in each):
            combined["includes_branch"] = True
        if worst == "stale":
            combined["changed"] = sum(w.get("changed", 0) for w in each
                                      if w["state"] == "stale")
        elif worst != "fresh":
            combined["reason"] = "; ".join(
                f"{w['dir']}: {w['state']}" + (f" ({w['reason']})" if w.get("reason") else "")
                for w in each if w["state"] != "fresh")
    if not wiki_dirs and combined["state"] == "missing":
        candidates = wiki_candidates(root)
        if candidates:
            combined["candidates"] = candidates
    return combined, each


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "record"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True, type=Path)
        p.add_argument("--map", required=True, type=Path)
        if name == "record":
            p.add_argument("--scope", action="append", default=[])
        else:
            p.add_argument("--wiki", action="append", default=[], metavar="DIR",
                           help="directory holding a code-wiki, relative to --root; "
                                "repeatable (default: the repo root)")
            p.add_argument("--against", metavar="COMMIT",
                           help="judge the wiki against this commit instead of HEAD")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    map_path = (args.map if args.map.is_absolute() else root / args.map).resolve()
    if args.cmd == "record":
        out = record(root, map_path, args.scope)
    else:
        given = normalize_wiki_dirs(root, args.wiki) if args.wiki else None
        out = check(root, map_path, given, args.against)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
