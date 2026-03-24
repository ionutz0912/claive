#!/usr/bin/env python3
"""claive/lib/handoff.py — Context handoff for agents hitting context limits.

Captures state from a filling-up agent, kills it, and spawns a fresh
replacement with a continuation prompt carrying forward the work.
"""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
SESSION_NAME = os.environ.get("CLAIVE_SESSION", "claive")
STATE_DIR = os.path.join(ROOT_DIR, "state", SESSION_NAME)
MESH_DIR = os.path.join(ROOT_DIR, ".claive", SESSION_NAME)
BUDGET_FILE = os.path.join(STATE_DIR, "budget.json")
SESSION = f"claive-{SESSION_NAME}" if SESSION_NAME != "claive" else "claive"

sys.path.insert(0, SCRIPT_DIR)
from lock import read_json_locked


def get_budget_remainder(name):
    """Return (remaining, limit) for an agent. (0, 0) if no budget set."""
    data = read_json_locked(BUDGET_FILE)
    if name not in data:
        return (0.0, 0.0)
    entry = data[name]
    remaining = max(0.0, entry["limit"] - entry["spent"])
    return (remaining, entry["limit"])


def capture_terminal(name, lines=200):
    """Capture last N lines from agent's tmux pane."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", f"{SESSION}:{name}", "-p", "-S", f"-{lines}"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def read_sideband(name):
    """Read .claive/outbox/<name>/status.json if it exists."""
    path = os.path.join(MESH_DIR, "outbox", name, "status.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def read_handoff_signal(name):
    """Read .claive/signals/<name>.handoff if agent self-reported."""
    path = os.path.join(MESH_DIR, "signals", f"{name}.handoff")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def build_continuation_prompt(name, terminal, sideband, handoff_signal, branch):
    """Assemble the relay prompt for the replacement agent."""
    parts = [
        f'You are continuing work started by a previous agent named "{name}".',
        "The previous agent ran out of context window space. Pick up where it left off.",
    ]

    if handoff_signal:
        parts.append(f"\n## Previous agent's summary\n{handoff_signal.get('summary', '(none)')}")
        if handoff_signal.get("remaining"):
            parts.append(f"Remaining work: {handoff_signal['remaining']}")
        if handoff_signal.get("files_modified"):
            parts.append(f"Files modified so far: {', '.join(handoff_signal['files_modified'])}")
    elif sideband:
        parts.append(f"\n## Sideband status\n{json.dumps(sideband)}")

    if terminal.strip():
        # Trim to keep prompt reasonable
        lines = terminal.strip().splitlines()[-100:]
        parts.append(f"\n## Recent terminal output (last {len(lines)} lines)\n```\n" + "\n".join(lines) + "\n```")

    if branch:
        parts.append(f"\nYou are on branch `{branch}`. Check `git diff` and `git log` to see prior work.")

    return "\n".join(parts)


def do_handoff(name):
    """Full handoff sequence: capture → build prompt → kill → respawn."""
    # 1. Gather state
    terminal = capture_terminal(name)
    sideband = read_sideband(name)
    handoff_signal = read_handoff_signal(name)
    remaining, limit = get_budget_remainder(name)

    # Detect current branch
    branch = None
    try:
        result = subprocess.run(
            ["tmux", "send-keys", "-t", f"{SESSION}:{name}", "", ""],
            capture_output=True, timeout=2,
        )
        # Best-effort: check if agent was on a specific branch from sideband or signal
        if handoff_signal and handoff_signal.get("branch"):
            branch = handoff_signal["branch"]
    except Exception:
        pass

    # 2. Build continuation prompt
    prompt = build_continuation_prompt(name, terminal, sideband, handoff_signal, branch)

    # 3. Kill old agent (via claive kill)
    bin_claive = os.path.join(ROOT_DIR, "bin", "claive")
    subprocess.run([bin_claive, "kill", name], capture_output=True, timeout=10)

    # Clean up handoff signal and reset budget (spent=0, limit=remainder)
    signal_path = os.path.join(MESH_DIR, "signals", f"{name}.handoff")
    if os.path.exists(signal_path):
        os.remove(signal_path)

    if remaining > 0:
        from lock import write_json_locked
        budget_data = read_json_locked(BUDGET_FILE)
        budget_data[name] = {"spent": 0.0, "limit": remaining}
        write_json_locked(BUDGET_FILE, budget_data)

    # 4. Respawn with continuation prompt and remaining budget
    spawn_cmd = [bin_claive, "spawn", name, "--prompt", prompt]
    if remaining > 0:
        spawn_cmd += ["--budget", f"{remaining:.2f}"]
    if branch:
        spawn_cmd += ["--branch", branch]

    subprocess.run(spawn_cmd, timeout=15)

    # 5. Audit
    from audit import audit_log
    detail = f"{name} (remaining=${remaining:.2f}/{limit:.2f})"
    audit_log("handoff", detail)

    print(f"Handoff complete: '{name}' replaced with fresh agent")
    if limit > 0:
        print(f"  Budget carried: ${remaining:.2f} remaining of ${limit:.2f}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: handoff.py <agent-name>")
        sys.exit(1)
    do_handoff(sys.argv[1])
