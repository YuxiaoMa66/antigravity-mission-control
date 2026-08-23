#!/usr/bin/env python3
"""Synchronize the publishable Codex skill embedded in the Python package."""

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "antigravity_mission_control" / "skill_bundle"
DIRECTORIES = ("agents", "policies", "references")
FILES = ("SKILL.md",)


def main() -> int:
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)
    for name in FILES:
        shutil.copy2(ROOT / name, BUNDLE / name)
    for name in DIRECTORIES:
        shutil.copytree(ROOT / name, BUNDLE / name)
    scripts = BUNDLE / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "scripts" / "agy_delegate.py", scripts / "agy_delegate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
