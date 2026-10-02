#!/usr/bin/env python3
"""Serve an architecture map with a chat panel that answers from the code-wiki.

    chat_server.py launch --root <repo> --map <index.html> --engine claude|codex [--wiki <dir> …]
                          [--port N] [--no-open] [--timeout SEC]
    chat_server.py stop   --root <repo> --map <index.html>
    chat_server.py serve  …same as launch…      (foreground; launch runs this)

`launch` reuses a server already running for the same repo and map, starts
one detached otherwise, waits until it answers, opens the browser, and prints
{"url", "pid", "port", "engine", "reused", "log"} as JSON.

The map file on disk is never modified: the panel (`assets/chat-panel.html`)
is inserted before `</body>` as the page is served. Questions run the chosen
engine headless and read-only (see engines.py) in the repo root.

A change map (one with a `<stem>.arch-explorer.json` sidecar, see
diff_session.py) is answered with `answer-rules-diff.md` added to the rules
and the change range in every prompt. When its sidecar records the session
that built it and the engine is claude, each conversation starts as a fork of
that session (`--resume <build> --fork-session`), so it answers from the
build's analysis; the build session itself is never changed. If that session
is gone, the conversation falls back to answering without it, and says so.

Security: binds 127.0.0.1 only; rejects foreign Host headers (DNS rebinding);
every request needs the per-launch token, first as `/?t=<token>`, then as an
HttpOnly SameSite=Strict cookie; POSTs must come from the server's own Origin.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engines  # noqa: E402
import status  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PANEL_PATH = PLUGIN_ROOT / "assets" / "chat-panel.html"
RULES_PATH = PLUGIN_ROOT / "assets" / "answer-rules.md"
RULES_DIFF_PATH = PLUGIN_ROOT / "assets" / "answer-rules-diff.md"

MAX_BODY = 256 * 1024
MAX_QUESTION = 8000
MAX_CONTEXT = 6000
PING_SECONDS = 5
CONV_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------- runtime file

def runtime_dir() -> Path:
    return Path(tempfile.gettempdir()) / "arch-explorer"


def runtime_file(root: Path, map_path: Path) -> Path:
    key = hashlib.sha1(f"{root}\n{map_path}".encode()).hexdigest()[:16]
    return runtime_dir() / f"{key}.json"


def read_runtime(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def health(port: int, token: str, timeout: float = 1.0) -> dict | None:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/health",
                                 headers={"X-Archx-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------- page

def inject(html: str, panel: str) -> str:
    """Insert the panel before the last </body>, or append it when there is none."""
    i = html.lower().rfind("</body>")
    return html[:i] + panel + html[i:] if i >= 0 else html + panel


def format_context(ctx) -> str:
    """The map context the panel sent, as a bounded plain-text block."""
    if not isinstance(ctx, dict) or not ctx:
        return ""
    lines = ["[map context]"]
    view = ctx.get("view") if isinstance(ctx.get("view"), dict) else None
    if view:
        lines.append(f"current layer: {view.get('id')} — {view.get('title') or ''}".rstrip(" —"))
        if view.get("hint"):
            lines.append(f"layer hint: {view['hint']}")
    node = ctx.get("node") if isinstance(ctx.get("node"), dict) else None
    if node:
        lines.append(f"selected box: {node.get('id')} — {node.get('title') or ''}".rstrip(" —")
                     + _mark(node))
        for ln in (node.get("lines") or [])[:6]:
            lines.append(f"  {ln}")
    block = ctx.get("block") if isinstance(ctx.get("block"), dict) else None
    if block:
        lines.append(f"change block of the selected box: {block.get('summary') or ''}")
        for title in (block.get("features") or [])[:8]:
            lines.append(f"  - {title}")
    changes = ctx.get("changes") if isinstance(ctx.get("changes"), dict) else None
    if changes:
        marked = ([f"box {n.get('id')}{_mark(n)}" for n in changes.get("nodes") or []
                   if isinstance(n, dict)]
                  + [f"arrow {e.get('from')} → {e.get('to')}{_mark(e)}"
                     for e in changes.get("edges") or [] if isinstance(e, dict)])
        if marked:
            lines.append("changed on this layer: " + ", ".join(marked[:30]))
    ifaces = ctx.get("ifaces") if isinstance(ctx.get("ifaces"), list) else []
    if ifaces:
        lines.append("interfaces on this layer:")
        for f in ifaces[:30]:
            if not isinstance(f, dict):
                continue
            lines.append(f"- {f.get('title')} ({f.get('from')} → {f.get('to')}){_mark(f)}")
            for it in (f.get("items") or [])[:4]:
                if isinstance(it, dict):
                    lines.append(f"    {it.get('sig', '')}  @ {it.get('ref', '')}")
    text = "\n".join(str(x) for x in lines)
    return text if len(text) <= MAX_CONTEXT else text[:MAX_CONTEXT] + "\n…(truncated)"


def _mark(item: dict) -> str:
    """` [added]` for an element the change map marks, else nothing."""
    change = item.get("change")
    return f" [{change}]" if change in ("added", "modified", "removed") else ""


def _wiki_status_line(wiki: dict, where: str = "") -> str | None:
    label = f"{where}: " if where else ""
    if wiki.get("includes_branch"):
        return (f"[wiki status] {label}the wiki was updated on this branch, after the "
                f"merge-base: it may already describe some of the branch's changes.")
    if wiki.get("state") == "stale":
        return (f"[wiki status] {label}the wiki does not reflect {wiki.get('changed')} "
                f"file(s) changed since {str(wiki.get('sha'))[:10]}.")
    if wiki.get("state") != "fresh":
        return f"[wiki status] {label}{wiki.get('state')}: {wiki.get('reason', '')}"
    return None


def format_range(diff: dict, head_now: str | None, build_context: bool) -> str:
    """The change map's range, and where to read each side of it."""
    head, base, mb, after = diff.get("head"), diff.get("base"), diff.get("mb"), diff.get("after")
    lines = [f"[change range] this map shows what `{head}` changed against `{base}`.",
             f"merge-base: {mb}",
             f"after: {after}" + (" (a snapshot of the work tree, uncommitted work included)"
                                  if diff.get("uncommitted") else " (head's commit)"),
             f"code before the change: `git show {mb}:<path>`",
             f"hunks: `git diff {mb} {after} -- <path>`"]
    if diff.get("uncommitted") or head_now == diff.get("head_sha"):
        lines.append("code after the change: the work tree")
    else:
        lines.append(f"code after the change: `git show {diff.get('head_sha')}:<path>` "
                     f"(the work tree is not at head)")
    lines.append("for code the diff does not touch (even in a changed file): read the wiki "
                 "first and cite it; do not answer it from memory of the build, and cite a "
                 "source line of it only after opening that file in this conversation.")
    if not build_context:
        lines.append("[build context] none: this session did not build the map. Answer "
                     "questions about the change from the change notes in [map context] "
                     "and from git, and say that the build's analysis is not available.")
    return "\n".join(lines)


