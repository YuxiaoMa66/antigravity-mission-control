#!/usr/bin/env python3
import json
import os
import sys
import time

if "--version" in sys.argv:
    print("agy 1.1.19-fake")
elif "--help" in sys.argv:
    print("--add-dir --input-format --output-format --model")
elif "/usage" in sys.argv:
    print(json.dumps({
        "command": {"data": {"groups": [
            {"name": "Gemini 3.7", "buckets": [
                {"id": "five-hour", "window": "5h", "remaining_fraction": 0.625,
                 "reset_time": "2026-08-23T12:00:00Z"},
                {"id": "weekly", "window": "7d", "remaining_fraction": 0.07125,
                 "reset_time": "2026-08-25T12:00:00Z"}
            ]},
            {"name": "Disabled model", "buckets": [
                {"id": "weekly", "window": "7d", "remaining_fraction": None, "disabled": True}
            ]}
        ]}}
    }))
elif "models" in sys.argv:
    if os.environ.get("FAKE_AGY_MODELS_ERROR"):
        print(json.dumps({"status": "ERROR", "error": "not authenticated"}), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({"command": {"data": {"models": [{"id": "gemini-3.7-flash-high"}]}}}))
elif "stream-json" in sys.argv:
    request = sys.stdin.readline()
    time.sleep(float(os.environ.get("FAKE_AGY_SLEEP", "0")))
    if os.environ.get("FAKE_AGY_EDIT"):
        from pathlib import Path
        Path("user.txt").write_text("worker change\n")
        Path("worker-new.txt").write_text("new output\n")
    if os.environ.get("FAKE_AGY_CUSTOM_ACTION"):
        action = json.loads(os.environ["FAKE_AGY_CUSTOM_ACTION"])
        from pathlib import Path
        import subprocess
        for item in action.get("write", []):
            target = Path(item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item["content"])
        for p in action.get("delete", []):
            target = Path(p)
            if target.is_symlink() or target.is_file():
                target.unlink()
        for item in action.get("symlink", []):
            target = Path(item["link"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or target.is_file():
                target.unlink()
            target.symlink_to(item["target"])
        if action.get("git_commit"):
            subprocess.run(["git", "commit", "-am", action["git_commit"]], check=False)
        if action.get("exit_code"):
            print("fake provider error", file=sys.stderr)
            sys.exit(int(action["exit_code"]))
    if os.environ.get("FAKE_AGY_PROVIDER_EXIT"):
        print("fake provider error", file=sys.stderr)
        sys.exit(int(os.environ["FAKE_AGY_PROVIDER_EXIT"]))
    print(json.dumps({"event": "init", "conversation_id": "fake-conversation"}))
    if os.environ.get("FAKE_AGY_NESTED_RESULT"):
        nested = json.loads(os.environ["FAKE_AGY_NESTED_RESULT"])
        print(json.dumps({"event": "result", "result": nested}))
    else:
        print(json.dumps({"event": "result", "status": "ERROR" if os.environ.get("FAKE_AGY_WARNING") else "SUCCESS", "conversation_id": "fake-conversation", "response": request}))
else:
    print(json.dumps({"status": "SUCCESS", "response": "fake"}))
