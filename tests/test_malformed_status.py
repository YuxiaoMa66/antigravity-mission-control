import argparse
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from antigravity_mission_control import jobs, jobstore

ROOT = Path(__file__).resolve().parents[1]
OLD = "2020-01-01T00:00:00+00:00"
DEAD_PID = 999999


class MalformedStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = mock.patch.object(jobstore, "JOB_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add(self, name, result=None, **job):
        job.setdefault("job_id", name)
        (self.root / name).mkdir()
        (self.root / name / "job.json").write_text(json.dumps(job))
        if result is not None:
            (self.root / name / "result.json").write_text(json.dumps(result))

    def stale_bad_result(self, name="stale-job", result=None):
        self.add(name, result={"status": ["done"]} if result is None else result,
                 status="running", pid=DEAD_PID, finished_at=OLD)

    def job_json(self, name):
        return json.loads((self.root / name / "job.json").read_text())

    def run_cmd(self, func, **ns):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = func(argparse.Namespace(**ns))
        return code, json.loads(out.getvalue())

    def status(self, job_id=None):
        return self.run_cmd(jobs.cmd_status, job_id=job_id, state=None, limit=None)

    def prune(self, yes):
        return self.run_cmd(jobs.cmd_prune, older_than=jobs.parse_duration("1d"), yes=yes)

    def assert_job_json_statuses_valid(self):
        for path in self.root.glob("*/job.json"):
            status = json.loads(path.read_text()).get("status")
            self.assertTrue(isinstance(status, str) and status in jobstore.JOB_EXIT_CODES, (path, status))

    # Reproduction 1: stale running job whose result.json carries a list status.
    def test_status_list_with_bad_result(self):
        self.stale_bad_result()
        code, payload = self.status()
        self.assertEqual(code, 0)
        self.assertEqual([j["status"] for j in payload["jobs"]], ["crashed"])
        self.assertEqual(self.job_json("stale-job")["status"], "crashed")

    def test_status_id_with_bad_result(self):
        self.stale_bad_result()
        code, payload = self.status("stale-job")
        self.assertEqual(payload["status"], "crashed")
        self.assertEqual(code, jobstore.JOB_EXIT_CODES["crashed"])
        self.assert_job_json_statuses_valid()

    def test_prune_dry_run_and_yes_with_bad_result(self):
        self.stale_bad_result()
        self.add("old-done", status="done", finished_at=OLD)
        _, payload = self.prune(yes=False)
        self.assertEqual(sorted(payload["would_remove"]), ["old-done", "stale-job"])
        self.assert_job_json_statuses_valid()
        _, payload = self.prune(yes=True)
        self.assertEqual(sorted(payload["removed"]), ["old-done", "stale-job"])
        self.assertEqual(os.listdir(self.root), [])

    def test_unknown_string_and_non_object_results_resolve_to_crashed(self):
        self.stale_bad_result("unknown-str", result={"status": "exploded"})
        self.stale_bad_result("number", result={"status": 3})
        self.stale_bad_result("still-running", result={"status": "running"})
        self.stale_bad_result("not-object", result=["done"])
        self.stale_bad_result("good", result={"status": "canceled"})
        _, payload = self.status()
        got = {j["job_id"]: j["status"] for j in payload["jobs"]}
        self.assertEqual(got, {"unknown-str": "crashed", "number": "crashed", "still-running": "crashed",
                               "not-object": "crashed", "good": "canceled"})
        self.assert_job_json_statuses_valid()

    def test_result_without_status_resolves_to_crashed(self):
        self.stale_bad_result("no-status", result={"error": "boom"})
        _, payload = self.status("no-status")
        self.assertEqual(payload["status"], "crashed")
        self.assertEqual(self.job_json("no-status")["status"], "crashed")

    def test_cancel_with_list_status_does_not_crash(self):
        self.add("bad-job", status=["done"], pid=DEAD_PID)
        before = (self.root / "bad-job" / "job.json").read_text()
        with mock.patch.object(jobs, "terminate_process_group") as term:
            code, payload = self.run_cmd(jobs.cmd_cancel, job_id="bad-job", grace_seconds=1)
        term.assert_not_called()
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], ["done"])
        self.assertEqual((self.root / "bad-job" / "job.json").read_text(), before)

    # Reproduction 2: job.json itself holds a list status.
    def test_list_status_in_job_json(self):
        self.add("bad-job", status=["done"], finished_at=OLD)
        self.add("old-done", status="done", finished_at=OLD)
        before = (self.root / "bad-job" / "job.json").read_text()
        code, payload = self.status()
        self.assertEqual(code, 0)
        self.assertEqual({j["job_id"] for j in payload["jobs"]}, {"bad-job", "old-done"})
        code, payload = self.status("bad-job")
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], ["done"])
        _, payload = self.prune(yes=False)
        self.assertEqual(payload["would_remove"], ["old-done"])
        _, payload = self.prune(yes=True)
        self.assertEqual(payload["removed"], ["old-done"])
        reasons = {s.get("job_id"): s["reason"] for s in payload["skipped"]}
        self.assertEqual(reasons["bad-job"], "unknown status")
        self.assertEqual((self.root / "bad-job" / "job.json").read_text(), before)

    def test_wait_with_list_status_does_not_crash(self):
        self.add("bad-job", result={"status": "done"}, status=["done"])
        code, payload = self.run_cmd(jobs.cmd_wait, job_id="bad-job", timeout="1s", timeout_seconds_override=None)
        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "done")

    def test_prune_reason_rejects_non_string_status(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        self.assertEqual(jobs._prune_reason({"status": ["done"], "finished_at": OLD}, cutoff), "unknown status")

    def test_list_jobs_skips_unrefreshable_entry(self):
        (self.root / "list-job").mkdir()
        (self.root / "list-job" / "job.json").write_text("[1]")
        self.add("old-done", status="done", finished_at=OLD)
        self.assertEqual([j["job_id"] for j in jobstore.list_jobs()], ["old-done"])

    def test_cli_reproductions(self):
        self.stale_bad_result()
        self.add("bad-job", status=["done"], finished_at=OLD)
        env = {**os.environ, "AGY_MC_JOB_ROOT": str(self.root)}
        for argv in (["status"], ["status", "stale-job"], ["status", "bad-job"],
                     ["prune", "--older-than", "1d"], ["prune", "--older-than", "1d", "--yes"]):
            proc = subprocess.run([sys.executable, "-m", "antigravity_mission_control.cli", *argv],
                                  cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertNotIn("Traceback", proc.stderr, argv)
            json.loads(proc.stdout)
        self.assertFalse((self.root / "stale-job").exists())
        self.assertTrue((self.root / "bad-job").is_dir())


if __name__ == "__main__":
    unittest.main()
