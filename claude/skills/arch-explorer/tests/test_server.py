import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import BIN, Repo, fake_bin, path_with

import chat_server

MAP_HTML = "<html><head><title>m</title></head><body><script>const MODEL={}</script></body></html>"


class InjectTest(unittest.TestCase):
    def test_before_last_body_close(self):
        out = chat_server.inject("<body>a</body>x</BODY>", "P")
        self.assertEqual(out, "<body>a</body>xP</BODY>")

    def test_appended_without_body(self):
        self.assertEqual(chat_server.inject("<div>a</div>", "P"), "<div>a</div>P")


class PromptTest(unittest.TestCase):
    def test_context_and_wiki_status(self):
        ctx = {"view": {"id": "worker", "title": "Worker"},
               "node": {"id": "sched", "title": "Scheduler", "lines": ["runs jobs"]},
               "ifaces": [{"title": "enqueue", "from": "api", "to": "sched",
                           "items": [{"sig": "enqueue(job)", "ref": "src/q.py:10"}]}]}
        p = chat_server.build_prompt("what is this?", ctx,
                                     {"state": "stale", "changed": 3, "sha": "abcdef1234567"})
        self.assertIn("current layer: worker — Worker", p)
        self.assertIn("selected box: sched — Scheduler", p)
        self.assertIn("enqueue(job)  @ src/q.py:10", p)
        self.assertIn("3 file(s) changed since abcdef1234", p)
        self.assertTrue(p.endswith("question:\nwhat is this?"))

    def test_subdir_wikis_are_located_for_the_engine(self):
        wikis = [{"dir": "web/api", "state": "fresh"},
                 {"dir": "web/ui", "state": "stale", "changed": 2, "sha": "0123456789abc"}]
        p = chat_server.build_prompt("q", None, {"state": "stale", "changed": 2}, wikis)
        self.assertIn("[wikis] code-wiki locations, relative to the repository root: "
                      "`web/api/wiki/`, `web/ui/wiki/`", p)
        self.assertIn("[wiki status] web/ui/wiki/: the wiki does not reflect 2 file(s)", p)
        self.assertNotIn("web/api/wiki/: ", p)

    def test_root_wiki_prompt_is_unchanged(self):
        wikis = [{"dir": ".", "state": "fresh"}]
        self.assertEqual(chat_server.build_prompt("q", None, {"state": "fresh"}, wikis),
                         "question:\nq")

    def test_no_context(self):
        p = chat_server.build_prompt("q", None, {"state": "fresh"})
        self.assertEqual(p, "question:\nq")

    def test_context_is_bounded(self):
        ctx = {"view": {"id": "v", "title": "x" * 10000}}
        self.assertLess(len(chat_server.format_context(ctx)), chat_server.MAX_CONTEXT + 50)


