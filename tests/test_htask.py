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
        for key in ("HTASK_PROJECT", "HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_BIN_PATH", "HC_TERMINAL_ID",
                    "HTASK_AGENT", "CLAUDECODE", "HTASK_HC", "CODEX_HOME"):
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

    def test_start_claims_the_task_for_its_terminal(self):
        self.env["HERDR_PANE_ID"] = ""            # added from the panel: no terminal
        self.run_htask("--by", "you", "add", "queued")
        self.env["HERDR_PANE_ID"] = "w1:p7"       # the agent started on it
        self.env["HTASK_AGENT"] = "codex"
        self.run_htask("start", "1")
        (t,) = self.tasks()
        self.assertEqual((t["pane_id"], t["agent"], t["status"]), ("w1:p7", "codex", "doing"))

    def test_start_without_a_terminal_keeps_the_owner(self):
        self.run_htask("add", "mine")             # made in w1:p1
        self.env["HERDR_PANE_ID"] = ""            # the panel marks it in progress
        self.run_htask("--by", "you", "start", "1")
        self.assertEqual(self.tasks()[0]["pane_id"], "w1:p1")

    def test_list_everywhere(self):
        self.run_htask("add", "in a")
        self.run_htask("add", "in b", cwd=self.repo_b)
        out = json.loads(self.run_htask("list", "--everywhere", "--json").stdout)["tasks"]
        self.assertEqual(sorted((os.path.basename(t["project"]), t["title"]) for t in out), [("a", "in a"), ("b", "in b")])
        text = self.run_htask("list", "--everywhere").stdout
        self.assertIn("== a  (", text)
        self.assertIn("== b  (", text)
        self.assertEqual(len(json.loads(self.run_htask("list", "--json").stdout)["tasks"]), 1)  # still just this repo

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

    def test_links_to_matching_htask_add_instead_of_duplicating(self):
        self.run_htask("add", "Parse output")        # Claude ran htask add for the step...
        self.hook("TaskCreate", {"subject": "parse output ", "description": "6.x block"}, {"task": {"id": "1"}})
        self.hook("TaskUpdate", {"taskId": "1", "status": "completed"})  # ...and the task tool too
        (t,) = self.tasks()
        self.assertEqual((t["title"], t["status"], t["description"]), ("parse output ", "done", "6.x block"))

    def test_same_title_from_another_terminal_is_not_linked(self):
        self.env["HERDR_PANE_ID"] = "w9:p9"
        self.run_htask("add", "Parse output")
        self.env["HERDR_PANE_ID"] = "w1:p1"
        self.hook("TaskCreate", {"subject": "Parse output"}, {"task": {"id": "1"}})
        self.assertEqual(len(self.tasks()), 2)

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


class Doctor(Base):
    def test_reports_a_missing_install(self):
        self.env["HOME"] = self.tmp.name  # a home with nothing installed
        out = self.run_htask("doctor", check=False)
        self.assertEqual(out.returncode, 1)
        self.assertIn("~/.local/bin/htask is missing or points elsewhere: run ./install.sh", out.stdout)

    def test_passes_after_linking(self):
        home = Path(self.tmp.name)
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "bin" / "htask").symlink_to(HTASK)
        (home / ".local" / "bin" / "htask-claude-inbox").symlink_to(HTASK.parent / "hooks" / "claude-inbox.sh")
        self.env["HOME"] = str(home)
        out = self.run_htask("doctor", check=False)
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("all good", out.stdout)


class TuiArchived(unittest.TestCase):
    def test_archived_section_only_when_toggled(self):
        from importlib.machinery import SourceFileLoader
        htask = SourceFileLoader("htask_module", str(HTASK)).load_module()
        color = dict.fromkeys(["doing", "blocked", "todo", "done", "dropped", "head"], 0)
        ctx = {"pane_id": None, "agent": None}
        old = {"id": 7, "status": "done", "title": "old work", "pane_id": None}
        text = lambda lines: "\n".join(line for line, _ in lines)
        self.assertNotIn("ARCHIVED", text(htask._render([], "/r", ctx, 80, True, True, color)))
        shown = text(htask._render([], "/r", ctx, 80, True, True, color, [old]))
        self.assertIn("ARCHIVED (1)", shown)
        self.assertIn("#7 old work", shown)
        self.assertIn("Nothing archived", text(htask._render([], "/r", ctx, 80, True, True, color, [])))


