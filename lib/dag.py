#!/usr/bin/env python3
"""claive/lib/dag.py — DAG pipeline parser, scheduler, and task board.

Phase 4 implementation: declarative task graphs with automatic parallelism.
"""

import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLAIVE_ROOT = os.path.dirname(SCRIPT_DIR)
STATE_DIR = os.path.join(CLAIVE_ROOT, "state")
PIPELINES_DIR = os.path.join(CLAIVE_ROOT, "pipelines")
BOARD_FILE = os.path.join(STATE_DIR, "board.json")

sys.path.insert(0, SCRIPT_DIR)
from lock import read_json_locked, write_json_locked

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# --- Pipeline ---

class Task:
    def __init__(self, id, prompt="", depends_on=None, outputs=None, budget=None, branch=None):
        self.id = id
        self.prompt = prompt
        self.depends_on = depends_on or []
        self.outputs = outputs or []
        self.budget = budget
        self.branch = branch
        self.status = "pending"  # pending | running | done | failed


class Pipeline:
    def __init__(self, name, tasks):
        self.name = name
        self.tasks = {t.id: t for t in tasks}

    @classmethod
    def from_yaml(cls, path):
        if not HAS_YAML:
            print("Error: PyYAML required. Install with: pip install pyyaml")
            sys.exit(1)
        with open(path) as f:
            data = yaml.safe_load(f)
        name = data.get("pipeline", os.path.basename(path))
        defaults = data.get("defaults", {})
        tasks = []
        for tid, tdata in data.get("tasks", {}).items():
            budget_str = tdata.get("budget", defaults.get("budget"))
            budget = float(str(budget_str).replace("$", "")) if budget_str else None
            tasks.append(Task(
                id=tid,
                prompt=tdata.get("prompt", ""),
                depends_on=tdata.get("depends_on", []),
                outputs=tdata.get("outputs", []),
                budget=budget,
                branch=tdata.get("branch"),
            ))
        return cls(name, tasks)

    def validate(self):
        """Check for missing deps and cycles. Returns list of errors."""
        errors = []
        ids = set(self.tasks.keys())
        for t in self.tasks.values():
            for dep in t.depends_on:
                if dep not in ids:
                    errors.append(f"Task '{t.id}' depends on unknown task '{dep}'")
        if not errors and self._has_cycle():
            errors.append("Pipeline contains a dependency cycle")
        return errors

    def _has_cycle(self):
        """Kahn's algorithm: returns True if cycle exists."""
        in_degree = {tid: 0 for tid in self.tasks}
        for t in self.tasks.values():
            for dep in t.depends_on:
                in_degree[t.id] += 1
        queue = deque(tid for tid, d in in_degree.items() if d == 0)
        visited = 0
        adj = defaultdict(list)
        for t in self.tasks.values():
            for dep in t.depends_on:
                adj[dep].append(t.id)
        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return visited != len(self.tasks)

    def ready_tasks(self):
        """Return tasks whose dependencies are all done."""
        return [
            t for t in self.tasks.values()
            if t.status == "pending"
            and all(self.tasks[d].status == "done" for d in t.depends_on)
        ]

    def mark_running(self, task_id):
        self.tasks[task_id].status = "running"

    def mark_done(self, task_id):
        self.tasks[task_id].status = "done"

    def mark_failed(self, task_id):
        self.tasks[task_id].status = "failed"

    def is_complete(self):
        return all(t.status in ("done", "failed") for t in self.tasks.values())

    def resolve_prompt(self, task):
        """Replace {dep.outputs} references in prompt."""
        prompt = task.prompt
        for dep_id in task.depends_on:
            dep = self.tasks[dep_id]
            outputs_str = ", ".join(dep.outputs)
            prompt = prompt.replace(f"{{{dep_id}.outputs}}", outputs_str)
        return prompt

    def checkpoint(self):
        """Save pipeline state for resume."""
        os.makedirs(PIPELINES_DIR, exist_ok=True)
        path = os.path.join(PIPELINES_DIR, f".checkpoint-{self.name}.json")
        state = {tid: t.status for tid, t in self.tasks.items()}
        write_json_locked(path, {"name": self.name, "tasks": state})

    def resume_from_checkpoint(self):
        """Load task statuses from checkpoint."""
        path = os.path.join(PIPELINES_DIR, f".checkpoint-{self.name}.json")
        if not os.path.exists(path):
            return False
        data = read_json_locked(path)
        for tid, status in data.get("tasks", {}).items():
            if tid in self.tasks:
                self.tasks[tid].status = status
        return True

    def show_status(self):
        """Print pipeline status."""
        print(f"Pipeline: {self.name}")
        print()
        for t in self.tasks.values():
            deps = f" (depends: {', '.join(t.depends_on)})" if t.depends_on else ""
            icon = {"pending": "○", "running": "◉", "done": "✓", "failed": "✗"}[t.status]
            print(f"  {icon} {t.id:<16} {t.status:<10}{deps}")


