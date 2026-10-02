import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import Repo, path_with

import diff_session
import status


def branch_repo() -> Repo:
    """main with src/a.py; `feature` adds src/b.py and changes src/a.py; on feature."""
    repo = Repo()
    repo.write("src/a.py", "a = 1\n")
    repo.commit("init")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("src/a.py", "a = 2\n")
    repo.write("src/b.py", "b = 1\n")
    repo.commit("feature work")
    return repo


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.repo = branch_repo()
        self.cwd = self.repo.root
        self.rt = tempfile.TemporaryDirectory()
        self.env = mock.patch.object(diff_session, "runtime_dir", lambda: Path(self.rt.name))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.rt.cleanup()
        self.repo.cleanup()

    def resolve(self, *refs, **kw):
        refs = list(refs) + [None] * (2 - len(refs))
        return diff_session.resolve(self.repo.root, refs[0], refs[1], cwd=self.cwd, **kw)

    def sha(self, ref):
        return self.repo.git("rev-parse", ref).strip()

    def test_current_branch_against_main(self):
        r = self.resolve()
        self.assertNotIn("ask", r)
        self.assertEqual((r["head"], r["base"], r["base_ref"]), ("feature", "main", "refs/heads/main"))
        self.assertEqual(r["mb"], self.sha("main"))
        self.assertEqual(r["after"], self.sha("feature"))
        self.assertEqual((r["read_from"], r["files"], len(r["commits"])), ("worktree", 2, 1))
        self.assertEqual(r["commits"][0]["subject"], "feature work")
        self.assertEqual(r["out"], str(self.repo.root / "feature-vs-main.html"))
        self.assertEqual(r["sidecar"], str(self.repo.root / "feature-vs-main.arch-explorer.json"))
        self.assertEqual(json.loads(Path(r["range_file"]).read_text())["mb"], r["mb"])
        self.assertEqual(Path(r["build_log"]).parent, Path(self.rt.name))

    def test_output_paths(self):
        self.repo.git("checkout", "-q", "-b", "topic/login")
        self.assertTrue(self.resolve()["out"].endswith("/topic-login-vs-main.html"))
        root = self.repo.root
        self.assertEqual(self.resolve(save_to="")["out"],
                         str(root / "docs/architecture/changes/topic-login-vs-main.html"))
        self.assertEqual(self.resolve(save_to="x/y.html")["out"], str(root / "x/y.html"))
        self.assertEqual(self.resolve(save_to="out")["out"],
                         str(root / "out/topic-login-vs-main.html"))

    def test_merge_base_not_the_base_tip(self):
        fork = self.sha("main")
        self.repo.git("checkout", "-q", "main")
        self.repo.write("src/later.py")
        self.repo.commit("later on main")
        r = self.resolve("feature")
        self.assertEqual(r["mb"], fork)
        self.assertEqual(r["files"], 2)  # main's later.py is not the branch's change
        self.assertEqual(r["read_from"], "git")  # feature is not checked out

    def test_head_is_a_default_branch_asks(self):
        self.repo.git("checkout", "-q", "main")
        r = self.resolve()
        self.assertTrue(r["ask"])
        self.assertEqual(len(r["choices"]), 1)
        r = self.resolve(include_uncommitted=True)
        self.assertIn("only the uncommitted changes (base = head)", r["choices"])

    def test_questions_instead_of_guesses(self):
        self.assertTrue(self.resolve("nope")["ask"])
        self.assertTrue(self.resolve("feature", "nope")["ask"])
        self.assertTrue(self.resolve("feature", "feature")["ask"])  # same commit
        self.repo.git("checkout", "-q", "--detach")
        self.assertIn("detached", self.resolve()["reason"])

    def test_no_main_or_master_asks(self):
        self.repo.git("branch", "-m", "main", "trunk")
        self.assertTrue(self.resolve()["ask"])
        self.assertEqual(self.resolve("feature", "trunk")["base"], "trunk")

    def test_unrelated_history_asks(self):
        self.repo.git("checkout", "-q", "--orphan", "other")
        self.repo.commit("orphan")
        self.assertIn("no history", self.resolve("other", "main")["reason"])

    def test_origin_main_when_no_local_main(self):
        self.repo.git("update-ref", "refs/remotes/origin/main", self.sha("main"))
        self.repo.git("branch", "-D", "main")
        r = self.resolve()
        self.assertEqual((r["base"], r["base_ref"]), ("main", "refs/remotes/origin/main"))

    def test_local_and_origin_differ_is_noted(self):
        self.repo.git("update-ref", "refs/remotes/origin/main", self.sha("feature"))
        r = self.resolve()
        self.assertEqual(r["base_ref"], "refs/heads/main")
        self.assertTrue(any("origin/main" in n for n in r["notes"]))

    def test_uncommitted_left_out_is_noted(self):
        self.repo.write("src/a.py", "a = 3\n")
        r = self.resolve()
        self.assertEqual(r["after"], self.sha("feature"))
        self.assertEqual(r["read_from"], "git")  # the work tree is not head any more
        self.assertTrue(any("--include-uncommitted" in n for n in r["notes"]))

    def test_include_uncommitted_never_touches_the_index(self):
        self.repo.write("src/a.py", "a = 3\n")
        self.repo.write("src/new.py")
        self.repo.write("src/staged.py")
        self.repo.git("add", "src/staged.py")
        index = (self.repo.root / ".git/index").read_bytes()
        cached = self.repo.git("diff", "--cached", "--name-only")
        r = self.resolve(include_uncommitted=True)
        self.assertEqual((self.repo.root / ".git/index").read_bytes(), index)
        self.assertEqual(self.repo.git("diff", "--cached", "--name-only"), cached)
        self.assertNotEqual(r["after"], r["head_sha"])
        changed = self.repo.git("diff", "--name-only", r["head_sha"], r["after"]).split()
        self.assertEqual(sorted(changed), ["src/a.py", "src/new.py", "src/staged.py"])
        self.assertTrue(r["out"].endswith("/feature-uncommitted-vs-main.html"))
        self.assertEqual(r["read_from"], "worktree")
        self.assertTrue(any("3 file(s) come from uncommitted work" in n for n in r["notes"]))

    def test_the_maps_own_files_are_not_part_of_the_snapshot(self):
        self.repo.write("feature-uncommitted-vs-main.html", "<html></html>")
        self.repo.write("feature-uncommitted-vs-main.arch-explorer.json", "{}")
        self.repo.write("src/a.py", "a = 3\n")
        r = self.resolve(include_uncommitted=True)
        self.assertEqual(self.repo.git("diff", "--name-only", r["head_sha"], r["after"]).split(),
                         ["src/a.py"])
        self.assertTrue(any("overwritten" in n for n in r["notes"]))

    def test_include_uncommitted_on_another_branch_asks(self):
        self.repo.git("checkout", "-q", "main")
        r = self.resolve("feature", include_uncommitted=True)
        self.assertTrue(r["ask"])

    def test_no_changes_is_empty(self):
        self.repo.write("src/a.py", "a = 1\n")
        self.repo.git("rm", "-q", "src/b.py")
        self.repo.commit("revert")
        r = self.resolve()
        self.assertTrue(r["empty"])
        self.assertNotIn("range_file", r)