class ArchiveOne(Base):
    def test_archive_done_task_and_reopen(self):
        self.run_htask("add", "a")
        self.run_htask("add", "b")
        self.run_htask("done", "1")
        self.run_htask("archive", "1")
        self.assertEqual([t["title"] for t in self.tasks()], ["b"])
        self.run_htask("reopen", "1")
        self.assertEqual([t["title"] for t in self.tasks()], ["a", "b"])

    def test_open_tasks_cannot_be_archived(self):
        self.run_htask("add", "a")
        out = self.run_htask("archive", "1", check=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("only done or dropped", out.stderr)


class TodoToggle(unittest.TestCase):
    def test_hiding_todo(self):
        from importlib.machinery import SourceFileLoader
        htask = SourceFileLoader("htask_module", str(HTASK)).load_module()
        tasks = [{"id": 1, "status": "todo", "pane_id": None, "completed_at": None}]
        titles = lambda **kw: [t for t, _, _ in htask.order_tasks(tasks, None, True, **kw)]
        self.assertIn("TO DO", titles())
        self.assertNotIn("TO DO", titles(show_todo=False))

    def test_dropped_only_when_toggled(self):
        from importlib.machinery import SourceFileLoader
        htask = SourceFileLoader("htask_module", str(HTASK)).load_module()
        tasks = [{"id": 1, "status": "dropped", "pane_id": None, "completed_at": None, "updated_at": 1}]
        titles = lambda **kw: [t for t, _, _ in htask.order_tasks(tasks, None, True, **kw)]
        self.assertNotIn("DROPPED", titles())
        self.assertIn("DROPPED", titles(show_dropped=True))


class ThisPaneMarker(unittest.TestCase):
    def setUp(self):
        from importlib.machinery import SourceFileLoader
        self.htask = SourceFileLoader("htask_module", str(HTASK)).load_module()

    def marked(self, tasks):
        color = dict.fromkeys(["doing", "blocked", "todo", "done", "dropped", "head"], 0)
        lines = self.htask._render(tasks, "/r", {"pane_id": "p1", "agent": None}, 80, True, False, color)
        return [line for line, _ in lines if line.startswith("›")]

    def task(self, i, status, pane):
        return {"id": i, "status": status, "pane_id": pane, "completed_at": 0, "title": f"t{i}",
                "description": "", "note": ""}

    def test_hidden_when_one_pane_made_everything(self):
        self.assertEqual(self.marked([self.task(1, "todo", "p1"), self.task(2, "doing", "p1")]), [])

    def test_shown_on_open_rows_when_panes_mix(self):
        tasks = [self.task(1, "todo", "p1"), self.task(2, "doing", "p2"), self.task(3, "done", "p1")]
        marked = self.marked(tasks)
        self.assertEqual(len(marked), 1)
        self.assertIn("#1", marked[0])


class Connect(Base):
    def setUp(self):
        super().setUp()
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.env["HOME"] = str(self.home)
        self.settings = self.home / ".claude" / "settings.json"
        self.claude_md = self.home / ".claude" / "CLAUDE.md"

    def status(self):
        return json.loads(self.run_htask("connect", "status", "--json").stdout)

    def hook_commands(self):
        hooks = json.loads(self.settings.read_text()).get("hooks", {})
        return sorted((ev, h["command"]) for ev, es in hooks.items() for e in es for h in e["hooks"])

    def test_connect_keeps_existing_settings_and_is_idempotent(self):
        self.settings.write_text(json.dumps({"theme": "dark", "hooks": {"PostToolUse": [
            {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "/x/lint --hook"}]}]}}, indent=2))
        self.claude_md.write_text("# Mine\n\nKeep this.\n")
        self.assertFalse(self.status()["claude"]["connected"])
        self.run_htask("connect", "claude")
        st = self.status()["claude"]
        self.assertTrue(st["connected"], st)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertIn(("PostToolUse", "/x/lint --hook"), self.hook_commands())
        self.assertEqual(len(self.hook_commands()), 4)
        self.assertTrue(self.claude_md.read_text().startswith("# Mine\n\nKeep this.\n"))
        before = (self.settings.read_text(), self.claude_md.read_text(), sorted(p.name for p in (self.home / ".claude").iterdir()))
        out = self.run_htask("connect", "claude").stdout
        self.assertIn("already connected", out)
        after = (self.settings.read_text(), self.claude_md.read_text(), sorted(p.name for p in (self.home / ".claude").iterdir()))
        self.assertEqual(before, after)  # no rewrite, no new backups

    def test_old_inbox_path_is_repointed_not_duplicated(self):
        self.settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": "/old/checkout/hooks/claude-inbox.sh"}]}]}}))
        self.run_htask("connect", "claude")
        prompt = [c for ev, c in self.hook_commands() if ev == "UserPromptSubmit"]
        self.assertEqual(prompt, [str(self.home / ".local" / "bin" / "htask-claude-inbox")])

    def test_remove_takes_out_only_htask(self):
        self.settings.write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "/x/lint --hook"}]}]}}))
        self.claude_md.write_text("# Mine\n")
        self.run_htask("connect", "claude")
        self.run_htask("connect", "claude", "--remove")
        self.assertEqual(self.hook_commands(), [("PostToolUse", "/x/lint --hook")])
        self.assertEqual(self.claude_md.read_text(), "# Mine\n")
        self.assertTrue(any(p.name.startswith("settings.json.bak-htask-") for p in (self.home / ".claude").iterdir()))
        self.assertFalse(self.status()["claude"]["connected"])

    def test_quick_connect_and_remove_keep_both_backups(self):
        original = json.dumps({"theme": "original"})
        self.settings.write_text(original)
        self.run_htask("connect", "claude")
        self.run_htask("connect", "claude", "--remove")
        backups = sorted(p for p in (self.home / ".claude").iterdir() if p.name.startswith("settings.json.bak-htask-"))
        self.assertEqual(len(backups), 2)
        self.assertIn(original, [b.read_text() for b in backups])  # the untouched original survives

    def test_remove_a_hand_written_section(self):
        self.claude_md.write_text("# Mine\n\n## Task tracking (htask)\n\nold text\n\n## Other\n\nkept\n")
        self.run_htask("connect", "claude", "--remove")
        self.assertEqual(self.claude_md.read_text(), "# Mine\n\n## Other\n\nkept\n")

    def test_missing_agent_is_refused(self):
        out = self.run_htask("connect", "codex", check=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("isn't set up here", out.stderr)
        self.assertFalse(self.status()["codex"]["available"])

    def test_codex_gets_instructions_only(self):
        (self.home / ".codex").mkdir()
        self.run_htask("connect", "codex")
        text = (self.home / ".codex" / "AGENTS.md").read_text()
        self.assertIn("<!-- htask:start -->", text)
        self.assertIn("[Herdr task panel]", text)
        self.assertTrue(self.status()["codex"]["connected"])


class CodexHook(Base):
    def hook(self, plan, session="c1", as_string=False):
        inp = {"plan": plan, "explanation": "why"}
        event = {"session_id": session, "cwd": str(self.repo_a / "sub"), "hook_event_name": "PostToolUse",
                 "tool_name": "update_plan", "tool_input": json.dumps(inp) if as_string else inp}
        out = subprocess.run([sys.executable, str(HTASK), "hook", "codex"], input=json.dumps(event),
                             env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def state(self):
        return [(t["title"], t["status"], t["agent"]) for t in self.tasks()]

    def test_plan_is_mirrored_and_revised(self):
        self.hook([{"step": "Read the parser", "status": "completed"},
                   {"step": "Add 6.1 support", "status": "in_progress"},
                   {"step": "Write tests", "status": "pending"}])
        self.assertEqual(self.state(), [("Read the parser", "done", "codex"), ("Add 6.1 support", "doing", "codex"),
                                        ("Write tests", "todo", "codex")])
        # Revised plan: "Write tests" became two steps; the left-out one is dropped, done stays done.
        self.hook([{"step": "Read the parser", "status": "completed"},
                   {"step": "Add 6.1 support", "status": "completed"},
                   {"step": "Unit tests", "status": "pending"}, {"step": "Fixture files", "status": "pending"}],
                  as_string=True)
        self.assertEqual(self.state(), [("Read the parser", "done", "codex"), ("Add 6.1 support", "done", "codex"),
                                        ("Write tests", "dropped", "codex"), ("Unit tests", "todo", "codex"),
                                        ("Fixture files", "todo", "codex")])

    def test_other_tools_and_sessions_are_left_alone(self):
        self.hook([{"step": "A", "status": "pending"}], session="c1")
        self.hook([{"step": "B", "status": "pending"}], session="c2")  # c2's plan doesn't drop c1's steps
        self.assertEqual([(t, st) for t, st, _ in self.state()], [("A", "todo"), ("B", "todo")])

    def fake_hc(self, terminals):
        """A fake `hc` answering ls and get from a dict of address -> (agent, cwd, state)."""
        script = Path(self.tmp.name) / "hc"
        data = json.dumps(terminals)
        script.write_text(f"""#!{sys.executable}
import json, sys
t = json.loads({data!r})
if sys.argv[1] == "ls":
    print(json.dumps({{"terminals": [{{"address": a, "agent": v[0], "state": "live"}} for a, v in t.items()]}}))
else:
    a = sys.argv[2]
    print(json.dumps({{"address": a, "foreground": {{"cwd": t[a][1]}}, "status": {{"state": t[a][2]}}}}))
""")
        script.chmod(0o755)
        self.env["HTASK_HC"] = str(script)
        self.env.pop("HERDR_PANE_ID", None)

    def test_terminal_found_from_herdr_core_when_the_hook_has_none(self):
        self.fake_hc({"t3": ["codex", str(self.repo_a / "sub"), "working"],
                      "t4": ["codex", str(self.repo_b), "working"], "t5": ["claude-code", str(self.repo_a), "idle"]})
        self.hook([{"step": "A", "status": "pending"}])
        self.assertEqual(self.tasks()[0]["pane_id"], "t3")

    def test_codex_commands_without_a_terminal_id_find_theirs(self):
        # Codex runs shell commands without HC_TERMINAL_ID: add and start still record its terminal.
        self.fake_hc({"t8": ["codex", str(self.repo_a), "working"]})
        self.env["HTASK_AGENT"] = "codex"
        self.run_htask("add", "from codex")
        self.assertEqual(self.tasks()[0]["pane_id"], "t8")
        self.env.pop("HTASK_AGENT")
        self.run_htask("--by", "you", "add", "queued by you")  # not codex: no terminal
        self.assertIsNone(self.tasks()[1]["pane_id"])
        self.env["HTASK_AGENT"] = "codex"
        self.run_htask("start", "2")                            # Codex starts it: claims it
        self.assertEqual(self.tasks()[1]["pane_id"], "t8")

    def test_ambiguous_terminal_is_left_empty(self):
        self.fake_hc({"t3": ["codex", str(self.repo_a), "working"], "t4": ["codex", str(self.repo_a), "working"]})
        self.hook([{"step": "A", "status": "pending"}])
        self.assertIsNone(self.tasks()[0]["pane_id"])


class ConnectCodex(Base):
    def setUp(self):
        super().setUp()
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".codex").mkdir(parents=True)
        self.env["HOME"] = str(self.home)
        self.env.pop("CODEX_HOME", None)
        self.hooks = self.home / ".codex" / "hooks.json"

    def test_adds_update_plan_hook_beside_existing_ones(self):
        self.hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "herdr-state idle"}]}]}}))
        (self.home / ".codex" / "config.toml").write_text("[features]\nhooks = true\n")
        out = self.run_htask("connect", "codex").stdout
        self.assertIn("approve a new hook", out)
        data = json.loads(self.hooks.read_text())["hooks"]
        self.assertEqual(data["Stop"][0]["hooks"][0]["command"], "herdr-state idle")
        self.assertEqual(data["PostToolUse"][0]["matcher"], "^update_plan$")
        self.assertTrue(data["PostToolUse"][0]["hooks"][0]["command"].endswith("htask hook codex"))
        status = json.loads(self.run_htask("connect", "status", "--json").stdout)["codex"]
        self.assertTrue(status["connected"] and status["hooks_enabled"], status)
        self.run_htask("connect", "codex", "--remove")
        self.assertEqual(list(json.loads(self.hooks.read_text())["hooks"]), ["Stop"])

    def test_remove_with_no_htask_hooks_leaves_the_file_alone(self):
        original = '{"hooks":{"Stop":[{"hooks":[{"command":"x","type":"command"}]}]}}'  # not htask's formatting
        self.hooks.write_text(original)
        out = self.run_htask("connect", "codex", "--remove").stdout
        self.assertEqual(self.hooks.read_text(), original)
        self.assertNotIn("hooks.json", out)

    def test_warns_when_codex_hooks_are_off(self):
        out = self.run_htask("connect", "codex").stdout
        self.assertIn("[features] hooks = true", out)

    def test_marked_section_is_brought_up_to_date(self):
        agents_md = self.home / ".codex" / "AGENTS.md"
        agents_md.write_text("# Mine\n\n<!-- htask:start -->\n## Task tracking (htask)\n\nold text\n<!-- htask:end -->\n")
        self.run_htask("connect", "codex")
        text = agents_md.read_text()
        self.assertTrue(text.startswith("# Mine\n\n<!-- htask:start -->\n## Task tracking (htask)"))
        self.assertIn("update_plan", text)
        self.assertNotIn("old text", text)


