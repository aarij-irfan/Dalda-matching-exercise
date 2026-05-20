#!/usr/bin/env python3
"""
Dalda Outlet Matcher — one-file setup and launch.

On a new machine:
  1. Install Python 3.10+ from https://www.python.org/ (check "Add to PATH")
  2. Clone this repo or copy the folder
  3. Double-click START.bat  OR  run:  python setup_and_run.py

This script installs dependencies and opens the matcher app.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    print("=" * 60)
    print("Dalda Outlet Matcher — setup")
    print("=" * 60)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Folder: {root}\n")

    census_dir = os.path.join(root, "Census Database")
    if not os.path.isdir(census_dir):
        print("ERROR: Census Database folder not found.")
        return 1

    census_files = [
        f
        for f in os.listdir(census_dir)
        if f.lower().endswith((".csv", ".xlsx", ".xls", ".xlsm"))
    ]
    if not census_files:
        print("ERROR: No census file in Census Database/.")
        return 1
    print(f"Census file(s): {', '.join(census_files)}\n")

    req = os.path.join(root, "requirements.txt")
    if not os.path.isfile(req):
        print("ERROR: requirements.txt not found.")
        return 1

    print("Installing / updating libraries (may take a minute)…")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", req, "--upgrade"],
    )
    print("\nStarting Dalda Outlet Matcher…\n")

    app = os.path.join(root, "dalda_matcher_app.py")
    return subprocess.call([sys.executable, app])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as e:
        print(f"\nSetup failed (pip exit {e.returncode}). Check internet and Python PATH.")
        input("Press Enter to close…")
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(0)