def build_prompt(question: str, ctx, wiki: dict, wikis: list[dict] | None = None,
                 diff: dict | None = None, build_context: bool = True,
                 head_now: str | None = None) -> str:
    """`wikis` (per-wiki status with `dir`) matters only when the wikis are not
    the single one at the repo root: then the engine is told where they are.
    `diff` is a change map's sidecar: the range goes first."""
    parts = []
    if diff:
        parts.append(format_range(diff, head_now, build_context))
    block = format_context(ctx)
    if block:
        parts.append(block)
    if wikis and [w.get("dir") for w in wikis] != [status.DEFAULT_WIKI]:
        where = ", ".join(f"`{status.wiki_location(w['dir'])}`" for w in wikis)
        parts.append(f"[wikis] code-wiki locations, relative to the repository root: {where}")
        parts += [line for w in wikis
                  if (line := _wiki_status_line(w, status.wiki_location(w["dir"])))]
    elif (line := _wiki_status_line(wiki)):
        parts.append(line)
    parts.append(f"question:\n{question}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- server

class ChatServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root: Path, map_path: Path, engine: str, port: int,
                 timeout: int, token: str | None = None, wikis: list[str] | None = None):
        super().__init__(("127.0.0.1", port), Handler)
        self.root = root
        self.map_path = map_path
        self.wikis = wikis or [status.DEFAULT_WIKI]
        self.engine = engine
        self.timeout = timeout
        self.token = token or secrets.token_urlsafe(24)
        self.port = self.server_address[1]
        self.cookie = f"archx_{self.port}"
        self.origins = {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.convs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.verbose = False
        # A change map: its sidecar, and the build session conversations fork.
        self.diff = None
        self.build_session = None
        self.build_ok = True  # False once resuming the build session has failed
        self.refresh_diff()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def refresh_diff(self) -> None:
        """Re-read the sidecar: a rebuild of the map, served by this same
        server, records a new build session."""
        self.diff = status.load_diff_sidecar(self.map_path)
        session = (self.diff or {}).get("session") if self.engine == "claude" else None
        if session != self.build_session:
            self.build_session, self.build_ok = session, True

    @property
    def build_context(self) -> bool:
        return bool(self.build_session and self.build_ok)

    def rules(self) -> str:
        text = RULES_PATH.read_text(encoding="utf-8")
        if self.diff:
            text += "\n\n" + RULES_DIFF_PATH.read_text(encoding="utf-8")
        return text

    def status(self) -> dict:
        self.refresh_diff()
        out = status.check(self.root, self.map_path, self.wikis)
        if self.diff:
            out["diff"] = {k: self.diff.get(k) for k in ("head", "base", "mb", "uncommitted")}
            out["diff"]["build_context"] = self.build_context
        return out


class Handler(BaseHTTPRequestHandler):
    server: ChatServer
    server_version = "arch-explorer"

    def log_message(self, fmt, *args):  # path only: keeps the token out of the log
        if self.server.verbose:
            sys.stderr.write("%s %s\n" % (self.command, urllib.parse.urlsplit(self.path).path))

    # -- helpers

    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _text(self, code: int, text: str):
        self._send(code, text.encode(), "text/plain; charset=utf-8")

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.server.hosts

    def _authed(self) -> bool:
        tok = self.headers.get("X-Archx-Token")
        if tok is None:
            for part in self.headers.get("Cookie", "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == self.server.cookie:
                    tok = v
        return tok is not None and hmac.compare_digest(tok, self.server.token)

    def _origin_ok(self) -> bool:
        return self.headers.get("Origin") in self.server.origins

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if n <= 0 or n > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(n))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    # -- routes

    def do_GET(self):
        if not self._host_ok():
            return self._text(403, "forbidden host")
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/":
            t = urllib.parse.parse_qs(url.query).get("t", [None])[0]
            if t is not None:
                if not hmac.compare_digest(t, self.server.token):
                    return self._text(403, "invalid token")
                cookie = (f"{self.server.cookie}={self.server.token}; "
                          "HttpOnly; SameSite=Strict; Path=/")
                return self._send(303, b"", "text/plain",
                                  {"Location": "/", "Set-Cookie": cookie})
            if not self._authed():
                return self._text(403, "Open this map with /arch-explorer:open.")
            return self._page()
        if not self._authed():
            return self._json(403, {"error": "unauthorized"})
        if url.path == "/health":
            return self._json(200, {"ok": True, "pid": os.getpid(), "engine": self.server.engine,
                                    "root": str(self.server.root),
                                    "map": str(self.server.map_path),
                                    "wikis": self.server.wikis})
        if url.path == "/api/status":
            return self._json(200, {"engine": self.server.engine, **self.server.status()})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._text(403, "forbidden host")
        if not self._authed() or not self._origin_ok():
            return self._json(403, {"error": "forbidden"})
        path = urllib.parse.urlsplit(self.path).path
        body = self._read_json()
        if body is None:
            return self._json(400, {"error": "expected a JSON object body"})
        conv = body.get("conversation")
        if not isinstance(conv, str) or not CONV_ID.match(conv):
            return self._json(400, {"error": "invalid conversation id"})
        if path == "/api/reset":
            with self.server.lock:
                c = self.server.convs.get(conv)
                if c and c["busy"]:
                    return self._json(409, {"error": "a question is still running"})
                self.server.convs.pop(conv, None)
            return self._json(200, {"ok": True})
        if path == "/api/ask":
            return self._ask(conv, body)
        return self._json(404, {"error": "not found"})

    def _page(self):
        try:
            html = self.server.map_path.read_text(encoding="utf-8")
        except OSError as e:
            return self._text(500, f"cannot read map: {e}")
        try:
            panel = PANEL_PATH.read_text(encoding="utf-8")
        except OSError as e:
            return self._text(500, f"cannot read chat panel: {e}")
        self._send(200, inject(html, panel).encode(), "text/html; charset=utf-8")

    # -- ask

    def _ask(self, conv_id: str, body: dict):
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            return self._json(400, {"error": "empty question"})
        if len(question) > MAX_QUESTION:
            return self._json(400, {"error": f"question longer than {MAX_QUESTION} characters"})
        srv = self.server
        with srv.lock:
            conv = srv.convs.setdefault(conv_id, {"session": None, "busy": False,
                                                  "fallback": False})
            if conv["busy"]:
                return self._json(409, {"error": "a question is still running"})
            conv["busy"] = True
        try:
            self._run(conv, question, body.get("context"))
        finally:
            with srv.lock:
                conv["busy"] = False

    def _emit(self, event: dict) -> bool:
        try:
            self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode())
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _run(self, conv: dict, question: str, ctx):
        srv = self.server
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        srv.refresh_diff()
        rules = srv.rules()
        mb = srv.diff.get("mb") if srv.diff else None
        wiki = status.wikis_status(srv.root, srv.wikis, against=mb)
        head_now = status._head(srv.root) if srv.diff else None
        session, fork = conv["session"], False
        if srv.diff and session is None and not conv["fallback"]:
            if srv.build_context:
                session, fork = srv.build_session, True
            else:
                conv["fallback"] = True
        for _ in range(2):
            prompt = build_prompt(question, ctx, *wiki, diff=srv.diff,
                                  build_context=not conv["fallback"], head_now=head_now)
            if self._attempt(conv, rules, prompt, session, fork) != "resume_failed":
                return
            # The build session is gone (cleaned up, another machine): answer without it.
            srv.build_ok = False
            conv["fallback"] = True
            session, fork = None, False
            if not self._emit({"type": "notice", "code": "no-build-context"}):
                return

    def _attempt(self, conv: dict, rules: str, prompt: str, session: str | None,
                 fork: bool) -> str:
        """One engine run, streamed to the client: "done", or "resume_failed"
        when the session to resume does not exist (nothing was streamed)."""
        srv = self.server
        ad = engines.adapter(srv.engine, srv.root, diff=bool(srv.diff))
        try:
            proc = subprocess.Popen(
                ad.argv(rules, session, srv.root, fork=fork), cwd=str(srv.root),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                env=engines.child_env(), start_new_session=True)
        except OSError as e:
            self._emit({"type": "error", "message": f"cannot start {srv.engine}: {e}"})
            return "done"

        lines: queue.Queue = queue.Queue()
        stderr: list[str] = []

        def pump_out():
            try:
                for line in proc.stdout:
                    lines.put(line)
            except (ValueError, OSError):  # closed after a kill
                pass
            lines.put(None)

        def pump_err():
            try:
                for line in proc.stderr:
                    stderr.append(line)
                    del stderr[:-200]
            except (ValueError, OSError):
                pass

        threading.Thread(target=pump_out, daemon=True).start()
        threading.Thread(target=pump_err, daemon=True).start()
        try:
            proc.stdin.write(ad.stdin(rules, prompt, session))
            proc.stdin.close()
        except OSError:
            pass  # the process died early; finish() reports it

        deadline = time.monotonic() + srv.timeout
        connected = True
        outcome = "done"
        try:
            while True:
                try:
                    line = lines.get(timeout=PING_SECONDS)
                except queue.Empty:
                    if time.monotonic() > deadline:
                        self._emit({"type": "error",
                                    "message": f"{srv.engine} timed out after {srv.timeout}s"})
                        break
                    if not self._emit({"type": "ping"}):
                        connected = False
                        break
                    continue
                if line is None:
                    proc.wait()
                    for ev in ad.finish(proc.returncode, "".join(stderr)):
                        self._emit(ev)
                    break
                for ev in ad.feed(line):
                    if ev["type"] == "resume_failed":
                        outcome = "resume_failed"
                        break
                    if ev["type"] == "session":
                        conv["session"] = ev["id"]
                        continue
                    if not self._emit(ev):
                        connected = False
                        break
                if not connected or outcome == "resume_failed":
                    break
                if time.monotonic() > deadline:
                    self._emit({"type": "error",
                                "message": f"{srv.engine} timed out after {srv.timeout}s"})
                    break
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for pipe in (proc.stdout, proc.stderr):
                try:
                    pipe.close()
                except OSError:
                    pass
        return outcome


