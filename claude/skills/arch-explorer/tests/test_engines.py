import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import fake_bin, path_with

import engines


class ChooseTest(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.TemporaryDirectory()
        self.bins = {}
        for key, names in {"both": ("claude", "codex"), "claude": ("claude",),
                           "codex": ("codex",), "none": ()}.items():
            self.bins[key] = fake_bin(names)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.cfg.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.cfg.cleanup()
        for b in self.bins.values():
            b.cleanup()

    def choose(self, have, **kw):
        with mock.patch.dict(os.environ, {"PATH": path_with(self.bins[have].name, only=True)}):
            return engines.choose(**kw)

    def test_both_installed_without_default_asks(self):
        r = self.choose("both")
        self.assertTrue(r["ask"])
        self.assertIsNone(r["engine"])

    def test_saved_default_is_used_and_not_asked_again(self):
        engines.save_default("codex")
        r = self.choose("both")
        self.assertEqual((r["engine"], r["ask"]), ("codex", False))
        self.assertEqual(json.loads(engines.config_path().read_text())["default_engine"], "codex")

    def test_config_lives_under_xdg_config_home(self):
        self.assertEqual(engines.config_path(),
                         Path(self.cfg.name) / "arch-explorer" / "config.json")

    def test_explicit_engine_is_one_run_only(self):
        r = self.choose("both", explicit="claude")
        self.assertEqual(r["engine"], "claude")
        self.assertIsNone(engines.load_default())

    def test_explicit_engine_must_be_installed(self):
        r = self.choose("claude", explicit="codex")
        self.assertIsNone(r["engine"])
        self.assertFalse(r["ask"])

    def test_only_one_installed_is_used_without_saving(self):
        r = self.choose("codex")
        self.assertEqual((r["engine"], r["ask"]), ("codex", False))
        self.assertIsNone(engines.load_default())

    def test_saved_default_missing_falls_back_and_keeps_default(self):
        engines.save_default("claude")
        r = self.choose("codex")
        self.assertEqual(r["engine"], "codex")
        self.assertEqual(engines.load_default(), "claude")

    def test_none_installed(self):
        r = self.choose("none")
        self.assertEqual((r["engine"], r["ask"]), (None, False))

    def test_reset_forgets_default_and_asks_again(self):
        engines.save_default("claude")
        r = self.choose("both", reset=True)
        self.assertTrue(r["ask"])
        self.assertIsNone(engines.load_default())

    def test_garbage_config_counts_as_no_default(self):
        engines.config_path().parent.mkdir(parents=True, exist_ok=True)
        engines.config_path().write_text("{nope")
        self.assertTrue(self.choose("both")["ask"])


def run(adapter, lines, returncode=0, stderr=""):
    events = []
    for line in lines:
        events += adapter.feed(json.dumps(line) if isinstance(line, dict) else line)
    return events + adapter.finish(returncode, stderr)


class ClaudeAdapterTest(unittest.TestCase):
    def test_argv_is_read_only_and_resumes(self):
        a = engines.ClaudeAdapter()
        argv = a.argv("RULES", None, Path("/r"))
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob")
        self.assertNotIn("--resume", argv)
        argv = a.argv("RULES", "s1", Path("/r"))
        self.assertEqual(argv[argv.index("--resume") + 1], "s1")
        self.assertEqual(a.stdin("RULES", "Q", None), "Q")

    def test_stream(self):
        ev = run(engines.ClaudeAdapter(), [
            {"type": "system", "subtype": "hook_started"},
            {"type": "system", "subtype": "init", "session_id": "s1"},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "wiki/a.md"}}]}},
            {"type": "stream_event", "event": {"type": "content_block_delta",
                                               "delta": {"type": "input_json_delta"}}},
            {"type": "stream_event", "event": {"type": "content_block_delta",
                                               "delta": {"type": "text_delta", "text": "Hi"}}},
            "not json",
            {"type": "result", "subtype": "success", "is_error": False,
             "session_id": "s1", "result": "Hi there"},
        ])
        self.assertEqual([e["type"] for e in ev], ["session", "tool", "delta", "session", "final"])
        self.assertEqual(ev[1]["detail"], "wiki/a.md")
        self.assertEqual(ev[-1]["text"], "Hi there")

    def test_tool_paths_are_relative_to_the_repo(self):
        ev = run(engines.ClaudeAdapter(Path("/repo")), [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read",
                 "input": {"file_path": "/repo/wiki/src/" + "x" * 150 + ".md"}}]}}])
        self.assertTrue(ev[0]["detail"].startswith("wiki/src/xxx"))

    def test_error_result(self):
        ev = run(engines.ClaudeAdapter(), [
            {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": ""}])
        self.assertEqual(ev[-1], {"type": "error", "message": "error_max_turns"})

    def test_exit_without_result_is_an_error_with_stderr(self):
        ev = run(engines.ClaudeAdapter(), [], returncode=1, stderr="x\nNot logged in\n")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["type"], "error")
        self.assertIn("code 1", ev[0]["message"])
        self.assertIn("Not logged in", ev[0]["message"])


class ClaudeDiffAdapterTest(unittest.TestCase):
    def test_change_map_chat_reads_git_read_only(self):
        argv = engines.ClaudeAdapter(diff=True).argv("RULES", None, Path("/r"))
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob,Bash")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        allowed = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
        self.assertIn("Bash(git show *)", allowed)
        self.assertFalse([a for a in allowed if a.startswith("Bash(") and "git show" not in a
                          and "git diff" not in a and "git log" not in a])
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "Bash(git *--output*)")
        self.assertEqual(argv[argv.index("--append-system-prompt") + 1], "RULES")

    def test_fork_only_with_a_session(self):
        a = engines.ClaudeAdapter(diff=True)
        argv = a.argv("RULES", "build", Path("/r"), fork=True)
        self.assertEqual(argv[-3:], ["--resume", "build", "--fork-session"])
        self.assertNotIn("--fork-session", a.argv("RULES", "s2", Path("/r")))
        self.assertNotIn("--fork-session", a.argv("RULES", None, Path("/r"), fork=True))

    def test_missing_session_is_resume_failed(self):
        ev = run(engines.ClaudeAdapter(), [
            {"type": "result", "subtype": "error_during_execution", "is_error": True,
             "num_turns": 0, "session_id": "new",
             "errors": ["No conversation found with session ID: build"]}], returncode=1)
        self.assertEqual([e["type"] for e in ev], ["resume_failed"])

    def test_other_errors_stay_errors(self):
        ev = run(engines.ClaudeAdapter(), [
            {"type": "result", "subtype": "error_during_execution", "is_error": True,
             "num_turns": 3, "errors": ["No conversation found in the wiki"]}])
        self.assertEqual(ev[-1]["type"], "error")


class CodexAdapterTest(unittest.TestCase):
    def test_argv_first_turn_and_resume(self):
        a = engines.CodexAdapter()
        argv = a.argv("RULES", None, Path("/r"))
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[argv.index("-C") + 1], "/r")
        argv = a.argv("RULES", "t1", Path("/r"))
        self.assertEqual(argv[:4], ["codex", "exec", "resume", "t1"])
        self.assertIn('sandbox_mode="read-only"', argv)
        self.assertTrue(a.stdin("RULES", "Q", None).startswith("RULES"))
        self.assertEqual(a.stdin("RULES", "Q", "t1"), "Q")

    def test_last_message_is_the_answer(self):
        ev = run(engines.CodexAdapter(), [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Reading."}},
            {"type": "item.started", "item": {"type": "command_execution", "command": "cat a"}},
            {"type": "item.completed", "item": {"type": "command_execution"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Answer."}},
            {"type": "turn.completed", "usage": {}},
        ])
        self.assertEqual([e["type"] for e in ev], ["session", "note", "tool", "note", "final"])
        self.assertEqual(ev[-1]["text"], "Answer.")

    def test_turn_failed(self):
        ev = run(engines.CodexAdapter(), [
            {"type": "turn.failed", "error": {"message": "rate limited"}}], returncode=1)
        self.assertEqual(ev, [{"type": "error", "message": "rate limited"}])

    def test_no_message_is_an_error(self):
        ev = run(engines.CodexAdapter(), [{"type": "turn.completed"}])
        self.assertEqual(ev[-1]["type"], "error")


class ChildEnvTest(unittest.TestCase):
    def test_nested_session_markers_are_removed(self):
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "KEEP": "1"}):
            env = engines.child_env()
        self.assertNotIn("CLAUDECODE", env)
        self.assertEqual(env["KEEP"], "1")


if __name__ == "__main__":
    unittest.main()