class DetectAgent(Base):
    def detect(self, via=None):
        code = ("from importlib.machinery import SourceFileLoader; import warnings; warnings.simplefilter('ignore');"
                f"print(SourceFileLoader('h', {str(HTASK)!r}).load_module().detect_agent())")
        cmd = [sys.executable, "-c", code]
        if via:  # run under a parent process called `via`
            link = Path(self.tmp.name) / via
            link.symlink_to("/bin/sh")
            import shlex
            # "; true" stops the shell exec-ing python in its place, so the shell stays its parent.
            cmd = [str(link), "-c", " ".join(shlex.quote(c) for c in cmd) + "; true"]
        return subprocess.run(cmd, env=self.env, capture_output=True, text=True).stdout.strip()

    def test_codex_home_or_other_codex_vars_are_not_codex(self):
        self.env.update(CODEX_HOME="/x", CODEX_COMPANION_SESSION_ID="y")
        self.assertEqual(self.detect(), "None")

    def test_codex_sandbox_var(self):
        self.env["CODEX_SANDBOX_NETWORK_DISABLED"] = "1"
        self.assertEqual(self.detect(), "codex")

    @unittest.skipUnless(os.path.exists("/proc/self/stat"), "parent lookup via /proc (Linux)")
    def test_codex_parent_process(self):
        self.assertEqual(self.detect(via="codex"), "codex")
        self.assertEqual(self.detect(), "None")


