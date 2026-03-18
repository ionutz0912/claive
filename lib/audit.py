#!/usr/bin/env python3
"""claive/lib/audit.py — Append-only JSONL audit trail."""

import fcntl
import json
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "state")
AUDIT_FILE = os.path.join(STATE_DIR, "audit.jsonl")


def audit_log(action, details=""):
    """Append a single audit entry. Never modifies existing entries."""
    os.makedirs(STATE_DIR, exist_ok=True)

    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": action,
        "details": details,
        "pid": os.getpid(),
    }

    line = json.dumps(entry, separators=(",", ":")) + "\n"

    # Append with exclusive lock
    fd = os.open(AUDIT_FILE, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    try:
        f = os.fdopen(fd, "a")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()
    except Exception:
        os.close(fd)
        raise


def audit_show(last_n=None, action_filter=None):
    """Print audit entries, optionally filtered."""
    if not os.path.exists(AUDIT_FILE):
        print("(no audit entries)")
        return

    with open(AUDIT_FILE, "r") as f:
        lines = f.readlines()

    if action_filter:
        lines = [l for l in lines if f'"action":"{action_filter}"' in l]

    if last_n:
        lines = lines[-last_n:]

    for line in lines:
        try:
            entry = json.loads(line.strip())
            ts = entry.get("ts", "?")
            action = entry.get("action", "?")
            details = entry.get("details", "")
            print(f"  {ts}  {action:<16}  {details}")
        except json.JSONDecodeError:
            continue


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: audit.py <log|show> [args]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "log" and len(sys.argv) >= 3:
        action = sys.argv[2]
        details = sys.argv[3] if len(sys.argv) > 3 else ""
        audit_log(action, details)
    elif cmd == "show":
        last_n = None
        action_filter = None
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--last" and i + 1 < len(sys.argv):
                last_n = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--action" and i + 1 < len(sys.argv):
                action_filter = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        audit_show(last_n, action_filter)
    else:
        print("Usage: audit.py <log|show> [args]")
        sys.exit(1)
