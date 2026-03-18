#!/usr/bin/env python3
"""claive/hooks/session-tracker.py — Maps Claude Code sessions to tmux windows.

Install as a Claude Code hook for SessionStart and SessionEnd events.
Writes to ~/.local/state/claive/session-map.json with chmod 600.

Hook configuration in ~/.claude/settings.json:
{
  "hooks": {
    "SessionStart": [{"command": "python3 /path/to/claive/hooks/session-tracker.py start"}],
    "SessionEnd": [{"command": "python3 /path/to/claive/hooks/session-tracker.py end"}]
  }
}
"""

import fcntl
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "claive")
SESSION_MAP = os.path.join(STATE_DIR, "session-map.json")
LOG_FILE = os.path.join(STATE_DIR, "tracker.log")


def setup():
    """Ensure state directory exists with correct permissions."""
    os.makedirs(STATE_DIR, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)

    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def get_tmux_pane():
    """Get the current tmux pane ID, or None if not in tmux."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_id}"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def read_map():
    """Read session map with shared lock."""
    if not os.path.exists(SESSION_MAP):
        return {}
    try:
        with open(SESSION_MAP, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            content = f.read().strip()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return json.loads(content) if content else {}
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Failed to read session map: {e}")
        return {}


def write_map(data):
    """Write session map with exclusive lock and chmod 600."""
    try:
        with open(SESSION_MAP, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            f.write("\n")
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.chmod(SESSION_MAP, 0o600)
    except IOError as e:
        logging.error(f"Failed to write session map: {e}")


def on_session_start(session_id):
    """Record a new session mapping."""
    pane = get_tmux_pane()
    data = read_map()
    data[session_id] = {
        "tmux_pane": pane,
        "cwd": os.getcwd(),
        "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_map(data)
    logging.info(f"Session started: {session_id} -> pane {pane}")


def on_session_end(session_id):
    """Remove a session mapping."""
    data = read_map()
    if session_id in data:
        del data[session_id]
        write_map(data)
        logging.info(f"Session ended: {session_id}")


if __name__ == "__main__":
    setup()

    if len(sys.argv) < 2:
        print("Usage: session-tracker.py <start|end> [session-id]")
        sys.exit(1)

    event = sys.argv[1]
    session_id = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("CLAUDE_SESSION_ID", "unknown")

    if event == "start":
        on_session_start(session_id)
    elif event == "end":
        on_session_end(session_id)
    else:
        logging.error(f"Unknown event: {event}")
        sys.exit(1)