class Dependencies(Base):
    def test_after_next_and_waiting(self):
        self.run_htask("add", "design")
        self.run_htask("add", "build", "--after", "1")
        self.run_htask("add", "ship", "--after", "1,2")
        out = json.loads(self.run_htask("list", "--json").stdout)["tasks"]
        self.assertEqual([(t["title"], t["after"], t["waiting"]) for t in out],
                         [("design", [], []), ("build", [1], [1]), ("ship", [1, 2], [1, 2])])
        self.assertIn("build  (after #1)", self.run_htask("list").stdout)
        self.assertTrue(self.run_htask("next").stdout.startswith("#1 design"))
        self.run_htask("done", "1")
        self.assertTrue(self.run_htask("next").stdout.startswith("#2 build"))
        self.run_htask("drop", "2")  # dropped counts as out of the way
        self.assertTrue(self.run_htask("next").stdout.startswith("#3 ship"))

    def test_starting_early_warns_but_works(self):
        self.run_htask("add", "a")
        self.run_htask("add", "b", "--after", "1")
        out = self.run_htask("start", "2")
        self.assertIn("comes after #1, not done yet", out.stderr)
        self.assertEqual(self.tasks()[1]["status"], "doing")

    def test_done_before_its_dependency_is_refused_unless_forced(self):
        self.run_htask("add", "A")
        self.run_htask("add", "B", "--after", "1")
        out = self.run_htask("done", "2", check=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("comes after #1, which isn't done", out.stderr)
        self.assertEqual(self.tasks()[1]["status"], "todo")
        self.run_htask("done", "2", "--force")
        self.assertEqual(self.tasks()[1]["status"], "done")

    def test_done_after_dependency_is_fine(self):
        self.run_htask("add", "A")
        self.run_htask("add", "B", "--after", "1")
        self.run_htask("done", "1")
        self.run_htask("done", "2")
        self.assertEqual([t["status"] for t in self.tasks()], ["done", "done"])

    def test_loops_and_self_are_refused(self):
        self.run_htask("add", "a")
        self.run_htask("add", "b", "--after", "1")
        self.assertIn("loop", self.run_htask("depend", "1", "--on", "2", check=False).stderr)
        self.assertIn("itself", self.run_htask("depend", "1", "--on", "1", check=False).stderr)
        self.assertIn("no task #9", self.run_htask("depend", "1", "--on", "9", check=False).stderr)

    def test_depend_clear(self):
        self.run_htask("add", "a")
        self.run_htask("add", "b", "--after", "1")
        self.assertIn("after nothing", self.run_htask("depend", "2", "--clear").stdout)


class ClaudePlanAndDeps(Base):
    def hook(self, tool, tool_input, tool_response=None):
        event = {"session_id": "s1", "cwd": str(self.repo_a), "hook_event_name": "PostToolUse",
                 "tool_name": tool, "tool_input": tool_input, "tool_response": tool_response or {}}
        out = subprocess.run([sys.executable, str(HTASK), "hook", "claude"], input=json.dumps(event),
                             env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_approved_plan_becomes_one_task(self):
        plan = "# Plan: move parsing to 6.x\n\n## Context\n\nThe parser breaks on 6.1.\n\n1. Read\n2. Fix\n"
        self.hook("ExitPlanMode", {"plan": plan, "planFilePath": "/p/plan.md"})
        self.hook("ExitPlanMode", {"plan": plan, "planFilePath": "/p/plan.md"})  # same plan: no duplicate
        (t,) = self.tasks()
        self.assertEqual((t["title"], t["status"], t["agent"]), ("Plan: move parsing to 6.x", "doing", "claude"))
        self.assertIn("The parser breaks on 6.1.", t["description"])
        self.assertIn("Plan file: /p/plan.md", t["description"])

    def test_blocked_by_becomes_a_dependency(self):
        self.hook("TaskCreate", {"subject": "first"}, {"task": {"id": "1"}})
        self.hook("TaskCreate", {"subject": "second", "addBlockedBy": ["1"]}, {"task": {"id": "2"}})
        out = json.loads(self.run_htask("list", "--json").stdout)["tasks"]
        self.assertEqual([t["after"] for t in out], [[], [out[0]["id"]]])


class ConnectMatcherUpgrade(Base):
    def test_old_mirror_matcher_is_widened(self):
        home = Path(self.tmp.name) / "home"
        (home / ".claude").mkdir(parents=True)
        self.env["HOME"] = str(home)
        cmd = str(home / ".local" / "bin" / "htask") + " hook claude"
        settings = home / ".claude" / "settings.json"
        settings.write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "TaskCreate|TaskUpdate|TodoWrite", "hooks": [{"type": "command", "command": cmd}]}]}}))
        self.run_htask("connect", "claude")
        matchers = [e["matcher"] for e in json.loads(settings.read_text())["hooks"]["PostToolUse"]
                    if "hook claude" in e["hooks"][0]["command"]]
        self.assertEqual(matchers, ["TaskCreate|TaskUpdate|TodoWrite|ExitPlanMode"])


