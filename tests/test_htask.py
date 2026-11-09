import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HTASK = Path(__file__).resolve().parent.parent / "htask"


class HtaskCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo_a, self.repo_b = root / "a", root / "b"
        for repo in (self.repo_a, self.repo_b):
            (repo / "sub").mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.env = {**os.environ, "HTASK_DB": str(root / "t.db"), "HERDR_PANE_ID": "w1:p1"}
        self.env.pop("HTASK_PROJECT", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_htask(self, *args, cwd=None, check=True):
        return subprocess.run([sys.executable, str(HTASK), *args], cwd=cwd or self.repo_a,
                              env=self.env, capture_output=True, text=True, check=check)

    def tasks(self, cwd=None):
        return json.loads(self.run_htask("list", "--all", "--json", cwd=cwd).stdout)

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

    def test_list_hides_done_by_default(self):
        self.run_htask("add", "open")
        self.run_htask("add", "closed", "--status", "done")
        out = self.run_htask("list").stdout
        self.assertIn("open", out)
        self.assertNotIn("closed", out)


if __name__ == "__main__":
    unittest.main()
