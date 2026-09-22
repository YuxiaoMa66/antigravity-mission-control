#!/usr/bin/env python3
"""Acceptance suite for Mission Control against the real AGY CLI.

The unit tests drive a fake AGY, so they only prove the wrapper is consistent
with our own assumptions. This suite drives the installed `agy` binary and
checks the contract users actually depend on: result judgement, job lifecycle,
conversation continuity, workspace evidence and the editor lock.

    python3 scripts/real_agy_check.py                 # everything
    python3 scripts/real_agy_check.py --offline-only  # no AGY calls, no quota
    python3 scripts/real_agy_check.py -k cancel       # one scenario
    python3 scripts/real_agy_check.py --report out.json
    python3 scripts/real_agy_check.py --cleanup-only  # after a killed run

Each live scenario costs one AGY turn on the selected model. State lives in a
temporary directory, so the user's own jobs are untouched. The workspace
scenarios trust a temporary Git workspace next to the repository and remove
that trust entry afterwards; a killed run is cleaned up by the next start.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OK_PROMPT = "Reply with exactly the word OK. Do not read, run or modify anything."
LONG_PROMPT = ("Write a detailed 1500-word explanation of how a job scheduler works. "
               "Do not read, run or modify anything.")

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "agy_delegate.py"
SETTINGS = Path(os.environ.get("AGY_MC_SETTINGS_PATH",
                               str(Path.home() / ".gemini" / "antigravity-cli" / "settings.json")))


class Failure(AssertionError):
    """A scenario expectation that did not hold."""


class Harness:
    def __init__(self, model: str, state_root: Path, timeout: int):
        self.model = model
        self.state_root = state_root
        self.timeout = timeout
        self.workspace = ROOT.parent  # already-trusted project directory, read-only scenarios
        self.prompts = state_root / "prompts"
        self.prompts.mkdir(parents=True, exist_ok=True)

    def prompt(self, name: str, text: str) -> Path:
        path = self.prompts / f"{name}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def amc(self, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            env={**os.environ, "AGY_MC_STATE_ROOT": str(self.state_root)},
            text=True, capture_output=True, timeout=timeout or self.timeout + 120, check=False)

    def run(self, prompt: Path, *extra: str, cwd: Path | None = None, mode: str = "plan",
            timeout_seconds: int | None = None) -> subprocess.CompletedProcess:
        return self.amc("run", "--strategy", "C", "--role", "planner", "--model", self.model,
                        "--roster-approved", "--cwd", str(cwd or self.workspace),
                        "--prompt-file", str(prompt), "--mode", mode,
                        "--timeout-seconds", str(timeout_seconds or self.timeout), *extra)

    def start_background(self, prompt: Path, **kwargs) -> str:
        started = self.run(prompt, "--background", **kwargs)
        expect(started.returncode == 0, f"background launch failed: {started.stderr[-400:]}")
        return json.loads(started.stdout)["job_id"]

    def json_out(self, proc: subprocess.CompletedProcess) -> dict:
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise Failure(f"expected JSON on stdout, got {proc.stdout[:200]!r} ({exc})") from exc

    def final_event(self, stdout: str) -> dict:
        sys.path.insert(0, str(ROOT))
        from antigravity_mission_control.jobs import parse_stream_result
        return parse_stream_result(stdout) or {}


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


SCENARIOS: list[tuple[str, bool, object]] = []


def scenario(name: str, live: bool = True):
    def register(function):
        SCENARIOS.append((name, live, function))
        return function
    return register


# --- offline scenarios: guards that must hold before any AGY turn is spent ---

@scenario("doctor_reports_ok", live=False)
def doctor_reports_ok(h: Harness) -> str:
    proc = h.amc("doctor")
    payload = h.json_out(proc)
    expect(payload["status"] in {"ok", "warn"}, f"doctor status {payload['status']}")
    failed = [c["name"] for c in payload["checks"] if not c.get("ok")]
    expect(not failed, f"failed doctor checks: {failed}")
    return f"version {payload['version']}, {len(payload['checks'])} checks"


@scenario("unavailable_model_is_refused", live=False)
def unavailable_model_is_refused(h: Harness) -> str:
    prompt = h.prompt("noop", "Reply with OK.")
    proc = h.amc("run", "--strategy", "A", "--role", "planner", "--model", "gemini-does-not-exist",
                 "--roster-approved", "--cwd", str(h.workspace), "--prompt-file", str(prompt),
                 "--mode", "plan", "--timeout-seconds", "30")
    expect(proc.returncode != 0, "an unavailable model was accepted")
    expect("unavailable" in proc.stderr, f"unexpected refusal: {proc.stderr[-200:]}")
    return "refused before dispatch"


@scenario("non_high_gemini_needs_confirmation", live=False)
def non_high_gemini_needs_confirmation(h: Harness) -> str:
    prompt = h.prompt("noop", "Reply with OK.")
    model = h.model.replace("-high", "-low")
    proc = h.amc("run", "--strategy", "A", "--role", "planner", "--model", model,
                 "--roster-approved", "--cwd", str(h.workspace), "--prompt-file", str(prompt),
                 "--mode", "plan", "--timeout-seconds", "30")
    expect(proc.returncode != 0, f"{model} ran without the explicit confirmation")
    expect("allow-non-high-gemini" in proc.stderr, f"unexpected refusal: {proc.stderr[-200:]}")
    return f"{model} refused without --allow-non-high-gemini"


@scenario("approval_binds_the_exact_prompt", live=False)
def approval_binds_the_exact_prompt(h: Harness) -> str:
    prompt = h.prompt("bound", "Reply with exactly the word OK.")
    created = h.amc("approve", "--strategy", "C", "--role", "planner", "--model", h.model,
                    "--cwd", str(h.workspace), "--prompt-file", str(prompt), "--mode", "plan",
                    "--expires-minutes", "10", "--confirmed", "--three-rosters-presented")
    expect(created.returncode == 0, f"approve failed: {created.stderr[-300:]}")
    manifest = h.json_out(created)["approval_file"]
    prompt.write_text("Reply with exactly the word CHANGED.", encoding="utf-8")
    proc = h.run(prompt, "--approval-file", manifest)
    expect(proc.returncode != 0, "a tampered prompt ran under a signed approval")
    expect("prompt_sha256" in proc.stderr, f"unexpected refusal: {proc.stderr[-200:]}")
    return "tampered prompt refused"


@scenario("broad_workspace_is_refused", live=False)
def broad_workspace_is_refused(h: Harness) -> str:
    prompt = h.prompt("noop", "Reply with OK.")
    proc = h.run(prompt, cwd=Path.home().parent)
    expect(proc.returncode != 0, f"{Path.home().parent} was accepted as a workspace")
    expect("broad workspace" in proc.stderr, f"unexpected refusal: {proc.stderr[-200:]}")
    return f"{Path.home().parent} refused"


# --- live scenarios: one AGY turn each ---

@scenario("foreground_run_succeeds")
def foreground_run_succeeds(h: Harness) -> str:
    prompt = h.prompt("ok", OK_PROMPT)
    proc = h.run(prompt)
    expect(proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr[-300:]}")
    event = h.final_event(proc.stdout)
    expect(event.get("status") == "SUCCESS", f"result status {event.get('status')!r}")
    expect(bool(event.get("response")), "successful run returned no response")
    expect(bool(event.get("conversation_id")), "no conversation id in the result event")
    return f"response {event['response'].strip()[:20]!r}"


@scenario("background_job_completes_and_records_the_conversation")
def background_job_completes(h: Harness) -> str:
    prompt = h.prompt("ok", OK_PROMPT)
    job_id = h.start_background(prompt)
    waited = h.amc("wait", job_id, "--timeout", f"{h.timeout + 60}s")
    result = h.json_out(waited)
    expect(waited.returncode == 0, f"wait exit {waited.returncode}, status {result.get('status')}")
    expect(result["status"] == "done", f"job status {result['status']}")
    expect(result["acceptance"] == "not_evaluated", "acceptance was pre-judged")
    expect(bool(result["conversation_id"]), "job recorded no conversation id")
    status = h.json_out(h.amc("status", job_id))
    expect(status["status"] == "done", f"status command disagrees: {status['status']}")
    h.last_done_job = job_id
    return f"{job_id} done, conversation recorded"


@scenario("continue_reuses_the_recorded_conversation")
def continue_reuses_conversation(h: Harness) -> str:
    job_id = getattr(h, "last_done_job", None)
    expect(job_id is not None, "no completed job from the previous scenario")
    before = h.json_out(h.amc("status", job_id))["conversation_id"]
    prompt = h.prompt("again", "Reply with exactly the word AGAIN.")
    proc = h.amc("continue", job_id, "--prompt-file", str(prompt), "--roster-approved")
    expect(proc.returncode == 0, f"continue exit {proc.returncode}: {proc.stderr[-300:]}")
    event = h.final_event(proc.stdout)
    expect(event.get("conversation_id") == before,
           f"continue used {event.get('conversation_id')} instead of {before}")
    return f"reused {before[:8]}…"


@scenario("cancel_stops_the_worker_and_agrees_everywhere")
def cancel_is_consistent(h: Harness) -> str:
    prompt = h.prompt("long", LONG_PROMPT)
    job_id = h.start_background(prompt, timeout_seconds=300)
    time.sleep(6)
    running = h.json_out(h.amc("status", job_id))
    expect(running["status"] == "running", f"job was {running['status']} before cancel")
    canceled = h.amc("cancel", job_id, "--grace-seconds", "5")
    expect(canceled.returncode == 4, f"cancel exit {canceled.returncode}")
    expect(h.json_out(canceled)["status"] == "canceled", "cancel did not confirm the exit")
    expect(not pid_alive(running.get("pid")), "the worker process is still alive after cancel")
    for command, expected_code in (("status", 4), ("result", 0), ("wait", 4)):
        extra = ["--timeout", "5s"] if command == "wait" else []
        proc = h.amc(command, job_id, *extra)
        payload = h.json_out(proc)
        expect(payload["status"] == "canceled", f"{command} reports {payload['status']}")
        expect(proc.returncode == expected_code, f"{command} exit {proc.returncode}")
    return "canceled; status, result and wait agree"


@scenario("print_timeout_is_reported_as_a_failure")
def print_timeout_is_a_failure(h: Harness) -> str:
    prompt = h.prompt("long", LONG_PROMPT)
    foreground = h.run(prompt, timeout_seconds=5)
    expect(foreground.returncode != 0, "a print timeout was reported as success")
    expect(foreground.returncode == 124, f"expected exit 124, got {foreground.returncode}")
    job_id = h.start_background(prompt, timeout_seconds=5)
    waited = h.amc("wait", job_id, "--timeout", "120s")
    result = h.json_out(waited)
    expect(result["status"] == "error", f"background job status {result['status']}")
    expect(waited.returncode == 3, f"wait exit {waited.returncode}")
    return f"foreground 124, background error (exit_code {result['exit_code']})"


@scenario("killed_worker_becomes_a_terminal_state")
def killed_worker_is_terminal(h: Harness) -> str:
    prompt = h.prompt("long", LONG_PROMPT)
    job_id = h.start_background(prompt, timeout_seconds=300)
    time.sleep(5)
    job = h.json_out(h.amc("status", job_id))
    expect(job["status"] == "running", f"job was {job['status']} before the kill")
    os.killpg(job["pid"], signal.SIGKILL)
    for _ in range(40):
        if not pid_alive(job["pid"]):
            break
        time.sleep(0.25)
    waited = h.amc("wait", job_id, "--timeout", "20s")
    result = h.json_out(waited)
    expect(result["status"] in {"crashed", "error"}, f"killed worker reported {result['status']}")
    expect(waited.returncode == 3, f"wait exit {waited.returncode}")
    return f"{result['status']} with exit 3"


@scenario("interrupted_cancel_still_reaches_a_terminal_state")
def interrupted_cancel_recovers(h: Harness) -> str:
    prompt = h.prompt("long", LONG_PROMPT)
    job_id = h.start_background(prompt, timeout_seconds=300)
    time.sleep(5)
    canceler = subprocess.Popen(
        [sys.executable, str(CLI), "cancel", job_id, "--grace-seconds", "30"],
        env={**os.environ, "AGY_MC_STATE_ROOT": str(h.state_root)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    canceler.kill()  # the cancel command dies after marking canceling and signalling the worker
    canceler.wait()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = h.json_out(h.amc("status", job_id))
        if status["status"] not in {"running", "canceling", "starting"}:
            break
        time.sleep(1)
    expect(status["status"] not in {"running", "canceling", "starting"},
           f"job stayed {status['status']} after the cancel command was killed")
    waited = h.amc("wait", job_id, "--timeout", "10s")
    expect(h.json_out(waited)["status"] == status["status"],
           "wait and status disagree after the interrupted cancel")
    return f"recovered to {status['status']}"


@scenario("wait_timeout_is_only_an_observation_timeout")
def wait_timeout_is_observational(h: Harness) -> str:
    prompt = h.prompt("long", LONG_PROMPT)
    job_id = h.start_background(prompt, timeout_seconds=300)
    early = h.amc("wait", job_id, "--timeout", "2s")
    payload = h.json_out(early)
    expect(early.returncode == 2, f"early wait exit {early.returncode}")
    expect(payload["status"] in {"starting", "running"}, f"early wait saw {payload['status']}")
    canceled = h.amc("cancel", job_id, "--grace-seconds", "5")
    expect(canceled.returncode == 4, f"cleanup cancel exit {canceled.returncode}")
    return "exit 2 while running, job still cancellable afterwards"


@scenario("parallel_plan_jobs_do_not_block_each_other")
def parallel_plan_jobs(h: Harness) -> str:
    first = h.start_background(h.prompt("ok", OK_PROMPT))
    second = h.start_background(h.prompt("ok2", "Reply with exactly the word TWO."))
    expect(first != second, "both launches returned the same job id")
    statuses = []
    for job_id in (first, second):
        waited = h.amc("wait", job_id, "--timeout", f"{h.timeout + 60}s")
        result = h.json_out(waited)
        expect(waited.returncode == 0, f"{job_id} exit {waited.returncode} ({result.get('status')})")
        statuses.append(result["status"])
    expect(statuses == ["done", "done"], f"parallel plan jobs ended {statuses}")
    listed = h.json_out(h.amc("status"))["jobs"]
    expect({first, second} <= {j["job_id"] for j in listed}, "the job listing lost a job")
    return "two read-only jobs ran together"


@scenario("json_schema_result_is_never_misreported")
def json_schema_output(h: Harness) -> str:
    # AGY does not always honour --json-schema (seen: the object twice, or a plan in prose).
    # The contract under test is Mission Control's: a non-JSON answer is never a clean success.
    schema_path = h.state_root / "schema.json"
    schema_path.write_text(json.dumps({
        "type": "object", "required": ["answer"], "additionalProperties": False,
        "properties": {"answer": {"type": "string"}}}), encoding="utf-8")
    prompt = h.prompt("schema", "Answer with the single word OK in the answer field.")
    proc = h.run(prompt, "--json-schema", str(schema_path))
    if proc.returncode != 0:
        return f"AGY failed and Mission Control reported it (exit {proc.returncode})"
    response = h.final_event(proc.stdout).get("response") or ""
    flagged = "not a single JSON document" in proc.stderr
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        expect(flagged, f"a non-JSON schema answer was reported as a clean success: {response[:120]!r}")
        return "AGY ignored the schema; Mission Control flagged done_with_warnings"
    expect(not flagged, "a valid JSON answer was flagged")
    expect(isinstance(payload, dict) and "answer" in payload, f"schema field missing: {payload}")
    return f"answer {str(payload['answer'])[:20]!r}"


@scenario("usage_snapshot_is_sanitized", live=False)
def usage_snapshot_is_sanitized(h: Harness) -> str:
    proc = h.amc("usage", "--format", "json")
    payload = h.json_out(proc)
    expect(proc.returncode == 0, f"usage exit {proc.returncode}")
    groups = payload.get("groups") or []
    expect(bool(groups), f"no quota groups in the snapshot: {str(payload)[:200]}")
    for group in groups:
        for bucket in group.get("buckets", []):
            fraction = bucket.get("remaining_fraction")
            expect(fraction is None or 0.0 <= fraction <= 1.0,
                   f"remaining_fraction out of range: {group.get('name')} {fraction}")
    return f"{len(groups)} quota groups"


@scenario("plan_mode_writes_are_never_reported_as_success")
def plan_mode_is_read_only(h: Harness) -> str:
    # AGY does not enforce plan mode: real plan workers have created files. The contract under
    # test is Mission Control's: a plan run that changed the workspace always fails with exit 5.
    with trusted_workspace(h) as workspace:
        marker = "plan-mode-should-not-exist.txt"
        prompt = h.prompt("plan-edit", f"Create a file named {marker} in the workspace root with the "
                                       f"text: nope. Then reply with DONE.")
        proc = h.run(prompt, cwd=workspace, mode="plan", timeout_seconds=120)
        if (workspace / marker).is_file():
            expect(proc.returncode == 5, f"plan mode created {marker} and the run exited {proc.returncode}")
            expect(marker in proc.stderr, "the plan-mode failure did not name the changed path")
            return "AGY wrote in plan mode; Mission Control failed the run with exit 5"
        expect(proc.returncode != 5, "exit 5 without any change in the workspace")
        return f"workspace unchanged after an edit request in plan mode (exit {proc.returncode})"


@scenario("evidence_separates_worker_changes_from_user_changes")
def evidence_separates_changes(h: Harness) -> str:
    with trusted_workspace(h) as workspace:
        (workspace / "user-untracked.txt").write_text("user work in progress\n", encoding="utf-8")
        (workspace / "README.md").write_text("edited by the user before the run\n", encoding="utf-8")
        marker = "worker-output.txt"
        prompt = h.prompt("edit2", f"Create a file named {marker} in the workspace root containing "
                                   f"exactly the line: worker wrote this. Do not modify any other file. "
                                   f"Then reply with DONE.")
        job_id = h.start_background(prompt, cwd=workspace, mode="accept-edits", timeout_seconds=180)
        result = h.json_out(h.amc("wait", job_id, "--timeout", "240s"))
        expect(result["status"] in {"done", "done_with_warnings"}, f"edit job {result['status']}")
        delta = json.loads((Path(result["evidence_path"]) / "delta.json").read_text(encoding="utf-8"))
        changed = delta["changed_paths"]
        expect(marker in changed, f"the worker's file is missing from the evidence: {changed}")
        expect("user-untracked.txt" not in changed,
               "a file the user already had is claimed as a worker change")
        expect((workspace / "user-untracked.txt").read_text() == "user work in progress\n",
               "the worker overwrote the user's untracked file")
        return f"worker change recorded, {len(changed)} changed path(s), user file intact"


@scenario("edits_are_serialized_and_recorded_as_evidence")
def edits_are_serialized(h: Harness) -> str:
    with trusted_workspace(h) as workspace:
        marker = "amc-real-check.txt"
        prompt = h.prompt("edit", f"Create a file named {marker} in the workspace root containing "
                                  f"exactly the line: real agy check. Then reply with DONE.")
        job_id = h.start_background(prompt, cwd=workspace, mode="accept-edits", timeout_seconds=180)
        blocked = h.run(prompt, cwd=workspace, mode="accept-edits", timeout_seconds=60)
        expect(blocked.returncode != 0, "a second editing job started in the same workspace")
        expect("active editing lock" in blocked.stderr, f"unexpected refusal: {blocked.stderr[-200:]}")

        waited = h.amc("wait", job_id, "--timeout", "240s")
        result = h.json_out(waited)
        expect(result["status"] in {"done", "done_with_warnings"}, f"edit job {result['status']}")
        expect((workspace / marker).is_file(), f"{marker} was not created")
        delta = json.loads((Path(result["evidence_path"]) / "delta.json").read_text(encoding="utf-8"))
        expect(marker in delta["changed_paths"], f"evidence missed the edit: {delta['changed_paths']}")
        expect(result["acceptance"] == "not_evaluated", "acceptance was pre-judged")

        after_lock = h.run(h.prompt("ok", "Reply with exactly the word OK."), cwd=workspace,
                           mode="accept-edits", timeout_seconds=60)
        expect(after_lock.returncode == 0, f"the lock was not released: {after_lock.stderr[-200:]}")
        return f"lock held during the edit, {marker} in the evidence delta"


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


CHECK_WORKSPACE = ROOT.parent / ".amc-real-agy-check"


def purge_check_workspace() -> bool:
    """Remove the edit workspace and its trust entry; True if anything was left over.

    Runs after each edit scenario and again at startup, because a killed run
    (SIGKILL, the app quitting) never reaches the context manager's exit.
    """
    leftover = CHECK_WORKSPACE.exists()
    shutil.rmtree(CHECK_WORKSPACE, ignore_errors=True)
    try:  # leave the user's settings exactly as they were
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return leftover
    entries = settings.get("trustedWorkspaces")
    if not isinstance(entries, list):
        return leftover
    kept = [e for e in entries if str(e).rstrip("/") != str(CHECK_WORKSPACE).rstrip("/")]
    if len(kept) != len(entries):
        settings["trustedWorkspaces"] = kept
        SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        leftover = True
    return leftover


class trusted_workspace:
    """A temporary Git workspace, trusted for the test and untrusted again afterwards."""

    def __init__(self, harness: Harness):
        self.harness = harness
        self.path = CHECK_WORKSPACE

    def __enter__(self) -> Path:
        shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.path, check=True)
        (self.path / "README.md").write_text("workspace for real AGY checks\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.path, check=True)
        subprocess.run(["git", "-c", "user.email=amc@example.com", "-c", "user.name=amc",
                        "commit", "-qm", "baseline"], cwd=self.path, check=True)
        granted = self.harness.amc("workspace", "--cwd", str(self.path), "--mode", "accept-edits",
                                   "--grant", "--trust-approved")
        expect(granted.returncode == 0, f"trust grant failed: {granted.stderr[-300:]}")
        return self.path

    def __exit__(self, *_exc) -> None:
        purge_check_workspace()


def latest_flash_high(state_root: Path) -> str:
    proc = subprocess.run([sys.executable, str(CLI), "models"],
                          env={**os.environ, "AGY_MC_STATE_ROOT": str(state_root)},
                          text=True, capture_output=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"cannot list AGY models: {proc.stderr[-300:]}")
    ids = [m["id"] for m in json.loads(proc.stdout)["models"]]
    flash_high = [i for i in ids if i.startswith("gemini-") and i.endswith("-flash-high")]
    if not flash_high:
        raise SystemExit(f"no Gemini Flash High model available: {ids}")
    return sorted(flash_high, reverse=True)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="AGY model slug (default: the latest Gemini Flash High)")
    parser.add_argument("--timeout-seconds", type=int, default=120, help="per-run AGY timeout")
    parser.add_argument("--offline-only", action="store_true", help="skip every scenario that calls AGY")
    parser.add_argument("-k", "--filter", help="run only scenarios whose name contains this text")
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    parser.add_argument("--keep-state", action="store_true", help="keep the temporary job state")
    parser.add_argument("--cleanup-only", action="store_true",
                        help="remove what a killed run left behind (workspace, trust entry) and exit")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # stream progress when redirected to a log

    if purge_check_workspace():
        print(f"removed leftovers of an interrupted run: {CHECK_WORKSPACE} and its trust entry")
    if args.cleanup_only:
        return 0

    state_root = Path(tempfile.mkdtemp(prefix="amc-real-check-"))
    model = args.model or latest_flash_high(state_root)
    harness = Harness(model, state_root, args.timeout_seconds)
    print(f"model {model} · state {state_root} · workspace {harness.workspace}\n")

    results = []
    for name, live, function in SCENARIOS:
        if args.filter and args.filter not in name:
            continue
        if live and args.offline_only:
            results.append({"scenario": name, "outcome": "skipped", "detail": "offline-only"})
            print(f"  skip  {name}")
            continue
        started = time.monotonic()
        try:
            detail = function(harness)
            outcome = "pass"
        except Failure as failure:
            detail, outcome = str(failure), "fail"
        except Exception as error:  # a crash is a result too, keep going
            detail, outcome = f"{type(error).__name__}: {error}", "error"
        seconds = round(time.monotonic() - started, 1)
        results.append({"scenario": name, "outcome": outcome, "detail": detail, "seconds": seconds})
        print(f"  {'PASS' if outcome == 'pass' else outcome.upper():4}  {name}  ({seconds}s)\n        {detail}")

    failed = [r for r in results if r["outcome"] in {"fail", "error"}]
    report = {"schema": "agy-mc-real-check.v1", "model": model, "agy_binary": os.environ.get("AGY_MC_BIN", "agy"),
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": results,
              "passed": len(results) - len(failed) - sum(r["outcome"] == "skipped" for r in results),
              "failed": len(failed)}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nreport written to {args.report}")
    if args.keep_state:
        print(f"state kept at {state_root}")
    else:
        shutil.rmtree(state_root, ignore_errors=True)
    print(f"\n{report['passed']} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
