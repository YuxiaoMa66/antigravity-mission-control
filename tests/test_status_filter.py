import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "agy_delegate.py"


class StatusFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job_root = Path(self.temp.name) / "jobs"
        self.job_root.mkdir()
        self.jobs = [
            {"job_id": "job-old", "status": "done", "started_at": "2026-01-01T00:00:00Z"},
            {"job_id": "job-error", "status": "error", "started_at": "2026-01-02T00:00:00Z"},
            {"job_id": "job-latest-done", "status": "done_with_warnings", "started_at": "2026-01-03T00:00:00Z"},
            {"job_id": "job-canceled", "status": "canceled", "started_at": "2026-01-04T00:00:00Z"},
        ]
        for job in self.jobs:
            directory = self.job_root / job["job_id"]
            directory.mkdir()
            (directory / "job.json").write_text(json.dumps(job), encoding="utf-8")
        self.env = os.environ.copy()
        self.env["AGY_MC_JOB_ROOT"] = str(self.job_root)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), "status", *args], cwd=ROOT, env=self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )

    def payload(self, *args):
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_default_output_is_unchanged(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.dumps({"jobs": self.jobs}, ensure_ascii=False, indent=2)
        self.assertEqual(result.stdout, expected + "\n")

    def test_limit_keeps_most_recent_in_ascending_order(self):
        jobs = self.payload("--limit", "2")["jobs"]
        self.assertEqual([job["job_id"] for job in jobs], ["job-latest-done", "job-canceled"])

    def test_state_accepts_one_or_repeated_values(self):
        self.assertEqual(
            [job["job_id"] for job in self.payload("--state", "done")["jobs"]], ["job-old"]
        )
        self.assertEqual(
            [job["job_id"] for job in self.payload("--state", "done", "--state", "canceled")["jobs"]],
            ["job-old", "job-canceled"],
        )

    def test_state_and_limit_filter_then_limit(self):
        jobs = self.payload("--state", "done", "--state", "done_with_warnings", "--limit", "1")["jobs"]
        self.assertEqual([job["job_id"] for job in jobs], ["job-latest-done"])

    def test_invalid_limit_is_usage_error(self):
        for value in ("0", "-1"):
            with self.subTest(value=value):
                result = self.cli("--limit", value)
                self.assertEqual(result.returncode, 2)
                self.assertIn("must be a positive integer", result.stderr)

    def test_job_id_cannot_be_combined_with_filter(self):
        for flag in (("--limit", "1"), ("--state", "done")):
            with self.subTest(flag=flag):
                result = self.cli("job-old", *flag)
                self.assertEqual(result.returncode, 2)
                self.assertIn("status filters cannot be used with a job_id", result.stderr)


if __name__ == "__main__":
    unittest.main()
