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
CLI = ROOT / "scripts" / "agy_delegate.py"


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


class PruneTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "jobs"
        self.root.mkdir()
        patcher = mock.patch.object(jobstore, "JOB_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.add("old-done", status="done", finished_at=ago(days=10))
        self.add("old-error", status="error", finished_at=ago(days=10).replace("+00:00", "Z"))
        self.add("recent-done", status="done", finished_at=ago(hours=1))
        self.add("no-finish", status="canceled")
        self.add("bad-finish", status="done", finished_at="yesterday")
        # A live pid keeps refresh_job from resolving these as crashed.
        for status in ("starting", "running", "canceling"):
            self.add(f"live-{status}", status=status, pid=os.getpid(), finished_at=ago(days=100))
        self.add("mismatch", job_id="someone-else", status="done", finished_at=ago(days=10))
        (self.root / "no-json").mkdir()
        (self.root / "corrupt").mkdir()
        (self.root / "corrupt" / "job.json").write_text("{nope")
        (self.root / "stray-file").write_text("x")
        self.outside = self.base / "outside"
        self.outside.mkdir()
        (self.outside / "job.json").write_text(json.dumps(
            {"job_id": "linked-job", "status": "done", "finished_at": ago(days=10)}))
        (self.root / "linked-job").symlink_to(self.outside, target_is_directory=True)

    def add(self, name, **job):
        job.setdefault("job_id", name)
        (self.root / name).mkdir()
        (self.root / name / "job.json").write_text(json.dumps(job))
        (self.root / name / "result.json").write_text("{}")

    def prune(self, older_than="7d", yes=False):
        out = io.StringIO()
        seconds = jobs.parse_duration(older_than)
        with contextlib.redirect_stdout(out):
            code = jobs.cmd_prune(argparse.Namespace(older_than=seconds, yes=yes))
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def entries(self):
        return sorted(os.listdir(self.root))

    def test_dry_run_deletes_nothing(self):
        before = self.entries()
        payload = self.prune()
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["older_than_seconds"], 7 * 86400.0)
        self.assertEqual(sorted(payload["would_remove"]), ["old-done", "old-error"])
        self.assertEqual(payload["removed"], [])
        self.assertEqual(self.entries(), before)

    def test_yes_deletes_only_old_finished_jobs(self):
        payload = self.prune(yes=True)
        self.assertFalse(payload["dry_run"])
        self.assertEqual(sorted(payload["removed"]), ["old-done", "old-error"])
        self.assertEqual(payload["would_remove"], [])
        self.assertEqual(self.entries(), sorted([
            "recent-done", "no-finish", "bad-finish", "live-starting", "live-running", "live-canceling",
            "mismatch", "no-json", "corrupt", "stray-file", "linked-job"]))

    def test_unfinished_jobs_never_deleted_however_old(self):
        payload = self.prune(older_than="1ms", yes=True)
        reasons = {s.get("job_id"): s["reason"] for s in payload["skipped"]}
        for status in ("starting", "running", "canceling"):
            self.assertTrue((self.root / f"live-{status}").is_dir())
            self.assertEqual(reasons[f"live-{status}"], "unfinished")

    def test_recent_and_missing_finished_at_kept(self):
        payload = self.prune(yes=True)
        reasons = {s.get("job_id"): s["reason"] for s in payload["skipped"]}
        self.assertEqual(reasons["recent-done"], "too recent")
        self.assertEqual(reasons["no-finish"], "missing or unparseable finished_at")
        self.assertEqual(reasons["bad-finish"], "missing or unparseable finished_at")
        for name in ("recent-done", "no-finish", "bad-finish"):
            self.assertTrue((self.root / name).is_dir())

    def test_mismatched_missing_and_corrupt_metadata_kept(self):
        payload = self.prune(yes=True)
        entries = {s.get("entry") for s in payload["skipped"]}
        self.assertTrue({"mismatch", "no-json", "corrupt", "stray-file"} <= entries)
        for name in ("mismatch", "no-json", "corrupt"):
            self.assertTrue((self.root / name).is_dir())

    def test_symlink_is_not_followed_or_deleted(self):
        payload = self.prune(older_than="1ms", yes=True)
        self.assertIn({"entry": "linked-job", "reason": "not a real directory"}, payload["skipped"])
        self.assertNotIn("linked-job", payload["removed"])
        self.assertTrue((self.root / "linked-job").is_symlink())
        self.assertTrue((self.outside / "job.json").is_file())

    def test_recheck_under_lock_keeps_job_that_became_unfinished(self):
        real_lock = jobs._locked_job_dir

        @contextlib.contextmanager
        def lock_then_restart(root_fd, name):
            with real_lock(root_fd, name) as dir_fd:
                if name == "old-done":
                    (self.root / name / "job.json").write_text(json.dumps(
                        {"job_id": name, "status": "running", "pid": os.getpid()}))
                yield dir_fd

        with mock.patch.object(jobs, "_locked_job_dir", lock_then_restart):
            payload = self.prune(yes=True)
        self.assertEqual(payload["removed"], ["old-error"])
        self.assertTrue((self.root / "old-done").is_dir())

    def test_cancel_failed_job_with_live_pid_kept(self):
        self.add("stuck", status="cancel_failed", pid=os.getpid(), finished_at=ago(days=100))
        self.add("stuck-launcher", status="done", launcher_pid=os.getpid(), finished_at=ago(days=100))
        payload = self.prune(older_than="1ms", yes=True)
        reasons = {s.get("job_id"): s["reason"] for s in payload["skipped"]}
        for name in ("stuck", "stuck-launcher"):
            self.assertEqual(reasons[name], "unfinished")
            self.assertTrue((self.root / name).is_dir())

    def outside_decoy(self, name):
        decoy = self.base / f"decoy-{name}"
        decoy.mkdir()
        (decoy / "job.json").write_text(json.dumps(
            {"job_id": name, "status": "done", "finished_at": ago(days=10)}))
        return decoy

    def test_candidate_swapped_for_symlink_before_lock(self):
        decoy = self.outside_decoy("old-done")
        real_refresh = jobs.refresh_job

        def refresh_then_swap(job):
            job = real_refresh(job)
            if job.get("job_id") == "old-done":
                (self.root / "old-done").rename(self.base / "moved-old-done")
                (self.root / "old-done").symlink_to(decoy, target_is_directory=True)
            return job

        with mock.patch.object(jobs, "refresh_job", refresh_then_swap):
            payload = self.prune(yes=True)
        self.assertEqual(payload["removed"], ["old-error"])
        self.assertIn("old-done", {s.get("job_id") for s in payload["skipped"]})
        self.assertEqual(sorted(os.listdir(decoy)), ["job.json"])
        self.assertTrue((self.root / "old-done").is_symlink())
        self.assertTrue((self.base / "moved-old-done" / "job.json").is_file())
        self.assertFalse(any(n.startswith(".prune-") for n in self.entries()))

    def test_candidate_swapped_for_symlink_after_lock(self):
        decoy = self.outside_decoy("old-done")
        real_reason = jobs._prune_reason
        calls = []

        def reason_then_swap(job, cutoff):
            calls.append(job.get("job_id"))
            if job.get("job_id") == "old-done" and calls.count("old-done") == 2:
                (self.root / "old-done").rename(self.base / "moved-old-done")
                (self.root / "old-done").symlink_to(decoy, target_is_directory=True)
            return real_reason(job, cutoff)

        with mock.patch.object(jobs, "_prune_reason", reason_then_swap):
            payload = self.prune(yes=True)
        self.assertEqual(payload["removed"], ["old-error"])
        self.assertIn({"job_id": "old-done", "reason": "directory changed during prune"}, payload["skipped"])
        self.assertEqual(sorted(os.listdir(decoy)), ["job.json"])
        self.assertTrue((self.root / "old-done").is_symlink())
        self.assertEqual(sorted(os.listdir(self.base / "moved-old-done")), ["job.json", "job.lock", "result.json"])
        self.assertFalse(any(n.startswith(".prune-") for n in self.entries()))

    def test_leftover_prune_entry_reported_as_skipped(self):
        (self.root / ".prune-old-done-abc").mkdir()
        payload = self.prune(yes=True)
        self.assertIn(".prune-old-done-abc", {s.get("entry") for s in payload["skipped"]})
        self.assertTrue((self.root / ".prune-old-done-abc").is_dir())

    def test_missing_job_root_is_empty_report(self):
        with mock.patch.object(jobstore, "JOB_ROOT", self.base / "absent"):
            payload = self.prune(yes=True)
        self.assertEqual((payload["removed"], payload["skipped"]), ([], []))


class PruneCliTests(unittest.TestCase):
    def cli(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "AGY_MC_JOB_ROOT": tmp}
            return subprocess.run([sys.executable, str(CLI), "prune", *args], cwd=ROOT, env=env,
                                  text=True, capture_output=True, check=False)

    def test_invalid_duration_is_usage_error(self):
        for value in ("0s", "-1d", "7", "soon", "0.0m"):
            with self.subTest(value=value):
                result = self.cli(f"--older-than={value}")
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("must be a positive duration", result.stderr)

    def test_older_than_is_required(self):
        self.assertEqual(self.cli().returncode, 2)

    def test_cli_dry_run_prints_report(self):
        result = self.cli("--older-than", "1d")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "dry_run": True, "older_than_seconds": 86400.0, "removed": [], "would_remove": [], "skipped": []})


if __name__ == "__main__":
    unittest.main()
