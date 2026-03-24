#!/usr/bin/env python3
"""claive/lib/budget.py — Per-agent budget caps with file locking.

Budgets are arbitrary governance units (not tied to real billing).
They act as soft limits to prevent runaway agents and prioritize work.
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
SESSION_NAME = os.environ.get("CLAIVE_SESSION", "claive")
STATE_DIR = os.path.join(ROOT_DIR, "state", SESSION_NAME)
BUDGET_FILE = os.path.join(STATE_DIR, "budget.json")

# Import lock helpers
sys.path.insert(0, SCRIPT_DIR)
from lock import read_json_locked, write_json_locked


def budget_set(agent, limit):
    """Set a dollar cap for an agent."""
    data = read_json_locked(BUDGET_FILE)
    if agent not in data:
        data[agent] = {"spent": 0.0, "limit": float(limit)}
    else:
        data[agent]["limit"] = float(limit)
    write_json_locked(BUDGET_FILE, data)
    print(f"Budget set: {agent} = ${float(limit):.2f}")


def budget_add(agent, amount):
    """Record spending. Returns False (exit 1) if over budget."""
    data = read_json_locked(BUDGET_FILE)
    if agent not in data:
        data[agent] = {"spent": 0.0, "limit": 0.0}

    new_spent = data[agent]["spent"] + float(amount)
    if new_spent > data[agent]["limit"] > 0:
        print(f"OVER BUDGET: {agent} would be ${new_spent:.2f} / ${data[agent]['limit']:.2f}")
        return False

    data[agent]["spent"] = new_spent
    write_json_locked(BUDGET_FILE, data)
    print(f"Recorded: {agent} +${float(amount):.2f} (${new_spent:.2f} / ${data[agent]['limit']:.2f})")
    return True


def budget_check(agent):
    """Show current spend vs limit for an agent."""
    data = read_json_locked(BUDGET_FILE)
    if agent not in data:
        print(f"{agent}: no budget set")
        return
    entry = data[agent]
    pct = (entry["spent"] / entry["limit"] * 100) if entry["limit"] > 0 else 0
    print(f"{agent}: ${entry['spent']:.2f} / ${entry['limit']:.2f} ({pct:.0f}%)")


def budget_report():
    """ASCII bar chart of all agents' budgets."""
    data = read_json_locked(BUDGET_FILE)
    if not data:
        print("  (no budgets)")
        return

    max_name = max(len(name) for name in data)
    for name, entry in sorted(data.items()):
        spent = entry["spent"]
        limit = entry["limit"]
        pct = (spent / limit * 100) if limit > 0 else 0
        bar_len = int(pct / 5)  # 20 chars = 100%
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"  {name:<{max_name}}  [{bar}] ${spent:.2f}/${limit:.2f}")


def budget_agent_row(agent):
    """Return compact bar string for one agent: [████░░░░░░] $4.20/$10.00"""
    data = read_json_locked(BUDGET_FILE)
    if agent not in data:
        return "-"
    entry = data[agent]
    spent, limit = entry["spent"], entry["limit"]
    pct = (spent / limit * 100) if limit > 0 else 0
    bar_len = min(int(pct / 5), 20)
    bar = "█" * bar_len + "░" * (20 - bar_len)
    return f"[{bar}] ${spent:.2f}/${limit:.2f}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: budget.py <set|add|check|report|row> [args]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "set" and len(sys.argv) == 4:
        budget_set(sys.argv[2], sys.argv[3])
    elif cmd == "add" and len(sys.argv) == 4:
        ok = budget_add(sys.argv[2], sys.argv[3])
        sys.exit(0 if ok else 1)
    elif cmd == "check" and len(sys.argv) == 3:
        budget_check(sys.argv[2])
    elif cmd == "report":
        budget_report()
    elif cmd == "row" and len(sys.argv) == 3:
        print(budget_agent_row(sys.argv[2]))
    else:
        print("Usage: budget.py <set|add|check|report|row> [args]")
        sys.exit(1)
