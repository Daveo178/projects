"""JSON persistence helpers for `household_data`.

Centralises reading and writing the household plan to disk so plans survive a
browser refresh. Writes are atomic (write-then-rename) to avoid corrupting the
file if the process is killed mid-save, and every successful save rotates the
previous version to a `.bak` file so a bad save is one-deep recoverable.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

# Files live next to `main.py` so they back up together with the rest of the
# project and stay trivially gitignore-able.
DEFAULT_PATH: Path = Path("household_data.json")


def _backup_path(path: Path) -> Path:
    """Single canonical `.bak` location for a given plan path."""
    return path.with_name(path.name + ".bak")


def load_household(path: Path = DEFAULT_PATH) -> Dict[str, Any]:
    """Load household data from disk.

    Falls back to `path + ".bak"` if the live file is missing or corrupt
    (e.g. a crash happened between rotation and the new write). Returns an
    empty dict if neither file exists or is readable. Never raises.
    """
    for candidate in (path, _backup_path(path)):
        if not candidate.exists():
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def save_household(data: Dict[str, Any], path: Path = DEFAULT_PATH) -> bool:
    """Persist household data to disk atomically.

    Before each successful save, the existing file (if any) is renamed to
    `path + ".bak"`, giving a single-step undo. The new content is written
    to a temp file and `os.replace`'d into place so the file is never
    partially written. Returns True on success, False on any OS-level failure.
    """
    backup_path = _backup_path(path)

    try:
        directory = path.parent or Path(".")
        directory.mkdir(parents=True, exist_ok=True)

        # Rotate the previous version. Best-effort: if rotation fails the
        # new save still proceeds (and overwrites the existing main file).
        if path.exists():
            try:
                os.replace(path, backup_path)
            except OSError:
                pass

        fd, tmp_path = tempfile.mkstemp(
            dir=str(directory), suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup of the half-written temp file.
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def delete_household(path: Path = DEFAULT_PATH) -> bool:
    """Remove the live plan and its `.bak` companion.

    Returns True if neither file exists at the end (best-effort tolerates
    per-file failures).
    """
    cleaned = True
    for victim in (path, _backup_path(path)):
        try:
            if victim.exists():
                os.remove(victim)
        except OSError:
            cleaned = False
    return cleaned


def init_household(state: Dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    """Seed `state['household_data']` from disk the first time it's read.

    Streamlit reruns each page script on every interaction, and `session_state`
    is preserved across page navigations within a single browser tab. So we
    only want to load from disk on the very first access of the session —
    after that, the in-memory dict is the source of truth.
    """
    if "household_data" not in state:
        state["household_data"] = load_household(path)


def has_saved_plan(path: Path = DEFAULT_PATH) -> bool:
    """True if a saved plan exists on disk (used for UI status indicators)."""
    return path.exists() and path.stat().st_size > 0