class ServerTest(unittest.TestCase):
    engine = "claude"

    def setUp(self):
        self.repo = Repo()
        self.repo.write("src/a.py")
        self.map = self.repo.write("docs/architecture/index.html", MAP_HTML)
        self.repo.commit()
        self.bins = fake_bin()
        self.log = Path(tempfile.mkstemp()[1])
        self.env = mock.patch.dict(os.environ, {
            "PATH": path_with(self.bins.name), "FAKE_LOG": str(self.log), "FAKE_MODE": "ok"})
        self.env.start()
        self.srv = chat_server.ChatServer(self.repo.root, self.map, self.engine, 0, timeout=30)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.srv.port}"
        self.cookie = f"{self.srv.cookie}={self.srv.token}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()
        self.bins.cleanup()
        self.log.unlink(missing_ok=True)
        self.repo.cleanup()

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=30)
        h = {"Host": host or f"127.0.0.1:{self.srv.port}"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=h)
        resp = conn.getresponse()
        return resp, resp.read()

    def authed(self, **extra):
        return {"Cookie": self.cookie, "Origin": self.origin, **extra}

    def ask(self, question="q", conv="c1", context=None):
        resp, raw = self.request("POST", "/api/ask",
                                 {"conversation": conv, "question": question, "context": context},
                                 self.authed())
        events = [json.loads(l) for l in raw.decode().splitlines() if l.strip()]
        return resp, events

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines() if l.strip()]

    # -- security

    def test_token_sets_cookie_and_redirects(self):
        resp, _ = self.request("GET", f"/?t={self.srv.token}")
        self.assertEqual(resp.status, 303)
        self.assertEqual(resp.getheader("Location"), "/")
        cookie = resp.getheader("Set-Cookie")
        self.assertIn(self.cookie, cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_wrong_token_rejected(self):
        resp, _ = self.request("GET", "/?t=wrong")
        self.assertEqual(resp.status, 403)

    def test_page_needs_cookie(self):
        resp, _ = self.request("GET", "/")
        self.assertEqual(resp.status, 403)

    def test_foreign_host_rejected(self):
        resp, _ = self.request("GET", "/", headers={"Cookie": self.cookie}, host="evil.example")
        self.assertEqual(resp.status, 403)
        resp, _ = self.request("GET", f"/?t={self.srv.token}", host=f"evil.example:{self.srv.port}")
        self.assertEqual(resp.status, 403)

    def test_api_needs_cookie(self):
        resp, _ = self.request("GET", "/api/status")
        self.assertEqual(resp.status, 403)

    def test_post_needs_own_origin(self):
        body = {"conversation": "c1", "question": "q"}
        resp, _ = self.request("POST", "/api/ask", body,
                               {"Cookie": self.cookie, "Origin": "https://evil.example"})
        self.assertEqual(resp.status, 403)
        resp, _ = self.request("POST", "/api/ask", body, {"Cookie": self.cookie})
        self.assertEqual(resp.status, 403)
        self.assertFalse(self.log.read_text())  # the engine never ran

    # -- page

    def test_page_is_injected_and_disk_untouched(self):
        resp, raw = self.request("GET", "/", headers={"Cookie": self.cookie})
        self.assertEqual(resp.status, 200)
        page = raw.decode()
        self.assertIn('id="arch-chat-host"', page)
        self.assertLess(page.index("arch-chat-host"), page.rindex("</body>"))
        self.assertEqual(self.map.read_text(), MAP_HTML)

    def test_page_reflects_rebuilt_map(self):
        self.map.write_text("<html><body>v2</body></html>")
        _, raw = self.request("GET", "/", headers={"Cookie": self.cookie})
        self.assertIn("v2", raw.decode())

    def test_status(self):
        resp, raw = self.request("GET", "/api/status", headers={"Cookie": self.cookie})
        s = json.loads(raw)
        self.assertEqual(s["engine"], self.engine)
        self.assertEqual(s["map"]["state"], "unknown")
        self.assertEqual(s["wiki"]["state"], "missing")
        self.assertEqual(s["wikis"], [{"dir": ".", "state": "missing"}])

    def test_status_and_prompt_with_subdir_wiki(self):
        self.repo.write("pkg/src/a.py")
        self.repo.write("pkg/wiki/config.yaml", "source_roots:\n  - path: src\n")
        self.repo.commit()
        self.srv.wikis = ["pkg"]
        _, raw = self.request("GET", "/api/status", headers={"Cookie": self.cookie})
        s = json.loads(raw)
        self.assertEqual(s["wiki"]["state"], "fresh")
        self.assertEqual([w["dir"] for w in s["wikis"]], ["pkg"])
        self.ask()
        self.assertIn("[wikis] code-wiki locations, relative to the repository root: `pkg/wiki/`",
                      self.calls()[0]["stdin"])

    # -- ask

    def test_ask_streams_and_resumes(self):
        resp, ev = self.ask(context={"view": {"id": "root", "title": "Root"}})
        self.assertEqual(resp.status, 200)
        types = [e["type"] for e in ev]
        self.assertEqual(types[-1], "final")
        self.assertIn("tool", types)
        self.assertNotIn("session", types)  # kept server-side
        first = self.calls()[0]
        self.assertEqual(Path(first["cwd"]).resolve(), self.repo.root)
        self.assertIn("current layer: root — Root", first["stdin"])
        self.assertNotIn("--resume", first["argv"])

        self.ask("again")
        second = self.calls()[1]
        self.assertEqual(second["argv"][second["argv"].index("--resume") + 1], "sess-claude-1")

    def test_reset_starts_a_new_session(self):
        self.ask()
        resp, _ = self.request("POST", "/api/reset", {"conversation": "c1"}, self.authed())
        self.assertEqual(resp.status, 200)
        self.ask()
        self.assertNotIn("--resume", self.calls()[1]["argv"])

    def test_engine_failure_is_reported(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "fail"}):
            _, ev = self.ask()
        self.assertEqual(ev[-1]["type"], "error")
        self.assertIn("code 3", ev[-1]["message"])
        self.assertIn("auth expired", ev[-1]["message"])

    def test_timeout_kills_the_engine(self):
        self.srv.timeout = 1
        with mock.patch.dict(os.environ, {"FAKE_MODE": "sleep"}), \
                mock.patch.object(chat_server, "PING_SECONDS", 0.2):
            start = time.monotonic()
            _, ev = self.ask()
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(ev[-1]["type"], "error")
        self.assertIn("timed out", ev[-1]["message"])

    def test_busy_conversation_rejected(self):
        self.srv.convs["c1"] = {"session": None, "busy": True}
        resp, _ = self.request("POST", "/api/ask", {"conversation": "c1", "question": "q"},
                               self.authed())
        self.assertEqual(resp.status, 409)

    def test_bad_input(self):
        for body in ({"conversation": "../x", "question": "q"},
                     {"conversation": "c1", "question": "  "},
                     {"conversation": "c1", "question": "x" * 9000}):
            resp, _ = self.request("POST", "/api/ask", body, self.authed())
            self.assertEqual(resp.status, 400, body)