class Update(unittest.TestCase):
    """htask update in a throwaway checkout that's one commit behind its 'GitHub'."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        git = lambda *a, cwd=root: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                                  cwd=cwd, check=True, capture_output=True, text=True)
        repo = HTASK.parent
        git("clone", "--quiet", "--no-local", str(repo), "seed")
        git("checkout", "--quiet", "-B", "main", cwd=root / "seed")
        # Test the working tree's code, not just the last commit.
        import shutil
        for f in ("htask", "install.sh", "hooks/claude-inbox.sh"):
            shutil.copy2(repo / f, root / "seed" / f)
        git("commit", "--quiet", "--allow-empty", "-am", "working tree", cwd=root / "seed")
        git("clone", "--quiet", "--bare", "seed", "origin.git")
        git("clone", "--quiet", "origin.git", "checkout")
        git("clone", "--quiet", "origin.git", "pusher")
        (root / "pusher" / "NEWS").write_text("new\n")
        git("add", "NEWS", cwd=root / "pusher")
        git("commit", "--quiet", "-m", "news", cwd=root / "pusher")
        git("push", "--quiet", "origin", "main", cwd=root / "pusher")
        self.checkout, self.home = root / "checkout", root / "home"
        self.home.mkdir()
        # No herdr / herdr-app on PATH: install.sh must not touch the real Herdr's plugin registry.
        self.env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin", "HTASK_DB": str(root / "t.db")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_update(self, *args):
        return subprocess.run([sys.executable, str(self.checkout / "htask"), "update", *args],
                              env=self.env, capture_output=True, text=True)

    def test_check_then_update(self):
        check = self.run_update("--check")
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("1 new commit(s)", check.stdout)
        self.assertFalse((self.checkout / "NEWS").exists())  # --check changes nothing
        up = self.run_update()
        self.assertEqual(up.returncode, 0, up.stderr + up.stdout)
        self.assertIn("pulled 1 commit(s)", up.stdout)
        self.assertTrue((self.checkout / "NEWS").exists())
        link = self.home / ".local" / "bin" / "htask"
        self.assertEqual(link.resolve(), (self.checkout / "htask").resolve())  # install.sh ran
        self.assertIn("already up to date", self.run_update().stdout)


class Versions(unittest.TestCase):
    def test_cli_manifest_and_mod_versions_match(self):
        import re
        root = HTASK.parent
        cli = re.search(r'__version__ = "([^"]+)"', HTASK.read_text()).group(1)
        manifest = re.search(r'^version = "([^"]+)"', (root / "herdr-plugin.toml").read_text(), re.M).group(1)
        mod = re.search(r'MOD_VERSION = "([^"]+)"', (root / "mods" / "htask" / "common.js").read_text()).group(1)
        self.assertEqual((cli, manifest), (mod, mod))


class CameFrom(Base):
    def test_from_and_followups(self):
        self.run_htask("add", "parser")
        self.assertIn("(from #1)", self.run_htask("add", "handle 6.1 edge case", "--from", "1").stdout)
        self.run_htask("add", "docs for the parser", "--from", "1")
        out = {t["title"]: t for t in json.loads(self.run_htask("list", "--json").stdout)["tasks"]}
        self.assertEqual(out["parser"]["followups"], [2, 3])
        self.assertEqual(out["handle 6.1 edge case"]["from_id"], 1)
        self.assertIn("handle 6.1 edge case  (from #1)", self.run_htask("list").stdout)

    def test_edit_sets_and_clears(self):
        self.run_htask("add", "a")
        self.run_htask("add", "b")
        self.run_htask("edit", "2", "--from", "1")
        self.assertEqual(self.tasks()[1]["from_id"], 1)
        self.run_htask("edit", "2", "--from", "0")
        self.assertIsNone(self.tasks()[1]["from_id"])

    def test_refusals(self):
        self.run_htask("add", "a")
        self.assertIn("no task #9", self.run_htask("add", "x", "--from", "9", check=False).stderr)
        self.assertIn("itself", self.run_htask("edit", "1", "--from", "1", check=False).stderr)


class Timeline(Base):
    def events(self, *args, cwd=None):
        return json.loads(self.run_htask("timeline", "--json", *args, cwd=cwd).stdout)["events"]

    def test_who_did_what_newest_first(self):
        self.env["HTASK_AGENT"] = "codex"
        self.run_htask("add", "parser")
        self.run_htask("start", "1")
        self.run_htask("block", "1", "-m", "need samples")
        self.run_htask("--by", "you", "done", "1", "--force")
        ev = self.events()
        self.assertEqual([(e["verb"], e["by"], e["pane_id"]) for e in ev],
                         [("finished", "you", "w1:p1"), ("blocked", "codex", "w1:p1"),
                          ("started", "codex", "w1:p1"), ("added", "codex", "w1:p1")])
        self.assertEqual(ev[1]["detail"], "need samples")
        text = self.run_htask("timeline").stdout
        self.assertTrue(text.startswith("Today\n"))
        self.assertIn("codex (w1:p1) blocked #1 parser: need samples", text)

    def test_hook_copied_changes_are_logged(self):
        event = {"session_id": "s1", "cwd": str(self.repo_a), "tool_name": "TaskCreate",
                 "tool_input": {"subject": "from claude"}, "tool_response": {"task": {"id": "1"}}}
        run = lambda e: subprocess.run([sys.executable, str(HTASK), "hook", "claude"], input=json.dumps(e),
                                       env=self.env, capture_output=True, text=True, check=True)
        run(event)
        run({**event, "tool_name": "TaskUpdate", "tool_input": {"taskId": "1", "status": "completed"}})
        run({**event, "tool_name": "TaskUpdate", "tool_input": {"taskId": "1", "status": "completed"}})  # no change
        self.assertEqual([(e["verb"], e["by"]) for e in self.events()], [("finished", "claude"), ("added", "claude")])

    def test_repo_scope_and_limit(self):
        self.run_htask("add", "here")
        self.run_htask("add", "there", cwd=self.repo_b)
        self.assertEqual([e["title"] for e in self.events()], ["here"])
        self.assertEqual(len(self.events("--everywhere")), 2)
        self.assertEqual(len(self.events("--everywhere", "--limit", "1")), 1)


if __name__ == "__main__":
    unittest.main()
