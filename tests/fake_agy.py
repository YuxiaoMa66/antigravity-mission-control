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
    print(json.dumps({"event": "init", "conversation_id": "fake-conversation"}))
    print(json.dumps({"event": "result", "status": "ERROR" if os.environ.get("FAKE_AGY_WARNING") else "SUCCESS", "conversation_id": "fake-conversation", "response": request}))
else:
    print(json.dumps({"status": "SUCCESS", "response": "fake"}))