class CodexServerTest(ServerTest):
    engine = "codex"

    def test_ask_streams_and_resumes(self):
        _, ev = self.ask()
        self.assertEqual(ev[-1], {"type": "final", "text": "Answer."})
        first = self.calls()[0]
        self.assertIn("read-only", first["argv"])
        self.assertIn("You answer questions about this repository", first["stdin"])
        self.ask("again")
        second = self.calls()[1]
        self.assertEqual(second["argv"][:3], ["exec", "resume", "thread-codex-1"])
        self.assertNotIn("You answer questions", second["stdin"])

    def test_engine_failure_is_reported(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "fail"}):
            _, ev = self.ask()
        self.assertEqual(ev[-1]["type"], "error")


DIFF_HTML = ("<html><body><script>const MODEL={root:{nodes:[{id:'a',change:'modified'}]}};"
             "const CHANGES={blocks:[]}</script></body></html>")


class DiffServerTest(unittest.TestCase):
    """A change map: forks of the build session, its range in the prompt, the fallback."""
    engine = "claude"

    def setUp(self):
        import diff_session
        self.repo = Repo()
        self.repo.write("src/a.py", "a = 1\n")
        self.main = self.repo.commit("init")
        self.repo.git("checkout", "-q", "-b", "feature")
        self.repo.write("src/a.py", "a = 2\n")
        self.repo.commit("change")
        self.rt = tempfile.TemporaryDirectory()
        with mock.patch.object(diff_session, "runtime_dir", lambda: Path(self.rt.name)):
            self.rng = diff_session.resolve(self.repo.root, cwd=self.repo.root, save_to="")
        self.map = Path(self.rng["out"])
        self.map.parent.mkdir(parents=True)
        self.map.write_text(DIFF_HTML)
        diff_session.record(self.rng, session="build-sess", engine="claude")
        self.bins = fake_bin()
        self.log = Path(tempfile.mkstemp()[1])
        self.env = mock.patch.dict(os.environ, {
            "PATH": path_with(self.bins.name), "FAKE_LOG": str(self.log), "FAKE_MODE": "ok"})
        self.env.start()
        self.srv = chat_server.ChatServer(self.repo.root, self.map, self.engine, 0, timeout=30)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()
        self.bins.cleanup()
        self.log.unlink(missing_ok=True)
        self.rt.cleanup()
        self.repo.cleanup()

    request = ServerTest.request  # the same HTTP and fake-engine helpers
    calls = ServerTest.calls

    def authed(self):
        return {"Cookie": f"{self.srv.cookie}={self.srv.token}",
                "Origin": f"http://127.0.0.1:{self.srv.port}"}

    def ask(self, question="q", conv="c1", context=None):
        _, raw = self.request("POST", "/api/ask",
                              {"conversation": conv, "question": question, "context": context},
                              self.authed())
        return [json.loads(l) for l in raw.decode().splitlines() if l.strip()]

    def status(self):
        _, raw = self.request("GET", "/api/status", headers=self.authed())
        return json.loads(raw)

    def test_conversations_fork_the_build_session(self):
        ev = self.ask()
        self.assertEqual(ev[-1]["type"], "final")
        first = self.calls()[0]["argv"]
        self.assertEqual(first[first.index("--resume") + 1], "build-sess")
        self.assertIn("--fork-session", first)
        self.assertEqual(first[first.index("--permission-mode") + 1], "dontAsk")
        rules = first[first.index("--append-system-prompt") + 1]
        self.assertIn("You answer questions about this repository", rules)
        self.assertIn("## This is a change map", rules)

        self.ask("again")
        second = self.calls()[1]["argv"]
        fork_id = second[second.index("--resume") + 1]
        self.assertTrue(fork_id.startswith("sess-fork-"))
        self.assertNotIn("--fork-session", second)

        self.ask(conv="c2")  # another conversation forks the build again
        third = self.calls()[2]["argv"]
        self.assertEqual(third[third.index("--resume") + 1], "build-sess")
        self.assertIn("--fork-session", third)

    def test_prompt_carries_the_range(self):
        self.ask(context={"view": {"id": "root", "title": "Root"},
                          "node": {"id": "a", "title": "A", "change": "modified"},
                          "block": {"summary": "a is two now", "features": ["bump a"]},
                          "changes": {"nodes": [{"id": "a", "change": "modified"}], "edges": []}})
        stdin = self.calls()[0]["stdin"]
        self.assertTrue(stdin.startswith("[change range] this map shows what `feature` "
                                         "changed against `main`."))
        self.assertIn(f"merge-base: {self.main}", stdin)
        self.assertIn(f"`git diff {self.main} {self.rng['after']} -- <path>`", stdin)
        self.assertIn("code after the change: the work tree", stdin)
        self.assertIn("for code the diff does not touch (even in a changed file): read the wiki",
                      stdin)
        self.assertIn("selected box: a — A [modified]", stdin)
        self.assertIn("change block of the selected box: a is two now", stdin)
        self.assertIn("changed on this layer: box a [modified]", stdin)
        self.assertNotIn("[build context] none", stdin)

    def test_head_not_checked_out_reads_after_side_from_git(self):
        self.repo.git("checkout", "-q", "main")
        self.ask()
        self.assertIn(f"`git show {self.rng['head_sha']}:<path>` (the work tree is not at head)",
                      self.calls()[0]["stdin"])

    def test_missing_build_session_falls_back(self):
        with mock.patch.dict(os.environ, {"FAKE_MODE": "noresume"}):
            ev = self.ask()
            self.assertEqual([e["type"] for e in ev][:1], ["notice"])
            self.assertEqual(ev[0]["code"], "no-build-context")
            self.assertEqual(ev[-1]["type"], "final")
            first, retry = self.calls()
            self.assertIn("--fork-session", first["argv"])
            self.assertNotIn("--resume", retry["argv"])
            self.assertIn("[build context] none", retry["stdin"])
            self.assertFalse(self.status()["diff"]["build_context"])
            self.ask(conv="c2")  # no second attempt at the gone session
            self.assertNotIn("--resume", self.calls()[2]["argv"])

    def test_rebuilt_map_brings_a_new_session(self):
        import diff_session
        with mock.patch.dict(os.environ, {"FAKE_MODE": "noresume"}):
            self.ask()
        diff_session.record(self.rng, session="build-2", engine="claude")
        self.assertTrue(self.status()["diff"]["build_context"])
        self.ask(conv="c2")
        argv = self.calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1], "build-2")

    def test_status(self):
        s = self.status()
        self.assertEqual(s["kind"], "diff")
        self.assertEqual(s["map"]["state"], "fresh")
        self.assertEqual(s["diff"], {"head": "feature", "base": "main", "mb": self.main,
                                     "uncommitted": False, "build_context": True})

    def test_map_without_session_answers_without_build_context(self):
        import diff_session
        diff_session.record(self.rng)  # built in the user's own session
        self.ask()
        call = self.calls()[0]
        self.assertNotIn("--resume", call["argv"])
        self.assertIn("[build context] none", call["stdin"])


