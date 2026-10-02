"""Shared fixtures: throwaway git repos and fake engine CLIs on PATH."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))


class Repo:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout

    def write(self, rel: str, text: str = "x\n") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def commit(self, msg: str = "c") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, "--allow-empty")
        return self.git("rev-parse", "HEAD").strip()

    def cleanup(self) -> None:
        self._tmp.cleanup()


FAKE_ENGINE = r'''#!/usr/bin/env python3
# Fake {name}: records argv and stdin, then behaves per $FAKE_MODE.
import json, os, sys, time
log = os.environ.get("FAKE_LOG")
data = sys.stdin.read()
if log:
    with open(log, "a") as f:
        f.write(json.dumps({{"argv": sys.argv[1:], "stdin": data, "cwd": os.getcwd()}}) + "\n")
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "sleep":
    time.sleep(60)
if mode == "fail":
    sys.stderr.write("boom: auth expired\n")
    sys.exit(3)
if mode == "noresume" and "--resume" in sys.argv:
    sid = sys.argv[sys.argv.index("--resume") + 1]
    sys.stderr.write("No conversation found with session ID: " + sid + "\n")
    print(json.dumps({{"type": "result", "subtype": "error_during_execution", "is_error": True, "num_turns": 0, "session_id": "sess-new", "errors": ["No conversation found with session ID: " + sid]}}), flush=True)
    sys.exit(1)
if "{name}" == "claude":
    sid = "sess-fork-" + str(os.getpid()) if "--fork-session" in sys.argv else "sess-claude-1"
    print(json.dumps({{"type": "system", "subtype": "init", "session_id": sid}}), flush=True)
    print(json.dumps({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": "Read", "input": {{"file_path": "wiki/src/index.md"}}}}]}}}}), flush=True)
    for part in ["See ", "`src/a.py:3`."]:
        print(json.dumps({{"type": "stream_event", "event": {{"type": "content_block_delta", "delta": {{"type": "text_delta", "text": part}}}}}}), flush=True)
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "result": "See `src/a.py:3`."}}), flush=True)
else:
    print(json.dumps({{"type": "thread.started", "thread_id": "thread-codex-1"}}), flush=True)
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": "Reading."}}}}), flush=True)
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": "Answer."}}}}), flush=True)
    print(json.dumps({{"type": "turn.completed", "usage": {{}}}}), flush=True)
'''


def fake_bin(names: tuple[str, ...] = ("claude", "codex")) -> tempfile.TemporaryDirectory:
    """A directory holding fake engines; put it first on PATH."""
    tmp = tempfile.TemporaryDirectory()
    for name in names:
        p = Path(tmp.name) / name
        p.write_text(FAKE_ENGINE.format(name=name).replace(
            "#!/usr/bin/env python3", f"#!{sys.executable}", 1), encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return tmp


def path_with(dir_: str, only: bool = False) -> str:
    """PATH with `dir_` first; with only=True, just dir_ plus git's directory."""
    if only:
        git_dir = os.path.dirname(subprocess.run(["which", "git"], capture_output=True,
                                                 text=True).stdout.strip())
        return os.pathsep.join([dir_, git_dir, "/usr/bin", "/bin"])
    return os.pathsep.join([dir_, os.environ.get("PATH", "")])
