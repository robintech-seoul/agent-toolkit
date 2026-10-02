#!/usr/bin/env python3
"""Which answer engine to use, and how to run it headless and read-only.

    engines.py choose [--engine claude|codex] [--reset]
    engines.py set-default claude|codex

`choose` prints {"engine", "ask", "installed", "default", "reason"}. When
"ask" is true, both engines are installed and no default is saved: the open
skill asks the user, then calls `set-default`. `--engine` is a one-run
override and is never saved.

The default lives per user, not per repo — which CLI someone uses is their
preference, not the project's:
    $XDG_CONFIG_HOME/arch-explorer/config.json  (else ~/.config/…)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ENGINES = ("claude", "codex")
CONFIG_VERSION = 1

# ---------------------------------------------------------------- default

def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "arch-explorer" / "config.json"


def load_default() -> str | None:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    engine = data.get("default_engine") if isinstance(data, dict) else None
    return engine if engine in ENGINES else None


def save_default(engine: str) -> None:
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CONFIG_VERSION, "default_engine": engine},
                               indent=2) + "\n", encoding="utf-8")


def reset_default() -> None:
    try:
        config_path().unlink()
    except FileNotFoundError:
        pass


def installed() -> list[str]:
    return [e for e in ENGINES if shutil.which(e)]


def choose(explicit: str | None = None, reset: bool = False) -> dict:
    if reset:
        reset_default()
    have = installed()
    default = load_default()
    out = {"engine": None, "ask": False, "installed": have, "default": default}
    if explicit:
        if explicit not in have:
            return {**out, "reason": f"--engine={explicit} is not installed"}
        return {**out, "engine": explicit, "reason": "--engine (this run only)"}
    if default in have:
        return {**out, "engine": default, "reason": "saved default"}
    if not have:
        return {**out, "reason": "neither claude nor codex is installed"}
    if default:
        return {**out, "engine": have[0],
                "reason": f"saved default {default} is not installed; using {have[0]}"}
    if len(have) == 2:
        return {**out, "ask": True, "reason": "both installed, no saved default"}
    return {**out, "engine": have[0], "reason": "only one installed"}


# ---------------------------------------------------------------- adapters
#
# An adapter turns one question into a subprocess and its stdout lines into
# normalized events:
#   {"type": "session", "id"}          engine session id, for resuming
#   {"type": "delta",   "text"}        streamed answer text (claude)
#   {"type": "note",    "text"}        interim message (codex preamble)
#   {"type": "tool",    "name", "detail"}
#   {"type": "final",   "text"}        the answer
#   {"type": "error",   "message"}
#   {"type": "resume_failed", "message"}  the session to resume does not exist
# Every run ends in exactly one "final", "error" or "resume_failed" — `finish`
# supplies the error when the process exits without one, so an empty answer
# never looks like a successful one.

READ_ONLY_TOOLS = "Read,Grep,Glob"
# A change map's chat also reads the code before the change and the hunks, so
# it gets three read-only git commands. Anything else is refused by dontAsk
# (redirects included); git's own file-writing option is refused explicitly.
GIT_WRITE_DENY = ("Bash(git *--output*)",)
DIFF_CHAT_TOOLS = "Read,Grep,Glob,Bash"
DIFF_CHAT_ALLOWED = (["Read", "Grep", "Glob"]
                     + [f"Bash(git {c})" for c in ("show", "diff", "log")]
                     + [f"Bash(git {c} *)" for c in ("show", "diff", "log")])
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


def child_env() -> dict:
    """The parent may be a Claude Code session; the child must not think it is nested."""
    return {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}


def _short(value, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _Adapter:
    def __init__(self, root: Path | None = None, diff: bool = False) -> None:
        self.ended = False
        self.diff = diff
        # Tool details name files by absolute path; show them relative to the repo.
        self.prefixes = sorted({f"{r}{os.sep}" for r in
                                ([str(root), str(Path(root).resolve())] if root else [])},
                               key=len, reverse=True)

    def _detail(self, value) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for prefix in self.prefixes:
            text = text.replace(prefix, "")
        return _short(text)

    def _end(self, event: dict) -> list[dict]:
        if self.ended:
            return []
        self.ended = True
        return [event]

    def feed(self, line: str) -> list[dict]:
        line = line.strip()
        if not line:
            return []
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return []
        return self._parse(data) if isinstance(data, dict) else []

    def finish(self, returncode: int | None, stderr: str) -> list[dict]:
        if self.ended:
            return []
        tail = stderr.strip().splitlines()[-5:]
        detail = ("\n" + "\n".join(tail)) if tail else ""
        return self._end({"type": "error",
                          "message": f"{self.name} exited with code {returncode} "
                                     f"without an answer{detail}"})


class ClaudeAdapter(_Adapter):
    name = "claude"

    def argv(self, rules: str, session: str | None, root: Path, fork: bool = False) -> list[str]:
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages",
               "--strict-mcp-config"]  # --tools alone leaves MCP tools available
        if self.diff:
            cmd += ["--tools", DIFF_CHAT_TOOLS, "--permission-mode", "dontAsk",
                    "--allowedTools", *DIFF_CHAT_ALLOWED,
                    "--disallowedTools", *GIT_WRITE_DENY]
        else:
            cmd += ["--tools", READ_ONLY_TOOLS]
        cmd += ["--append-system-prompt", rules]
        if session:
            cmd += ["--resume", session]
            if fork:  # a new session from the build's; the build session stays as it was
                cmd.append("--fork-session")
        return cmd

    def stdin(self, rules: str, prompt: str, session: str | None) -> str:
        return prompt

    def _parse(self, d: dict) -> list[dict]:
        t = d.get("type")
        if t == "system" and d.get("subtype") == "init" and d.get("session_id"):
            return [{"type": "session", "id": d["session_id"]}]
        if t == "stream_event":
            delta = (d.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [{"type": "delta", "text": delta["text"]}]
            return []
        if t == "assistant":
            events = []
            for block in (d.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    inp = block.get("input") or {}
                    detail = (inp.get("file_path") or inp.get("pattern")
                              or inp.get("path") or inp)
                    events.append({"type": "tool", "name": block.get("name", "?"),
                                   "detail": self._detail(detail)})
            return events
        if t == "result":
            errors = [str(e) for e in d.get("errors") or []]
            if (d.get("is_error") and not d.get("num_turns")
                    and any("No conversation found" in e for e in errors)):
                return self._end({"type": "resume_failed", "message": _short(errors[0], 500)})
            events = []
            if d.get("session_id"):
                events.append({"type": "session", "id": d["session_id"]})
            if d.get("is_error") or d.get("subtype") != "success":
                msg = d.get("result") or d.get("subtype") or "unknown error"
                return events + self._end({"type": "error", "message": _short(msg, 2000)})
            return events + self._end({"type": "final", "text": d.get("result") or ""})
        return []


class CodexAdapter(_Adapter):
    name = "codex"

    def __init__(self, root: Path | None = None, diff: bool = False) -> None:
        super().__init__(root, diff)
        self.last_message = None

    def argv(self, rules: str, session: str | None, root: Path, fork: bool = False) -> list[str]:
        # The server never asks codex to fork: only a claude build leaves a session.
        if session:
            # `exec resume` has no --sandbox; the config override applies it.
            return ["codex", "exec", "resume", session, "--json",
                    "-c", 'sandbox_mode="read-only"', "-"]
        return ["codex", "exec", "--json", "--sandbox", "read-only",
                "-C", str(root), "-"]

    def stdin(self, rules: str, prompt: str, session: str | None) -> str:
        # codex has no system-prompt flag; the first turn carries the rules.
        return prompt if session else f"{rules}\n\n---\n\n{prompt}"

    def _parse(self, d: dict) -> list[dict]:
        t = d.get("type")
        if t == "thread.started" and d.get("thread_id"):
            return [{"type": "session", "id": d["thread_id"]}]
        item = d.get("item") or {}
        if t == "item.started" and item.get("type") == "command_execution":
            return [{"type": "tool", "name": "shell",
                     "detail": self._detail(item.get("command", ""))}]
        if t == "item.completed" and item.get("type") == "agent_message":
            # Only turn.completed tells which message was the last, so each one
            # shows as progress now and the last becomes the answer.
            self.last_message = item.get("text") or ""
            return [{"type": "note", "text": self.last_message}]
        if t == "turn.completed":
            if self.last_message is None:
                return self._end({"type": "error", "message": "codex finished without a message"})
            return self._end({"type": "final", "text": self.last_message})
        if t == "turn.failed":
            err = (d.get("error") or {}).get("message") or "turn failed"
            return self._end({"type": "error", "message": _short(err, 2000)})
        if t == "error":
            return self._end({"type": "error", "message": _short(d.get("message") or d, 2000)})
        return []


def adapter(engine: str, root: Path | None = None, diff: bool = False) -> _Adapter:
    return {"claude": ClaudeAdapter, "codex": CodexAdapter}[engine](root, diff)


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("choose")
    p.add_argument("--engine", choices=ENGINES)
    p.add_argument("--reset", action="store_true")
    p = sub.add_parser("set-default")
    p.add_argument("engine", choices=ENGINES)
    args = ap.parse_args(argv)
    if args.cmd == "set-default":
        save_default(args.engine)
        out = {"default": args.engine, "path": str(config_path())}
    else:
        out = choose(args.engine, args.reset)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
