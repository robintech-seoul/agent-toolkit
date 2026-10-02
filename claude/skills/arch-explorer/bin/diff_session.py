#!/usr/bin/env python3
"""Resolve a change map's range, build it headless, and record its sidecar.

    diff_session.py resolve --root <repo> [head [base]] [--include-uncommitted]
                            [--save-to[=<path>]] [--cwd <dir>]
    diff_session.py build   --range-file <file> [--timeout SEC] [--force]
    diff_session.py record  --range-file <file>

`resolve` is /arch-explorer:diff §1 as a program. It prints one of
    {"ask": true, "reason", "choices"}     a question for the user; nothing decided
    {"empty": true, …range}                no changes between merge-base and after
    {…range, "range_file"}                 the range, also saved to range_file
and never touches the user's index or work tree: a work-tree snapshot goes
through a copy of the index (status.snapshot_tree).

`build` runs `claude -p` headless in the repo root with diff §2–§7 and the
resolved range, under `--permission-mode dontAsk` and an allow-list. It checks
that nothing but the map changed in the work tree, then writes the sidecar
with the session id, so the chat can fork that session (see chat_server.py).
It prints {"out", "sidecar", "session", "log", "report", "reused"} or
{"error", "log"}. With the same range already built and a session recorded,
it reuses that build unless `--force`.

`record` writes the sidecar for a map built in the user's own session
(`session: null`): open can then recognise it, but the chat has no build
context to fork.

The sidecar sits next to the map: `<stem>.arch-explorer.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engines  # noqa: E402
import status  # noqa: E402
from status import _git, _rel, _rev  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RANGE_VERSION = 1
DEFAULT_BASES = (("main", "refs/heads/main", "refs/remotes/origin/main"),
                 ("master", "refs/heads/master", "refs/remotes/origin/master"))
CHANGES_DIR = "docs/architecture/changes"
BUILD_TIMEOUT = 1800

# The build reads git and runs check scripts; it writes only the map. The
# allow-list cannot confine Write or python3 to one path, so `build` checks the
# work tree afterwards instead.
GIT_READ = ("show", "diff", "log", "status", "rev-parse", "ls-files", "ls-tree",
            "cat-file", "merge-base", "grep", "blame", "rev-list", "name-rev")
BUILD_TOOLS = "Read,Grep,Glob,Bash,Write,Edit,Agent"
BUILD_ALLOWED = (["Read", "Grep", "Glob", "Agent", "Write", "Edit"]
                 + [f"Bash(git {c})" for c in GIT_READ]
                 + [f"Bash(git {c} *)" for c in GIT_READ]
                 + [f"Bash({c} *)" for c in ("python3", "ls", "wc", "head", "tail")])


def runtime_dir() -> Path:
    return Path(tempfile.gettempdir()) / "arch-explorer"


def _key(root: Path, out: Path) -> str:
    return hashlib.sha1(f"{root}\n{out}".encode()).hexdigest()[:16]


def build_log_path(root: Path, out: Path) -> Path:
    return runtime_dir() / f"build-{_key(root, out)}.log"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- resolve

def _slug(ref: str) -> str:
    return ref.replace("/", "-")


def output_path(cwd: Path, head: str, base: str, uncommitted: bool,
                save_to: str | None) -> Path:
    """diff §6: where the map goes. `save_to` None = flag absent, "" = flag alone."""
    name = f"{_slug(head)}{'-uncommitted' if uncommitted else ''}-vs-{_slug(base)}.html"
    if save_to is None:
        return (cwd / name).resolve()
    if save_to == "":
        return (cwd / CHANGES_DIR / name).resolve()
    p = Path(save_to)
    p = p if p.is_absolute() else cwd / p
    return (p if p.suffix == ".html" else p / name).resolve()


def _ask(reason: str, choices: list[str] | None = None) -> dict:
    return {"ask": True, "reason": reason, "choices": choices or []}


def resolve(root: Path, head: str | None = None, base: str | None = None,
            include_uncommitted: bool = False, save_to: str | None = None,
            cwd: Path | None = None) -> dict:
    cwd = cwd or Path.cwd()
    current = (_git(root, "branch", "--show-current") or "").strip()
    notes: list[str] = []

    # 1. head
    if head is None:
        if not current:
            return _ask("HEAD is detached: which branch should be explained?")
        head = current
    head_sha = _rev(root, head)
    if head_sha is None:
        return _ask(f"`{head}` does not resolve to a commit.")
    is_current = bool(current) and head == current
    if include_uncommitted and not is_current:
        return _ask(f"--include-uncommitted applies only to the current branch "
                    f"(`{current or 'detached HEAD'}`), not `{head}`.",
                    [f"compare `{head}` without uncommitted changes",
                     f"compare the current branch `{current}` with them"] if current else None)

    # 2. base
    if base is None:
        if head in ("main", "master"):
            choices = ["name a base ref to compare against"]
            if include_uncommitted:
                choices.append("only the uncommitted changes (base = head)")
            return _ask(f"`{head}` is itself a default branch: compare it against what?", choices)
        for name, local, remote in DEFAULT_BASES:
            l_sha, r_sha = _rev(root, local), _rev(root, remote)
            if l_sha or r_sha:
                base, base_ref = name, (local if l_sha else remote)
                if l_sha and r_sha and l_sha != r_sha:
                    notes.append(f"local `{name}` and `origin/{name}` point at different "
                                 f"commits; used local `{name}`.")
                break
        else:
            return _ask("Neither `main` nor `master` exists: which base should be compared against?")
    else:
        base_ref = base
    base_sha = _rev(root, base_ref)
    if base_sha is None:
        return _ask(f"`{base}` does not resolve to a commit.")
    if base_sha == head_sha and not include_uncommitted:
        return _ask(f"`{head}` and `{base}` are the same commit: which base did you mean?")
    mb = (_git(root, "merge-base", base_sha, head_sha) or "").strip()
    if not mb:
        return _ask(f"`{head}` and `{base}` share no history: which base did you mean?")

    # 3. after side, and the map's own paths (kept out of the snapshot)
    out = output_path(cwd, head, base, include_uncommitted, save_to)
    sidecar = status.diff_sidecar_path(out)
    own = [p for p in (_rel(root, out), _rel(root, sidecar)) if p]
    porcelain = _git(root, "status", "--porcelain", "--untracked-files=no") or ""
    if include_uncommitted:
        after = status.snapshot_tree(root, own)
        if after is None:
            return {"error": "could not snapshot the work tree"}
        n = len((_git(root, "diff", "--name-only", head_sha, after) or "").split())
        notes.append(f"{n} file(s) come from uncommitted work.")
    else:
        after = head_sha
        if is_current and (_git(root, "status", "--porcelain", "--", ".",
                                *[f":(exclude,literal){p}" for p in own]) or "").strip():
            notes.append("Uncommitted changes are not part of the comparison; "
                         "--include-uncommitted would include them.")
    if out.exists():
        notes.append(f"`{out}` already exists and will be overwritten.")

    log = _git(root, "log", "--reverse", "--format=%h%x09%s", f"{mb}..{head_sha}") or ""
    commits = [dict(zip(("sha", "subject"), line.split("\t", 1)))
               for line in log.splitlines() if line]
    files = [f for f in (_git(root, "diff", "--name-only", mb, after) or "").splitlines() if f]
    # The after side is readable in the work tree only when the work tree is it.
    read_from = ("worktree" if is_current and (include_uncommitted or not porcelain.strip())
                 else "git")
    rng = {
        "version": RANGE_VERSION, "root": str(root),
        "head": head, "head_sha": head_sha, "current": is_current,
        "base": base, "base_ref": base_ref, "base_sha": base_sha,
        "mb": mb, "after": after, "uncommitted": include_uncommitted,
        "read_from": read_from, "commits": commits, "files": len(files),
        "notes": notes, "out": str(out), "sidecar": str(sidecar),
        "build_log": str(build_log_path(root, out)),
    }
    if not files:
        return {"empty": True, **rng}
    path = runtime_dir() / "ranges" / f"{_key(root, out)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rng, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {**rng, "range_file": str(path)}


def load_range(path: Path) -> dict:
    rng = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rng, dict) or rng.get("version") != RANGE_VERSION:
        raise SystemExit(f"{path}: not a range file from `diff_session.py resolve`")
    return rng


# ---------------------------------------------------------------- record

def record(rng: dict, session: str | None = None, engine: str | None = None) -> dict:
    meta = {
        "version": status.DIFF_SIDECAR_VERSION, "kind": "diff",
        "head": rng["head"], "head_sha": rng["head_sha"], "base": rng["base"],
        "mb": rng["mb"], "after": rng["after"], "uncommitted": rng["uncommitted"],
        "engine": engine, "session": session, "built_at": _now(),
    }
    Path(rng["sidecar"]).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


# ---------------------------------------------------------------- build

def build_prompt(rng: dict, read_at: str) -> str:
    """What the headless session is told. §1 is done: it gets the range instead."""
    shown = {k: rng[k] for k in ("head", "head_sha", "base", "base_sha", "mb", "after",
                                 "uncommitted", "commits")}
    after = (f"`{read_at}` — the work tree"
             + (" (it includes the uncommitted work)" if rng["uncommitted"] else "")
             if read_at == rng["root"] else
             f"`{read_at}` — a worktree of head made for this build; do not add or "
             f"remove worktrees")
    return f"""You are building an arch-explorer change map, headless. Nobody can answer questions.

