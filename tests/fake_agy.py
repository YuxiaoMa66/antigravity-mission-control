#!/usr/bin/env python3
import json
import sys

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
    print(json.dumps({"command": {"data": {"models": [{"id": "gemini-3.7-flash-high"}]}}}))
else:
    print(json.dumps({"status": "SUCCESS", "response": "fake"}))
