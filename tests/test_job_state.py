import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from antigravity_mission_control import jobs, jobstore

ROOT = Path(__file__).resolve().parents[1]


class ResultJudgementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("plan a bounded change")
        settings = self.root / "settings.json"
        settings.write_text(json.dumps({"trustedWorkspaces": [str(self.workspace) + os.sep]}))
        self.env = {**os.environ, "AGY_MC_BIN": str(ROOT / "tests/fake_agy.py"),
                    "AGY_MC_STATE_ROOT": str(self.root / "state"),
                    "AGY_MC_JOB_ROOT": str(self.root / "state/jobs"),
                    "AGY_MC_SETTINGS_PATH": str(settings)}

    def call(self, *args, **fake):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/agy_delegate.py"), *args],
            env={**self.env, **fake}, text=True, capture_output=True, timeout=40)

    def run_plan(self, *extra, **fake):
        return self.call("run", "--strategy", "A", "--role", "planner", "--model", "gemini-3.7-flash-high",
                         "--roster-approved", "--cwd", str(self.workspace), "--prompt-file", str(self.prompt),
                         "--mode", "plan", "--timeout-seconds", "30", *extra, **fake)

    def test_nonzero_exit_with_partial_response_fails_and_keeps_evidence(self):
        run = self.run_plan(FAKE_AGY_WARNING="1", FAKE_AGY_EXIT="7")
        self.assertEqual(run.returncode, 7, run.stderr)
        self.assertIn('"response"', run.stdout)
        self.assertNotIn("done_with_warnings", run.stderr)

    def test_error_status_without_response_or_error_field_fails(self):
        run = self.run_plan(FAKE_AGY_STATUS="ERROR", FAKE_AGY_RESPONSE="")
        self.assertNotEqual(run.returncode, 0, run.stderr)

    def test_unknown_provider_status_fails(self):
        run = self.run_plan(FAKE_AGY_STATUS="CANCELLED")
        self.assertNotEqual(run.returncode, 0, run.stderr)

    def test_error_status_with_response_and_clean_exit_is_a_warning(self):
        run = self.run_plan(FAKE_AGY_WARNING="1")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("done_with_warnings", run.stderr)

    def test_print_timeout_notice_is_a_failure(self):
        # Real AGY 1.2 exits 0 with SUCCESS and an empty response when its print timeout cuts the turn.
        run = self.run_plan(FAKE_AGY_RESPONSE="",
                            FAKE_AGY_STDERR="[agy] print timeout after 5s with turn in progress; returning partial output")
        self.assertEqual(run.returncode, 124, run.stderr)

    def test_last_open_step_names_what_the_turn_was_stuck_on(self):
        stream = "\n".join(json.dumps(e) for e in (
            {"event": "step_update", "step_update": {"step_index": 1, "state": "DONE", "step_type": "tool",
                                                     "tool_name": "view_file"}},
            {"event": "step_update", "step_update": {"step_index": 2, "state": "ACTIVE", "step_type": "tool",
                                                     "tool_name": "run_command",
                                                     "tool_info": {"parameters": {"CommandLine": "git diff"}}}},
            {"event": "result", "result": {"status": "SUCCESS", "response": ""}},
        ))
        self.assertEqual(jobs.last_open_step(stream),
                         {"step": "run_command", "state": "ACTIVE", "parameters": {"CommandLine": "git diff"}})
        self.assertIsNone(jobs.last_open_step(stream.split("\n")[0]))

    def test_success_without_a_response_is_a_warning(self):
        run = self.run_plan(FAKE_AGY_RESPONSE="")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("empty response", run.stderr)

    def test_schema_run_with_a_non_json_response_is_a_warning(self):
        schema = self.root / "schema.json"
        schema.write_text('{"type": "object"}')
        run = self.run_plan("--json-schema", str(schema), FAKE_AGY_RESPONSE="I wrote a plan instead.")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("not a single JSON document", run.stderr)
        valid = self.run_plan("--json-schema", str(schema), FAKE_AGY_RESPONSE='{"answer": "OK"}')
        self.assertNotIn("done_with_warnings", valid.stderr)

    def test_plan_mode_run_that_changes_the_workspace_fails(self):
        subprocess.run(["git", "init", "-q"], cwd=self.workspace, check=True)
        run = self.run_plan(FAKE_AGY_EDIT="1")
        self.assertEqual(run.returncode, jobs.PLAN_MODE_CHANGED_EXIT, run.stderr)
        self.assertIn("worker-new.txt", run.stderr)
        for name in ("user.txt", "worker-new.txt"):  # start the background run from a clean tree again
            (self.workspace / name).unlink()
        started = self.run_plan("--background", FAKE_AGY_EDIT="1")
        job_id = json.loads(started.stdout)["job_id"]
        result = json.loads(self.call("wait", job_id, "--timeout", "20s").stdout)
        self.assertEqual((result["status"], result["exit_code"]), ("error", jobs.PLAN_MODE_CHANGED_EXIT))
        clean = self.run_plan()
        self.assertEqual(clean.returncode, 0, clean.stderr)

    def test_worker_prompt_carries_no_private_state_paths(self):
        # The fake AGY echoes the dispatched request back as its response.
        clean = self.run_plan()
        request = self.response(clean)
        self.assertNotIn("AMC workspace context", request)
        self.assertNotIn(str(self.root / "state"), request)

        subprocess.run(["git", "init", "-q"], cwd=self.workspace, check=True)
        (self.workspace / "user.txt").write_text("user work\n")
        dirty = self.response(self.run_plan())
        self.assertIn("user.txt", dirty)
        self.assertNotIn(str(self.root / "state"), dirty)
        self.assertNotIn("before.json", dirty)

    def response(self, run):
        self.assertEqual(run.returncode, 0, run.stderr)
        return jobs.parse_stream_result(run.stdout)["response"]

    def test_background_worker_records_nonzero_exit_as_error(self):
        started = self.run_plan("--background", FAKE_AGY_WARNING="1", FAKE_AGY_EXIT="7")
        self.assertEqual(started.returncode, 0, started.stderr)
        job_id = json.loads(started.stdout)["job_id"]
        waited = self.call("wait", job_id, "--timeout", "20s")
        result = json.loads(waited.stdout)
        self.assertEqual(waited.returncode, jobstore.JOB_EXIT_CODES["error"], waited.stdout)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["exit_code"], 7)
        self.assertIn('"response"', result["stdout"])


