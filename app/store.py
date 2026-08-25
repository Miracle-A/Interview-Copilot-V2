"""Persist interview history to disk so it survives restarts.

One JSON file holds both the in-progress conversation ("turns") and the
archived interviews ("sessions"). Writes go through a temp file + atomic
replace so a crash mid-write can't corrupt existing history.
"""
import json
from pathlib import Path


def load_history(path: Path) -> tuple[list, list]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        turns = data.get("turns", [])
        sessions = data.get("sessions", [])
        if isinstance(turns, list) and isinstance(sessions, list):
            return turns, sessions
    except FileNotFoundError:
        pass
    except Exception:
        pass  # unreadable/corrupt file: start fresh rather than crash the app
    return [], []


def save_history(path: Path, turns: list, sessions: list):
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"turns": turns, "sessions": sessions}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(path)
