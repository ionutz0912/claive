#!/usr/bin/env python3
"""claive/lib/heartbeat.py — Agent liveness monitoring.

Scans sideband status files for heartbeat timestamps.
Flags agents that haven't updated in N minutes as stale.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLAIVE_ROOT = os.path.dirname(SCRIPT_DIR)
MESH_DIR = os.path.join(CLAIVE_ROOT, ".claive")
DEFAULT_TIMEOUT_MINUTES = 5


def check_agents(timeout_minutes=DEFAULT_TIMEOUT_MINUTES):
    """Scan all agent outbox/status.json files for liveness.

    Returns dict: {agent_name: {"status": "alive"|"stale"|"unknown", "last_seen": str|None}}
    """
    outbox = os.path.join(MESH_DIR, "outbox")
    if not os.path.isdir(outbox):
        return {}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=timeout_minutes)
    results = {}

    for agent in os.listdir(outbox):
        agent_dir = os.path.join(outbox, agent)
        if not os.path.isdir(agent_dir):
            continue

        status_file = os.path.join(agent_dir, "status.json")
        if not os.path.exists(status_file):
            results[agent] = {"status": "unknown", "last_seen": None}
            continue

        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(status_file), tz=timezone.utc)
            if mtime < cutoff:
                results[agent] = {"status": "stale", "last_seen": mtime.strftime("%Y-%m-%dT%H:%M:%SZ")}
            else:
                results[agent] = {"status": "alive", "last_seen": mtime.strftime("%Y-%m-%dT%H:%M:%SZ")}
        except OSError:
            results[agent] = {"status": "unknown", "last_seen": None}

    return results


def report(timeout_minutes=DEFAULT_TIMEOUT_MINUTES):
    """Print heartbeat status for all agents."""
    agents = check_agents(timeout_minutes)
    if not agents:
        print("  (no agents with status files)")
        return

    for name, info in sorted(agents.items()):
        icon = {"alive": "♥", "stale": "⚠", "unknown": "?"}[info["status"]]
        last = info["last_seen"] or "never"
        print(f"  {icon} {name:<16} {info['status']:<8} last seen: {last}")


def agent_status_line(agent, timeout_minutes=DEFAULT_TIMEOUT_MINUTES):
    """Return compact status for one agent: 'alive', 'stale 3m', or '-'."""
    outbox = os.path.join(MESH_DIR, "outbox")
    status_file = os.path.join(outbox, agent, "status.json")
    if not os.path.exists(status_file):
        return "-"
    try:
        now = datetime.now(timezone.utc)
        mtime = datetime.fromtimestamp(os.path.getmtime(status_file), tz=timezone.utc)
        age = now - mtime
        if age > timedelta(minutes=timeout_minutes):
            mins = int(age.total_seconds() / 60)
            return f"stale {mins}m"
        return "alive"
    except OSError:
        return "-"


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "status":
        print(agent_status_line(sys.argv[2]))
    else:
        timeout = DEFAULT_TIMEOUT_MINUTES
        if len(sys.argv) > 1:
            try:
                timeout = int(sys.argv[1])
            except ValueError:
                print(f"Usage: heartbeat.py [timeout_minutes] | heartbeat.py status <agent>")
                sys.exit(1)
        report(timeout)
