#!/usr/bin/env python3
"""Compatibility launcher for Antigravity Mission Control."""

from pathlib import Path
import os
import shutil
import sys

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    if (project_root / "antigravity_mission_control").is_dir():
        sys.path.insert(0, str(project_root))
        from antigravity_mission_control.cli import main

        raise SystemExit(main())
    executable = shutil.which("agy-mc")
    if not executable:
        print("agy-mc is not installed; run the npm or Python installer first", file=sys.stderr)
        raise SystemExit(127)
    os.execv(executable, [executable, *sys.argv[1:]])
