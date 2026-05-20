"""Resolve app folders for normal Python runs and PyInstaller .exe builds."""

from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def app_base_dir() -> str:
    """Folder containing the .exe (frozen) or project scripts (dev)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir() -> str:
    """Temp extract folder when running a one-file .exe."""
    if is_frozen():
        return getattr(sys, "_MEIPASS")
    return app_base_dir()


def default_census_dir() -> str:
    """
    Prefer Census Database next to the .exe (easy to update on USB).
    Fall back to copy bundled inside the executable.
    """
    beside_exe = os.path.join(app_base_dir(), "Census Database")
    if _has_census_files(beside_exe):
        return beside_exe
    bundled = os.path.join(bundle_dir(), "Census Database")
    if _has_census_files(bundled):
        return bundled
    return beside_exe


def _has_census_files(directory: str) -> bool:
    if not os.path.isdir(directory):
        return False
    exts = (".csv", ".xlsx", ".xls", ".xlsm")
    return any(name.lower().endswith(exts) for name in os.listdir(directory))