class SidecarStatusTest(unittest.TestCase):
    def setUp(self):
        self.repo = branch_repo()
        self.rt = tempfile.TemporaryDirectory()
        self.env = mock.patch.object(diff_session, "runtime_dir", lambda: Path(self.rt.name))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.rt.cleanup()
        self.repo.cleanup()

    def make(self, **kw):
        rng = diff_session.resolve(self.repo.root, cwd=self.repo.root, save_to="", **kw)
        Path(rng["out"]).parent.mkdir(parents=True, exist_ok=True)
        Path(rng["out"]).write_text("<html><script>const MODEL={};const CHANGES={}</script></html>")
        diff_session.record(rng)
        return rng, Path(rng["out"])

    def test_record_makes_a_fresh_change_map(self):
        rng, out = self.make()
        meta = status.load_diff_sidecar(out)
        self.assertEqual((meta["kind"], meta["session"], meta["mb"]), ("diff", None, rng["mb"]))
        r = status.check(self.repo.root, out)
        self.assertEqual((r["kind"], r["map"]["state"], r["map"]["session"]), ("diff", "fresh", False))

    def test_a_map_without_the_sidecar_is_a_build_map(self):
        out = self.repo.write("docs/architecture/index.html", "<html></html>")
        self.assertEqual(status.check(self.repo.root, out)["kind"], "build")

    def test_branch_advanced(self):
        _, out = self.make()
        self.repo.write("src/c.py")
        self.repo.commit("more")
        m = status.check(self.repo.root, out)["map"]
        self.assertEqual((m["state"], m["reason"], m["commits"]), ("stale", "advanced", 1))

    def test_branch_rewritten(self):
        _, out = self.make()
        self.repo.git("commit", "-q", "--amend", "-m", "reworded")
        m = status.check(self.repo.root, out)["map"]
        self.assertEqual((m["state"], m["reason"]), ("stale", "rewritten"))

    def test_uncommitted_map_follows_the_work_tree(self):
        self.repo.write("src/a.py", "a = 3\n")
        _, out = self.make(include_uncommitted=True)
        self.assertEqual(status.check(self.repo.root, out)["map"]["state"], "fresh")
        self.repo.write("src/a.py", "a = 4\n")
        m = status.check(self.repo.root, out)["map"]
        self.assertEqual((m["state"], m["reason"]), ("stale", "worktree"))

    def test_wiki_is_judged_against_the_merge_base(self):
        self.repo.git("checkout", "-q", "main")
        self.repo.write("wiki/config.yaml", "source_roots:\n  - path: src\n")
        self.repo.commit("wiki")
        self.repo.git("checkout", "-q", "feature")
        self.repo.git("rebase", "-q", "main")
        _, out = self.make()
        r = status.check(self.repo.root, out)
        self.assertEqual(r["wiki"]["state"], "fresh")  # the branch's own changes do not count
        self.assertEqual(r["wiki"]["against"], r["map"]["mb"])
        self.assertEqual(status.wikis_status(self.repo.root)[0]["state"], "stale")  # vs HEAD
        before_build = self.repo.root / "not-built-yet.html"
        r = status.check(self.repo.root, before_build, against=r["map"]["mb"])
        self.assertEqual((r["kind"], r["wiki"]["state"]), ("build", "fresh"))