Read `{PLUGIN_ROOT}/skills/diff/SKILL.md` and follow §2–§7 for the range below,
reading `{PLUGIN_ROOT}/skills/build/SKILL.md` where it says to. §0 and §1 are
already done by the program: do not resolve refs, do not take a snapshot, do not
check out anything, do not ask.

RANGE: {json.dumps(shown, ensure_ascii=False)}
OUTPUT: {rng["out"]}

- Code before the change: `git show {rng["mb"]}:<path>`.
- Code after it: {after}.
- Diffs: `git diff {rng["mb"]} {rng["after"]}`.
- Write the map to exactly OUTPUT. Write no other file anywhere: run any check
  script inline (`python3 - <<'EOF' … EOF`), and write no sidecar or README.
- If you cannot finish without asking someone, stop and make your final message
  `CANNOT: <reason>`.
- Your final message is the §7 report.

Questions about this change will later be asked in forks of this session, so
the analysis you do here is what they will answer from.
"""


def build_argv(add_dir: str | None) -> list[str]:
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
           "--strict-mcp-config", "--permission-mode", "dontAsk",
           "--tools", BUILD_TOOLS, "--allowedTools", *BUILD_ALLOWED,
           "--disallowedTools", *engines.GIT_WRITE_DENY]
    if add_dir:
        cmd += ["--add-dir", add_dir]
    return cmd


def _changed_between(root: Path, a: str, b: str) -> list[str]:
    return [f for f in (_git(root, "diff", "--name-only", a, b) or "").splitlines() if f]


def _log_line(event: dict) -> str | None:
    t = event.get("type")
    if t == "assistant":
        sub = " (subagent)" if event.get("parent_tool_use_id") else ""
        parts = []
        for b in (event.get("message") or {}).get("content") or []:
            if b.get("type") == "tool_use":
                inp = b.get("input") or {}
                detail = (inp.get("file_path") or inp.get("command") or inp.get("pattern")
                          or inp.get("description") or "")
                parts.append(f"tool{sub} {b.get('name')}: {str(detail)[:160]}")
            elif b.get("type") == "text" and b.get("text", "").strip():
                parts.append(f"text{sub}: {b['text'].strip().splitlines()[0][:160]}")
        return "\n".join(parts) or None
    if t == "result":
        return f"result {event.get('subtype')} is_error={event.get('is_error')}"
    return None


def build(rng: dict, timeout: int = BUILD_TIMEOUT, force: bool = False) -> dict:
    root = Path(rng["root"])
    out, sidecar = Path(rng["out"]), Path(rng["sidecar"])
    log_path = build_log_path(root, out)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    old = status.load_diff_sidecar(out)
    if (not force and old and out.is_file() and old.get("session")
            and all(old.get(k) == rng[k] for k in ("head_sha", "mb", "after"))):
        return {"out": str(out), "sidecar": str(sidecar), "session": old["session"],
                "log": str(log_path), "report": None, "reused": True}
    if not shutil.which("claude"):
        return {"error": "claude is not installed", "log": str(log_path)}

    own = [p for p in (_rel(root, out), _rel(root, sidecar)) if p]
    before = status.snapshot_tree(root, own)
    if before is None:
        return {"error": "could not snapshot the work tree", "log": str(log_path)}
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()

    worktree = None
    if rng["read_from"] == "git":
        worktree = Path(tempfile.mkdtemp(prefix="archx-wt-")).resolve()
        worktree.rmdir()
        if _git(root, "worktree", "add", "--detach", str(worktree), rng["head_sha"]) is None:
            return {"error": f"could not add a worktree for {rng['head']}", "log": str(log_path)}
    try:
        result = _run_build(root, rng, str(worktree) if worktree else str(root),
                            str(worktree) if worktree else None, log_path, timeout)
    finally:
        if worktree:
            _git(root, "worktree", "remove", "--force", str(worktree))
            shutil.rmtree(worktree, ignore_errors=True)

    fail = lambda msg: {"error": msg, "log": str(log_path), "session": result.get("session")}  # noqa: E731
    if result.get("error"):
        return fail(result["error"])
    after = status.snapshot_tree(root, own)
    touched = _changed_between(root, before, after) if after else ["<snapshot failed>"]
    if touched:
        return fail("the build changed files other than the map: " + ", ".join(touched[:10])
                    + " — review them; no sidecar was written")
    if not out.is_file() or out.stat().st_mtime < started:
        return fail(f"the build finished without writing {out}")
    record(rng, session=result["session"], engine="claude")
    return {"out": str(out), "sidecar": str(sidecar), "session": result["session"],
            "log": str(log_path), "report": result["report"], "reused": False}


def _run_build(root: Path, rng: dict, read_at: str, add_dir: str | None,
               log_path: Path, timeout: int) -> dict:
    try:
        proc = subprocess.Popen(
            build_argv(add_dir), cwd=str(root), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=engines.child_env(),
            start_new_session=True)
    except OSError as e:
        return {"error": f"cannot start claude: {e}"}

    lines: queue.Queue = queue.Queue()
    stderr: list[str] = []

    def pump_out():
        try:
            for line in proc.stdout:
                lines.put(line)
        except (ValueError, OSError):
            pass
        lines.put(None)

    def pump_err():
        try:
            for line in proc.stderr:
                stderr.append(line)
                del stderr[:-50]
        except (ValueError, OSError):
            pass

    threading.Thread(target=pump_out, daemon=True).start()
    threading.Thread(target=pump_err, daemon=True).start()
    try:
        proc.stdin.write(build_prompt(rng, read_at))
        proc.stdin.close()
    except OSError:
        pass

    session = None
    last = None  # Background subagents can produce more than one result; the last one counts.
    deadline = time.monotonic() + timeout
    timed_out = False
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"{_now()} build {rng['head']} vs {rng['base']} → {rng['out']}\n")
        while True:
            try:
                line = lines.get(timeout=max(0.1, min(5, deadline - time.monotonic())))
            except queue.Empty:
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                continue
            if line is None:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if (event.get("type") == "system" and event.get("subtype") == "init"
                    and session is None and event.get("session_id")):
                session = event["session_id"]
            if event.get("type") == "result":
                last = event
            text = _log_line(event)
            if text:
                log.write(text + "\n")
                log.flush()
        if timed_out or proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        tail = "".join(stderr).strip()
        if tail:
            log.write("stderr: " + tail[-2000:] + "\n")

    if timed_out:
        return {"error": f"the build timed out after {timeout}s", "session": session}
    if last is None:
        return {"error": f"claude exited with code {proc.returncode} without a result"
                + (f": {tail[-500:]}" if tail else ""), "session": session}
    report = last.get("result") or ""
    if last.get("is_error") or last.get("subtype") != "success":
        return {"error": f"the build failed: {report or last.get('subtype')}", "session": session}
    cannot = next((ln.strip() for ln in report.splitlines() if ln.strip().startswith("CANNOT:")),
                  None)
    if cannot:
        return {"error": cannot, "session": session}
    if not session:
        session = last.get("session_id")
    if not session:
        return {"error": "claude reported no session id"}
    return {"session": session, "report": report}


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("resolve")
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("refs", nargs="*", metavar="head [base]")
    p.add_argument("--include-uncommitted", action="store_true")
    p.add_argument("--save-to", nargs="?", const="", default=None)
    p.add_argument("--cwd", type=Path, default=None)
    for name in ("build", "record"):
        p = sub.add_parser(name)
        p.add_argument("--range-file", required=True, type=Path)
        if name == "build":
            p.add_argument("--timeout", type=int, default=BUILD_TIMEOUT)
            p.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "resolve":
        if len(args.refs) > 2:
            ap.error("resolve takes at most two refs: head and base")
        refs = args.refs + [None] * (2 - len(args.refs))
        out = resolve(args.root.resolve(), refs[0], refs[1], args.include_uncommitted,
                      args.save_to, (args.cwd or Path.cwd()).resolve())
    elif args.cmd == "record":
        out = record(load_range(args.range_file))
    else:
        out = build(load_range(args.range_file), args.timeout, args.force)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    sys.exit(main())