# ---------------------------------------------------------------- commands

def serve(args) -> int:
    rt = runtime_file(args.root, args.map)
    srv = ChatServer(args.root, args.map, args.engine, args.port, args.timeout,
                     wikis=args.wikis)
    srv.verbose = True
    rt.parent.mkdir(parents=True, exist_ok=True)
    tmp = rt.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "port": srv.port, "token": srv.token,
                               "engine": srv.engine, "root": str(args.root),
                               "map": str(args.map), "wikis": srv.wikis}), encoding="utf-8")
    os.chmod(tmp, 0o600)  # the token lives here
    os.replace(tmp, rt)

    def stop(*_):
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"serving {args.map} on http://127.0.0.1:{srv.port}/ (engine: {srv.engine})",
          file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        info = read_runtime(rt)
        if info and info.get("pid") == os.getpid():
            rt.unlink(missing_ok=True)
    return 0


def _stop_pid(pid: int, wait: float = 5.0) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    end = time.monotonic() + wait
    while time.monotonic() < end and pid_alive(pid):
        time.sleep(0.1)


def launch(args) -> int:
    rt = runtime_file(args.root, args.map)
    info = read_runtime(rt)
    if info and pid_alive(info.get("pid")) and health(info["port"], info["token"]):
        same = (info.get("engine") == args.engine
                and info.get("wikis", [status.DEFAULT_WIKI]) == args.wikis)
        if same and (not args.port or args.port == info["port"]):
            url = f"http://127.0.0.1:{info['port']}/?t={info['token']}"
            return _launched(args, url, info["pid"], info["port"], reused=True)
        _stop_pid(info["pid"])

    rt.parent.mkdir(parents=True, exist_ok=True)
    log = rt.with_suffix(".log")
    cmd = [sys.executable, str(Path(__file__).resolve()), "serve",
           "--root", str(args.root), "--map", str(args.map), "--engine", args.engine,
           "--port", str(args.port), "--timeout", str(args.timeout)]
    for d in args.wikis:
        cmd += ["--wiki", d]
    with open(log, "ab") as logf:
        child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                                 start_new_session=True, close_fds=True)
    end = time.monotonic() + 15
    while time.monotonic() < end:
        if child.poll() is not None:
            print(json.dumps({"error": f"server exited with code {child.returncode}",
                              "log": str(log)}))
            return 1
        info = read_runtime(rt)
        if info and info.get("pid") == child.pid and health(info["port"], info["token"]):
            url = f"http://127.0.0.1:{info['port']}/?t={info['token']}"
            return _launched(args, url, child.pid, info["port"], reused=False)
        time.sleep(0.1)
    _stop_pid(child.pid)
    print(json.dumps({"error": "server did not become ready in 15s", "log": str(log)}))
    return 1