def do_run(args):
    """Execute a pipeline YAML."""
    if not args:
        print("Usage: claive run <pipeline.yaml> [--resume] [--status]")
        return

    path = args[0]
    resume = "--resume" in args
    status_only = "--status" in args

    pipeline = Pipeline.from_yaml(path)
    errors = pipeline.validate()
    if errors:
        for e in errors:
            print(f"Error: {e}")
        sys.exit(1)

    if resume:
        if pipeline.resume_from_checkpoint():
            print(f"Resumed from checkpoint")
        else:
            print("No checkpoint found, starting fresh")

    if status_only:
        pipeline.show_status()
        return

    # Execute the DAG
    signals_dir = os.path.join(CLAIVE_ROOT, ".claive", "signals")
    os.makedirs(signals_dir, exist_ok=True)

    print(f"Running pipeline: {pipeline.name}")
    pipeline.show_status()
    print()

    while not pipeline.is_complete():
        # Check for completion signals from running agents
        for t in pipeline.tasks.values():
            if t.status != "running":
                continue
            signal_file = os.path.join(signals_dir, f"{t.id}.done")
            if os.path.exists(signal_file):
                try:
                    with open(signal_file) as f:
                        result = f.read().strip()
                except IOError:
                    result = "unknown"
                if result == "failure":
                    pipeline.mark_failed(t.id)
                    print(f"Failed: {t.id}")
                else:
                    pipeline.mark_done(t.id)
                    print(f"Done: {t.id}")
                pipeline.checkpoint()

        ready = pipeline.ready_tasks()
        if not ready:
            running = [t for t in pipeline.tasks.values() if t.status == "running"]
            if not running:
                print("Pipeline stuck: no ready or running tasks")
                break
            time.sleep(2)
            continue

        for task in ready:
            prompt = pipeline.resolve_prompt(task)
            cmd = ["claive", "spawn", task.id, "--prompt", prompt]
            if task.budget:
                cmd.extend(["--budget", str(task.budget)])
            if task.branch:
                cmd.extend(["--branch", task.branch])

            print(f"Spawning: {task.id}")
            subprocess.run(cmd)
            pipeline.mark_running(task.id)

        pipeline.checkpoint()
        pipeline.show_status()


# --- Task Board ---

def board_show():
    data = read_json_locked(BOARD_FILE, default={"tasks": [], "next_id": 1})
    tasks = data.get("tasks", [])
    if not tasks:
        print("  (empty board)")
        return
    for t in tasks:
        icon = {"open": "○", "assigned": "◉", "done": "✓"}[t.get("status", "open")]
        assignee = f" -> {t['assignee']}" if t.get("assignee") else ""
        print(f"  {icon} [{t['id']}] {t['desc']}{assignee}")