class CodexDiffServerTest(DiffServerTest):
    engine = "codex"

    def test_conversations_fork_the_build_session(self):
        self.ask()
        call = self.calls()[0]
        self.assertNotIn("resume", call["argv"])
        self.assertIn("## This is a change map", call["stdin"])
        self.assertIn("[build context] none", call["stdin"])
        self.assertFalse(self.status()["diff"]["build_context"])

    def test_prompt_carries_the_range(self):
        self.ask()
        self.assertIn("[change range] this map shows what `feature`", self.calls()[0]["stdin"])

    def test_missing_build_session_falls_back(self):
        pass  # codex never resumes the build session

    def test_rebuilt_map_brings_a_new_session(self):
        pass

    def test_status(self):
        self.assertFalse(self.status()["diff"]["build_context"])


class LaunchTest(unittest.TestCase):
    """The real detached process: launch, reuse, engine switch, stop."""

    def setUp(self):
        self.repo = Repo()
        self.map = self.repo.write("docs/index.html", MAP_HTML)
        self.repo.commit()
        self.bins = fake_bin()
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "PATH": path_with(self.bins.name), "TMPDIR": self.tmp.name}

    def tearDown(self):
        self.cli("stop")
        self.bins.cleanup()
        self.tmp.cleanup()
        self.repo.cleanup()

    def cli(self, cmd, *extra):
        args = [sys.executable, str(BIN / "chat_server.py"), cmd,
                "--root", str(self.repo.root), "--map", "docs/index.html", *extra]
        out = subprocess.run(args, capture_output=True, text=True, env=self.env, timeout=30)
        return json.loads(out.stdout)

    def test_launch_reuse_switch_stop(self):
        a = self.cli("launch", "--engine", "claude", "--no-open")
        self.assertFalse(a["reused"])
        b = self.cli("launch", "--engine", "claude", "--no-open")
        self.assertTrue(b["reused"])
        self.assertEqual(a["url"], b["url"])
        c = self.cli("launch", "--engine", "codex", "--no-open")
        self.assertFalse(c["reused"])
        self.assertNotEqual(a["pid"], c["pid"])
        self.assertFalse(chat_server.pid_alive(a["pid"]))
        self.assertTrue(self.cli("stop")["stopped"])
        self.assertFalse(self.cli("stop")["stopped"])

    def test_changed_wikis_restart_the_server(self):
        a = self.cli("launch", "--engine", "claude", "--no-open")
        self.assertEqual(a["wikis"], ["."])
        b = self.cli("launch", "--engine", "claude", "--no-open", "--wiki", "web/api")
        self.assertFalse(b["reused"])
        self.assertEqual(b["wikis"], ["web/api"])
        c = self.cli("launch", "--engine", "claude", "--no-open", "--wiki", "./web/api/")
        self.assertTrue(c["reused"])
        self.assertEqual(b["pid"], c["pid"])

    def test_missing_map(self):
        args = [sys.executable, str(BIN / "chat_server.py"), "launch", "--root",
                str(self.repo.root), "--map", "nope.html", "--engine", "claude", "--no-open"]
        out = subprocess.run(args, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(out.returncode, 1)
        self.assertIn("map not found", out.stdout)


if __name__ == "__main__":
    unittest.main()