def _launched(args, url: str, pid: int, port: int, reused: bool) -> int:
    if not args.no_open:
        webbrowser.open(url)
    print(json.dumps({"url": url, "pid": pid, "port": port, "engine": args.engine,
                      "wikis": args.wikis, "reused": reused, "log": str(runtime_file(args.root, args.map)
                                                   .with_suffix(".log"))}, indent=2))
    return 0


def stop_cmd(args) -> int:
    rt = runtime_file(args.root, args.map)
    info = read_runtime(rt)
    if not info or not pid_alive(info.get("pid")):
        rt.unlink(missing_ok=True)
        print(json.dumps({"stopped": False, "reason": "no server running"}))
        return 0
    _stop_pid(info["pid"])
    print(json.dumps({"stopped": not pid_alive(info["pid"]), "pid": info["pid"]}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("launch", "serve", "stop"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True, type=Path)
        p.add_argument("--map", required=True, type=Path)
        if name != "stop":
            p.add_argument("--engine", required=True, choices=engines.ENGINES)
            p.add_argument("--port", type=int, default=0)
            p.add_argument("--timeout", type=int, default=300)
            p.add_argument("--wiki", action="append", default=[], metavar="DIR",
                           help="directory holding a code-wiki, relative to --root; "
                                "repeatable (default: the repo root)")
        if name == "launch":
            p.add_argument("--no-open", action="store_true")
    args = ap.parse_args(argv)
    args.root = args.root.resolve()
    args.map = (args.map if args.map.is_absolute() else args.root / args.map).resolve()
    if args.cmd != "stop":
        args.wikis = status.normalize_wiki_dirs(args.root, args.wiki)
    if args.cmd != "stop" and not args.map.is_file():
        print(json.dumps({"error": f"map not found: {args.map}"}))
        return 1
    return {"launch": launch, "serve": serve, "stop": stop_cmd}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