def board_add(desc):
    data = read_json_locked(BOARD_FILE, default={"tasks": [], "next_id": 1})
    task_id = data["next_id"]
    data["tasks"].append({
        "id": task_id,
        "desc": desc,
        "status": "open",
        "assignee": None,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    data["next_id"] = task_id + 1
    write_json_locked(BOARD_FILE, data)
    print(f"Added task [{task_id}]: {desc}")


def board_assign(task_id, agent):
    data = read_json_locked(BOARD_FILE, default={"tasks": [], "next_id": 1})
    for t in data["tasks"]:
        if t["id"] == int(task_id):
            t["status"] = "assigned"
            t["assignee"] = agent
            write_json_locked(BOARD_FILE, data)
            print(f"Assigned [{task_id}] to {agent}")
            return
    print(f"Task [{task_id}] not found")


def board_done(task_id):
    data = read_json_locked(BOARD_FILE, default={"tasks": [], "next_id": 1})
    for t in data["tasks"]:
        if t["id"] == int(task_id):
            t["status"] = "done"
            write_json_locked(BOARD_FILE, data)
            print(f"Completed [{task_id}]")
            return
    print(f"Task [{task_id}] not found")


# --- Plan ---

PIPELINE_SCHEMA = """\
# Pipeline YAML schema — this is what you must produce.
# Task IDs become agent names. Dependencies define execution order.
# Tasks with no dependencies run in parallel automatically.

pipeline: <name>

defaults:
  budget: 3.00          # default per-agent budget if not overridden

tasks:
  <task-id>:
    prompt: "Focused instruction for this agent"
    depends_on: []      # list of task IDs that must complete first
    outputs: []         # list of files/artifacts this task produces
    budget: 5.00        # optional override
    branch: <branch>    # optional git branch for isolation
"""


def _slugify(text):
    """Convert goal text to a filename-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return slug.strip("-")[:60]


def do_plan(args):
    """Spawn a planner agent that generates a pipeline YAML from a goal."""
    if not args:
        print("Usage: claive plan \"goal description\" [--budget N]")
        return

    # Parse args
    goal_parts = []
    budget = "2.00"
    i = 0
    while i < len(args):
        if args[i] == "--budget" and i + 1 < len(args):
            budget = args[i + 1]
            i += 2
        else:
            goal_parts.append(args[i])
            i += 1

    goal = " ".join(goal_parts)
    if not goal:
        print("Error: no goal provided")
        return

    slug = _slugify(goal)
    output_path = os.path.join(PIPELINES_DIR, f"{slug}.yaml")
    goals_path = os.path.join(STATE_DIR, "goals.md")

    prompt = f"""\
You are a claive planner agent. Your job: decompose a goal into a pipeline YAML that claive can execute.

GOAL: {goal}

INSTRUCTIONS:
1. Read {goals_path} for project context and priorities.
2. Break the goal into 2-6 focused tasks. Each task becomes one Claude Code agent.
3. Name tasks by role (e.g., backend, frontend, tests, docs, schema, api).
4. Identify dependencies — what must finish before what else can start.
5. Maximize parallelism: independent tasks should have no dependencies between them.
6. Set realistic budgets: $2-5 for simple tasks, $5-10 for complex ones.
7. Write clear, specific prompts — each agent sees ONLY its own prompt.
8. Write the pipeline YAML to: {output_path}

YAML SCHEMA:
{PIPELINE_SCHEMA}

RULES:
- One agent per concern. Don't overload tasks.
- Prompts must be self-contained — agents can't read each other's output directly.
- Use depends_on to chain tasks that need prior work.
- Use outputs to list files each task produces (helps downstream agents).
- Use branch for tasks that modify code (keeps work isolated until merge).
- After writing the YAML, signal done: write "success" to .claive/signals/planner.done

Write the YAML file now. Do not ask questions — make reasonable assumptions."""

    # Spawn the planner agent
    os.makedirs(PIPELINES_DIR, exist_ok=True)
    cmd = [
        os.path.join(CLAIVE_ROOT, "bin", "claive"),
        "spawn", "planner",
        "--prompt", prompt,
        "--budget", budget,
    ]
    subprocess.run(cmd)

    print(f"\nPlanner spawned. Pipeline will be written to:")
    print(f"  {output_path}")
    print(f"\nMonitor with:  claive read planner")
    print(f"Then run with: claive run {output_path}")


def do_pipeline(args):
    """Print parsed pipeline DAG with prompts — for orchestrator consumption."""
    if not args:
        print("Usage: dag.py pipeline <file.yaml>")
        return

    path = args[0]
    pipeline = Pipeline.from_yaml(path)
    errors = pipeline.validate()
    if errors:
        for e in errors:
            print(f"Error: {e}")
        sys.exit(1)

    # Compute DAG layers via topological sort
    in_degree = {tid: len(t.depends_on) for tid, t in pipeline.tasks.items()}
    adj = defaultdict(list)
    for t in pipeline.tasks.values():
        for dep in t.depends_on:
            adj[dep].append(t.id)

    layers = []
    remaining = dict(in_degree)
    while remaining:
        layer = [tid for tid, d in remaining.items() if d == 0]
        if not layer:
            print("Error: cycle detected")
            sys.exit(1)
        layers.append(sorted(layer))
        for tid in layer:
            for neighbor in adj[tid]:
                if neighbor in remaining:
                    remaining[neighbor] -= 1
            del remaining[tid]

    print(f"Pipeline: {pipeline.name}")
    print(f"Tasks: {len(pipeline.tasks)}")
    print(f"Layers: {len(layers)}")
    print()

    # DAG overview
    print("DAG:")
    for i, layer in enumerate(layers):
        parallel = " || ".join(layer)
        prefix = "  " if i == 0 else "  -> "
        print(f"{prefix}[{parallel}]")
    print()

    # Per-task details with spawn commands
    for i, layer in enumerate(layers):
        print(f"--- Layer {i + 1} {'(parallel)' if len(layer) > 1 else ''} ---")
        for tid in layer:
            task = pipeline.tasks[tid]
            deps_str = f" (after: {', '.join(task.depends_on)})" if task.depends_on else ""
            budget_str = f" --budget {task.budget}" if task.budget else ""
            print(f"\n  Task: {tid}{deps_str}")
            if task.budget:
                print(f"  Budget: ${task.budget:.2f}")
            if task.outputs:
                print(f"  Outputs: {', '.join(task.outputs)}")

            # Print the spawn command
            prompt_oneline = task.prompt.strip().replace('\n', '\\n')[:200]
            print(f"  Spawn: claive spawn {tid} --prompt <see below>{budget_str}")
            print(f"  Prompt:")
            for line in task.prompt.strip().split('\n'):
                print(f"    {line}")
        print()


def checkpoint_summary():
    """Print compact 2-column pipeline progress from checkpoint files."""
    if not os.path.isdir(PIPELINES_DIR):
        return
    checkpoints = [f for f in os.listdir(PIPELINES_DIR) if f.startswith(".checkpoint-") and f.endswith(".json")]
    if not checkpoints:
        return
    icons = {"pending": "○", "running": "◉", "done": "✓", "failed": "✗"}
    for cp_file in sorted(checkpoints):
        data = read_json_locked(os.path.join(PIPELINES_DIR, cp_file))
        name = data.get("name", cp_file)
        tasks = data.get("tasks", {})
        has_running = any(s == "running" for s in tasks.values())
        all_terminal = all(s in ("done", "failed") for s in tasks.values())
        state = "running" if has_running else ("complete" if all_terminal else "paused")
        print(f"\nPipeline: {name} ({state})")
        items = list(tasks.items())
        # Print in 2-column layout
        for i in range(0, len(items), 2):
            col1 = f"  {icons.get(items[i][1], '?')} {items[i][0]}"
            col2 = f"  {icons.get(items[i+1][1], '?')} {items[i+1][0]}" if i + 1 < len(items) else ""
            print(f"{col1:<24}{col2}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: dag.py <plan|run|board|checkpoint-summary> [args]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "run":
        do_run(sys.argv[2:])
    elif cmd == "pipeline":
        do_pipeline(sys.argv[2:])
    elif cmd == "checkpoint-summary":
        checkpoint_summary()
    elif cmd == "board":
        subcmd = sys.argv[2] if len(sys.argv) > 2 else "show"
        if subcmd == "show" or subcmd == "board":
            board_show()
        elif subcmd == "add" and len(sys.argv) > 3:
            board_add(sys.argv[3])
        elif subcmd == "assign" and len(sys.argv) > 4:
            board_assign(sys.argv[3], sys.argv[4])
        elif subcmd == "done" and len(sys.argv) > 3:
            board_done(sys.argv[3])
        else:
            print("Usage: dag.py board [show|add|assign|done]")
    elif cmd == "plan":
        do_plan(sys.argv[2:])
    else:
        print("Usage: dag.py <plan|run|board> [args]")
        sys.exit(1)