class LifecycleRaceTests(unittest.TestCase):
    def test_cancel_in_the_launch_gap_is_not_overwritten(self):
        """Cancel lands after the launcher read 'starting' and before it wrote 'running'."""
        job_id = "planner-gap-job"
        real_read = jobstore.read_job
        real_popen = subprocess.Popen
        main = threading.current_thread()
        children = []
        canceler = threading.Thread(
            target=lambda: jobs.cmd_cancel(argparse.Namespace(job_id=job_id, grace_seconds=2)))

        def spawn(command, *args, **kwargs):
            if "_worker" not in command:  # the patch is global; let cancel's `ps` through
                return real_popen(command, *args, **kwargs)
            # Looks like a worker to process_matches_job; a thread reaps it so it cannot linger as a zombie.
            child = real_popen(["sh", "-c", "sleep 30; exit 0", "_worker", job_id], start_new_session=True)
            threading.Thread(target=child.wait, daemon=True).start()
            children.append(child)
            return child

        def read_then_cancel(requested):
            job = real_read(requested)
            if threading.current_thread() is main and job.get("status") == "starting" and not canceler.is_alive():
                canceler.start()
                canceler.join(1.0)  # without a job lock the cancel completes inside this gap
            return job

        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(role="planner", strategy="A", mode="plan", conversation=None,
                                      allow_non_high_gemini=False, unrestricted=False, timeout_seconds=30)
            prepared = {"cwd": Path(directory), "model": "fake", "prompt_text": "hi", "schema_path": None}
            with mock.patch.object(jobstore, "JOB_ROOT", Path(directory) / "jobs"), \
                    mock.patch.object(jobstore.subprocess, "Popen", side_effect=spawn), \
                    mock.patch.object(jobstore, "read_job", side_effect=read_then_cancel), \
                    contextlib.redirect_stdout(io.StringIO()):
                jobstore.launch_background_job(args, prepared, job_id, None, None)
                canceler.join(10)
                status = real_read(job_id)["status"]
                result = jobstore.job_result(job_id)["status"]
        self.assertEqual(status, "canceled")
        self.assertEqual(result, "canceled")
        children[0].wait(5)

    def test_canceling_job_with_dead_worker_is_recovered(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(jobstore, "JOB_ROOT", Path(directory)):
            base = {"status": "canceling", "pid": dead.pid, "launcher_pid": dead.pid,
                    "role": "planner", "model": "fake", "cwd": directory}
            jobstore.write_job(dict(base, job_id="planner-cancel-cut"))
            job = jobstore.refresh_job(jobstore.read_job("planner-cancel-cut"))
            self.assertEqual(job["status"], "canceled")
            self.assertEqual(jobstore.job_result("planner-cancel-cut")["status"], "canceled")

            jobstore.write_job(dict(base, job_id="planner-cancel-late"))
            jobstore.atomic_write_json(jobstore.job_result_path("planner-cancel-late"),
                                       {"job_id": "planner-cancel-late", "status": "done", "exit_code": 0})
            self.assertEqual(jobstore.refresh_job(jobstore.read_job("planner-cancel-late"))["status"], "done")

            waited = io.StringIO()
            with contextlib.redirect_stdout(waited):
                code = jobs.cmd_wait(argparse.Namespace(job_id="planner-cancel-cut", timeout="1s",
                                                        timeout_seconds_override=None))
            self.assertEqual(code, jobstore.JOB_EXIT_CODES["canceled"])
            self.assertEqual(json.loads(waited.getvalue())["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
