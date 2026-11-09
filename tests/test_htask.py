import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HTASK = Path(__file__).resolve().parent.parent / "htask"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo_a, self.repo_b = root / "a", root / "b"
        for repo in (self.repo_a, self.repo_b):
            (repo / "sub").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.env = {**os.environ, "HTASK_DB": str(root / "t.db"), "HERDR_PANE_ID": "w1:p1"}
        # Never report to a real Herdr TUI the tests happen to run in.
        for key in ("HTASK_PROJECT", "HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_BIN_PATH"):
            self.env.pop(key, None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_htask(self, *args, cwd=None, check=True):
        return subprocess.run([sys.executable, str(HTASK), *args], cwd=cwd or self.repo_a,
                              env=self.env, capture_output=True, text=True, check=check)

    def tasks(self, cwd=None):
        out = json.loads(self.run_htask("list", "--all", "--json", cwd=cwd).stdout)
        self.assertEqual(out["project"], os.path.realpath(cwd or self.repo_a))
        return out["tasks"]


class HtaskCLI(Base):
    def test_lifecycle(self):
        self.run_htask("add", "one", "-d", "first, with a comma")
        self.run_htask("add", "two")
        self.run_htask("start", "1")
        self.run_htask("note", "1", "halfway")
        self.run_htask("done", "2")
        t1, t2 = self.tasks()
        self.assertEqual((t1["status"], t1["note"], t1["description"]),
                         ("doing", "halfway", "first, with a comma"))
        self.assertEqual(t2["status"], "done")
        self.assertIsNotNone(t2["completed_at"])
        self.assertEqual(t1["pane_id"], "w1:p1")

    def test_subdir_maps_to_git_root_and_projects_are_separate(self):
        self.run_htask("add", "in a", cwd=self.repo_a / "sub")
        self.run_htask("add", "in b", cwd=self.repo_b)
        self.assertEqual([t["title"] for t in self.tasks()], ["in a"])
        self.assertEqual([t["title"] for t in self.tasks(self.repo_b)], ["in b"])

    def test_reopen_clears_completed_at(self):
        self.run_htask("add", "x")
        self.run_htask("done", "1")
        self.run_htask("reopen", "1")
        self.assertIsNone(self.tasks()[0]["completed_at"])

    def test_unknown_id_fails(self):
        out = self.run_htask("done", "42", check=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("no task #42", out.stderr)

    def test_add_from_panel(self):
        # The panel adds with --agent you and "--", so a title starting with "-" still works.
        self.run_htask("add", "--agent", "you", "--", "-fix the flag parser")
        (t,) = self.tasks()
        self.assertEqual((t["title"], t["agent"]), ("-fix the flag parser", "you"))

    def test_list_hides_done_by_default(self):
        self.run_htask("add", "open")
        self.run_htask("add", "closed", "--status", "done")
        out = self.run_htask("list").stdout
        self.assertIn("open", out)
        self.assertNotIn("closed", out)


class ClaudeHook(Base):
    def hook(self, tool, tool_input, tool_response=None, session="s1"):
        event = {"session_id": session, "cwd": str(self.repo_a / "sub"), "hook_event_name": "PostToolUse",
                 "tool_name": tool, "tool_input": tool_input, "tool_response": tool_response or {}}
        out = subprocess.run([sys.executable, str(HTASK), "hook", "claude"], input=json.dumps(event),
                             env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out

    def test_create_then_update(self):
        self.hook("TaskCreate", {"subject": "Parse output", "description": "6.x block"}, {"task": {"id": "1"}})
        self.hook("TaskUpdate", {"taskId": "1", "status": "in_progress"})
        (t,) = self.tasks()
        self.assertEqual((t["title"], t["description"], t["status"], t["agent"]),
                         ("Parse output", "6.x block", "doing", "claude"))
        self.hook("TaskUpdate", {"taskId": "1", "status": "completed"})
        self.assertEqual(self.tasks()[0]["status"], "done")

    def test_sessions_do_not_collide(self):
        self.hook("TaskCreate", {"subject": "a"}, {"task": {"id": "1"}}, session="s1")
        self.hook("TaskCreate", {"subject": "b"}, {"task": {"id": "1"}}, session="s2")
        self.hook("TaskUpdate", {"taskId": "1", "status": "completed"}, session="s2")
        self.assertEqual([(t["title"], t["status"]) for t in self.tasks()], [("a", "todo"), ("b", "done")])

    def test_update_for_unknown_task_is_ignored(self):
        self.hook("TaskUpdate", {"taskId": "9", "status": "completed"})
        self.assertEqual(self.tasks(), [])

    def test_todowrite_upserts_by_text(self):
        self.hook("TodoWrite", {"todos": [{"content": "x", "status": "pending"}, {"content": "y", "status": "pending"}]})
        self.hook("TodoWrite", {"todos": [{"content": "x", "status": "completed"}, {"content": "y", "status": "in_progress"}]})
        self.assertEqual([(t["title"], t["status"]) for t in self.tasks()], [("x", "done"), ("y", "doing")])

    def test_bad_input_never_fails(self):
        out = subprocess.run([sys.executable, str(HTASK), "hook", "claude"], input="not json",
                             env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("htask hook", out.stderr)

    def test_summary(self):
        self.run_htask("add", "a")
        self.run_htask("add", "b")
        self.run_htask("done", "1")
        self.run_htask("add", "elsewhere", cwd=self.repo_b)
        self.run_htask("block", "3", "-m", "need data", cwd=self.repo_b)
        s = json.loads(self.run_htask("summary").stdout)
        self.assertEqual((s["counts"]["done"], s["counts"]["todo"], s["counts"]["blocked"]), (1, 1, 0))
        self.assertEqual([(b["title"], b["note"]) for b in s["blocked"]], [("elsewhere", "need data")])

class Clean(Base):
    def age(self, task_id, days):
        """Pretend task_id finished `days` ago."""
        import sqlite3, time
        conn = sqlite3.connect(self.env["HTASK_DB"])
        with conn:
            conn.execute("UPDATE tasks SET completed_at = ?, updated_at = ? WHERE id = ?",
                         (time.time() - days * 86400,) * 2 + (task_id,))

    def test_clean_archives_only_old_finished_tasks(self):
        for title in ("old done", "new done", "open", "old dropped"):
            self.run_htask("add", title)
        self.run_htask("done", "1", "2")
        self.run_htask("drop", "4")
        self.age(1, 10)
        self.age(4, 10)
        self.assertIn("2 task(s) would be archived", self.run_htask("clean", "--dry-run").stdout)
        self.assertEqual(len(self.tasks()), 4)  # dry run changed nothing
        self.run_htask("clean")
        self.assertEqual([t["title"] for t in self.tasks()], ["new done", "open"])
        archived = json.loads(self.run_htask("list", "--archived", "--json").stdout)["tasks"]
        self.assertEqual([t["title"] for t in archived], ["old done", "old dropped"])
        summary = json.loads(self.run_htask("summary").stdout)
        self.assertEqual((summary["counts"]["done"], summary["counts"]["dropped"]), (1, 0))

    def test_clean_is_per_project_unless_everywhere(self):
        self.run_htask("add", "a")
        self.run_htask("add", "b", cwd=self.repo_b)
        self.run_htask("done", "1")
        self.run_htask("done", "2", cwd=self.repo_b)
        self.run_htask("clean", "--days", "0")
        self.assertEqual(self.tasks(), [])
        self.assertEqual(len(self.tasks(self.repo_b)), 1)
        self.run_htask("clean", "--days", "0", "--everywhere")
        self.assertEqual(self.tasks(self.repo_b), [])

    def test_reopen_unarchives(self):
        self.run_htask("add", "x")
        self.run_htask("done", "1")
        self.run_htask("clean", "--days", "0")
        self.run_htask("reopen", "1")
        self.assertEqual([(t["title"], t["status"]) for t in self.tasks()], [("x", "todo")])


class TuiProgress(Base):
    def test_reports_tasks_token_to_pane_and_workspace(self):
        log = Path(self.tmp.name) / "herdr.log"
        fake = Path(self.tmp.name) / "herdr"
        fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
        fake.chmod(0o755)
        self.env.update(HERDR_ENV="1", HERDR_BIN_PATH=str(fake), HERDR_WORKSPACE_ID="w1")
        self.run_htask("add", "a")
        self.run_htask("add", "b")
        self.run_htask("done", "1")
        last = log.read_text().splitlines()[-2:]
        self.assertEqual(last, ["pane report-metadata w1:p1 --source htask --token tasks=1/2",
                                "workspace report-metadata w1 --source htask --token tasks=1/2"])

    def test_silent_outside_herdr(self):
        self.env.pop("HERDR_ENV", None)
        self.env["HERDR_BIN_PATH"] = "/nonexistent/herdr"
        self.run_htask("add", "a")  # must not try (or fail) to report

INBOX = Path(__file__).resolve().parent.parent / "hooks" / "claude-inbox.sh"


class ClaudeInbox(Base):
    def setUp(self):
        super().setUp()
        self.env["HTASK_BIN"] = str(HTASK)

    def inbox(self, session="s1", event="PostToolUse"):
        payload = {"session_id": session, "cwd": str(self.repo_a), "hook_event_name": event, "tool_name": "Bash"}
        out = subprocess.run([str(INBOX)], input=json.dumps(payload), env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        if not out.stdout.strip():
            return None
        context = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], event)
        return context["additionalContext"]

    def claude_task(self, subject, task_id, session="s1"):
        event = {"session_id": session, "cwd": str(self.repo_a), "tool_name": "TaskCreate",
                 "tool_input": {"subject": subject}, "tool_response": {"task": {"id": task_id}}}
        subprocess.run([sys.executable, str(HTASK), "hook", "claude"], input=json.dumps(event),
                       env=self.env, check=True, capture_output=True, text=True)

    def test_first_call_only_sets_the_cursor(self):
        self.run_htask("--by", "you", "add", "old backlog")
        self.assertIsNone(self.inbox())

    def test_human_change_to_own_task_is_reported_once(self):
        self.claude_task("Parse output", "3")
        self.assertIsNone(self.inbox())
        self.run_htask("--by", "you", "done", "1")
        text = self.inbox()
        self.assertIn('marked htask #1 "Parse output" (your task 3) done', text)
        self.assertIn("TaskUpdate", text)
        self.assertIsNone(self.inbox())  # already delivered

    def test_agent_changes_are_not_reported(self):
        self.claude_task("Parse output", "1")
        self.inbox()
        self.run_htask("done", "1")  # no --by you: an agent did it
        self.assertIsNone(self.inbox())

    def test_backlog_additions_in_this_repo_only(self):
        self.inbox()
        self.run_htask("--by", "you", "add", "here")
        self.run_htask("--by", "you", "add", "elsewhere", cwd=self.repo_b)
        text = self.inbox(event="UserPromptSubmit")
        self.assertIn('added htask #1 "here"', text)
        self.assertNotIn("elsewhere", text)

    def test_other_sessions_tasks_are_not_reported(self):
        self.env["HERDR_PANE_ID"] = "w9:p9"  # not the terminal that will ask
        self.claude_task("theirs", "1", session="other")
        self.env["HERDR_PANE_ID"] = "w1:p1"
        self.inbox()
        self.run_htask("--by", "you", "drop", "1")
        self.assertIsNone(self.inbox())

    def test_block_reason_and_notes_are_passed_on(self):
        self.claude_task("Parse output", "2")
        self.inbox()
        self.run_htask("--by", "you", "block", "1", "-m", "wait for the new outputs")
        self.run_htask("--by", "you", "note", "1", "use the 6.1 files")
        text = self.inbox()
        self.assertIn('blocked: "wait for the new outputs"', text)
        self.assertIn('note on htask #1 "Parse output" (your task 2): "use the 6.1 files"', text)


class Order(unittest.TestCase):
    def setUp(self):
        from importlib.machinery import SourceFileLoader
        self.htask = SourceFileLoader("htask_module", str(HTASK)).load_module()

    def test_policy(self):
        def task(i, status, pane=None, completed=None):
            return {"id": i, "status": status, "pane_id": pane, "completed_at": completed}
        tasks = [task(1, "todo", "t1"), task(2, "todo", "t9"), task(3, "doing", "t1"),
                 task(4, "blocked", "t1"), task(5, "dropped", "t9")]
        tasks += [task(10 + i, "done", completed=i) for i in range(7)]  # finished at 0..6
        out = self.htask.order_tasks(tasks, "t9", show_done=True)
        self.assertEqual([title for title, _, _ in out], ["BLOCKED", "IN PROGRESS", "TO DO", "DONE"])
        rows = {title: [t["id"] for t in r] for title, r, _ in out}
        self.assertEqual(rows["TO DO"], [2, 1])                 # focused pane's first
        self.assertEqual(rows["DONE"], [16, 15, 14, 13, 12])    # newest five
        self.assertEqual(out[3][2], 2)                          # "+2 more"
        self.assertNotIn(5, sum(rows.values(), []))             # dropped hidden
        self.assertEqual([title for title, _, _ in self.htask.order_tasks(tasks, None, show_done=False)],
                         ["BLOCKED", "IN PROGRESS", "TO DO"])


if __name__ == "__main__":
    unittest.main()