FAKE_BUILD = r'''#!{python}
import json, os, sys, time
data = sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "stdin": data, "cwd": os.getcwd()}}) + "\n")
mode = os.environ.get("FAKE_MODE", "ok")
out = next(l[len("OUTPUT: "):] for l in data.splitlines() if l.startswith("OUTPUT: "))
emit = lambda d: print(json.dumps(d), flush=True)
if mode == "fail":
    sys.stderr.write("Not logged in\n"); sys.exit(2)
if mode == "sleep":
    time.sleep(60)
emit({{"type": "system", "subtype": "init", "session_id": "build-sess"}})
emit({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": "Bash", "input": {{"command": "git diff x y"}}}}]}}}})
emit({{"type": "assistant", "parent_tool_use_id": "t1", "message": {{"content": [{{"type": "tool_use", "name": "Read", "input": {{"file_path": "src/a.py"}}}}]}}}})
if mode != "noout":
    open(out, "w").write("<html><script>const MODEL={{}};const CHANGES={{}}</script></html>")
if mode == "dirty":
    open("src/evil.py", "w").write("x")
if mode == "twice":
    emit({{"type": "result", "subtype": "success", "is_error": False, "session_id": "build-sess", "result": "waiting for subagents"}})
text = {{"cannot": "Looked around.\nCANNOT: base is ambiguous"}}.get(mode, "Wrote the map: 2 blocks.")
emit({{"type": "result", "subtype": "success", "is_error": False, "session_id": "build-sess", "result": text}})
'''


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.repo = branch_repo()
        self.rt = tempfile.TemporaryDirectory()
        self.bin = tempfile.TemporaryDirectory()
        fake = Path(self.bin.name) / "claude"
        fake.write_text(FAKE_BUILD.format(python=sys.executable))
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.log = Path(self.rt.name) / "calls.jsonl"
        self.patches = [
            mock.patch.object(diff_session, "runtime_dir", lambda: Path(self.rt.name)),
            mock.patch.dict(os.environ, {"PATH": path_with(self.bin.name),
                                         "FAKE_LOG": str(self.log), "FAKE_MODE": "ok"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.bin.cleanup()
        self.rt.cleanup()
        self.repo.cleanup()

    def rng(self, *refs, **kw):
        refs = list(refs) + [None] * (2 - len(refs))
        return diff_session.resolve(self.repo.root, refs[0], refs[1], cwd=self.repo.root,
                                    save_to="", **kw)

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def mode(self, m):
        os.environ["FAKE_MODE"] = m

    def test_build_records_the_session(self):
        rng = self.rng()
        r = diff_session.build(rng, timeout=30)
        self.assertNotIn("error", r)
        self.assertEqual((r["session"], r["reused"]), ("build-sess", False))
        self.assertEqual(r["report"], "Wrote the map: 2 blocks.")
        meta = status.load_diff_sidecar(Path(rng["out"]))
        self.assertEqual((meta["session"], meta["engine"], meta["after"]),
                         ("build-sess", "claude", rng["after"]))
        call = self.calls()[0]
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("Bash(git diff *)", argv)
        self.assertNotIn("Bash(git *)", argv)  # no checkout, reset or stash
        self.assertIn("Bash(git *--output*)", argv[argv.index("--disallowedTools"):])
        self.assertNotIn("--add-dir", argv)
        self.assertEqual(Path(call["cwd"]).resolve(), self.repo.root)
        self.assertIn(f"OUTPUT: {rng['out']}", call["stdin"])
        self.assertIn(rng["mb"], call["stdin"])
        self.assertIn("skills/diff/SKILL.md", call["stdin"])
        log = Path(r["log"]).read_text()
        self.assertIn("tool Bash: git diff x y", log)
        self.assertIn("tool (subagent) Read: src/a.py", log)

    def test_same_range_is_reused_unless_forced(self):
        rng = self.rng()
        diff_session.build(rng, timeout=30)
        r = diff_session.build(rng, timeout=30)
        self.assertTrue(r["reused"])
        self.assertEqual(len(self.calls()), 1)
        r = diff_session.build(rng, timeout=30, force=True)
        self.assertFalse(r["reused"])
        self.assertEqual(len(self.calls()), 2)

    def test_the_last_result_counts(self):
        self.mode("twice")
        r = diff_session.build(self.rng(), timeout=30)
        self.assertEqual(r["report"], "Wrote the map: 2 blocks.")

    def test_failures_write_no_sidecar(self):
        for mode, needle in [("cannot", "CANNOT: base is ambiguous"),
                             ("dirty", "src/evil.py"),
                             ("noout", "without writing"),
                             ("fail", "Not logged in")]:
            with self.subTest(mode=mode):
                self.mode(mode)
                rng = self.rng()
                r = diff_session.build(rng, timeout=30, force=True)
                self.assertIn(needle, r.get("error", ""))
                self.assertFalse(Path(rng["sidecar"]).exists())
                (self.repo.root / "src/evil.py").unlink(missing_ok=True)
                Path(rng["out"]).unlink(missing_ok=True)

    def test_timeout_kills_the_build(self):
        self.mode("sleep")
        r = diff_session.build(self.rng(), timeout=1)
        self.assertIn("timed out", r["error"])

    def test_another_branch_is_read_from_a_temporary_worktree(self):
        self.repo.git("checkout", "-q", "main")
        rng = self.rng("feature")
        self.assertEqual(rng["read_from"], "git")
        r = diff_session.build(rng, timeout=30)
        self.assertNotIn("error", r)
        call = self.calls()[0]
        wt = call["argv"][call["argv"].index("--add-dir") + 1]
        self.assertIn(f"`{wt}` — a worktree of head", call["stdin"])
        self.assertFalse(Path(wt).exists())
        self.assertEqual(len(self.repo.git("worktree", "list").splitlines()), 1)

    def test_claude_missing(self):
        with mock.patch.dict(os.environ, {"PATH": path_with(tempfile.gettempdir(), only=True)}):
            r = diff_session.build(self.rng(), timeout=30)
        self.assertIn("not installed", r["error"])


class CliTest(unittest.TestCase):
    def test_resolve_prints_json(self):
        repo = branch_repo()
        rt = tempfile.TemporaryDirectory()
        try:
            with mock.patch.object(diff_session, "runtime_dir", lambda: Path(rt.name)), \
                 mock.patch("sys.stdout") as out:
                code = diff_session.main(["resolve", "--root", str(repo.root),
                                          "--cwd", str(repo.root), "--save-to"])
            printed = "".join(c.args[0] for c in out.write.call_args_list)
            self.assertEqual(code, 0)
            self.assertIn("docs/architecture/changes/feature-vs-main.html",
                          json.loads(printed)["out"])
        finally:
            rt.cleanup()
            repo.cleanup()


if __name__ == "__main__":
    unittest.main()
