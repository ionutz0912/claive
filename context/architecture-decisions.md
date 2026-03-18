# Architecture Decisions

Read this before proposing new features or changing the component structure.

## Core Design Choices

**tmux as the only runtime**: All agent isolation, communication, and lifecycle management goes through tmux primitives. No custom IPC, no message queues, no databases. tmux has 30+ years of reliability.

**State as files**: Markdown for goals (human-readable), JSON for structured state (budget, sessions, board), JSONL for append-only audit. All greppable, diffable, and debuggable with standard Unix tools.

**EventMesh over polling**: v1 used 15-second sleep-poll cycles. v2 uses watchdog filesystem events on `.claive/outbox/` and `.claive/signals/` for sub-second latency. Falls back to 2s polling if watchdog not installed.

**DAG pipelines for planning**: Task decomposition expressed as YAML with explicit dependencies. Topological sort extracts automatic parallelism. Checkpoint/resume for interrupted pipelines.

**Git branches for artifact passing**: Agents on `--branch` commit their work to isolated branches. Orchestrator merges via `claive merge`. Conflict detection built in. Git log becomes natural audit trail.

**File locking via fcntl.flock**: All state writes go through lib/lock.py. Advisory locking sufficient since all writers are claive processes.

## Anti-Patterns to Avoid

- No web servers, no React dashboards, no localhost ports
- No proprietary binaries or remote script fetching
- No `except Exception: pass` — always log errors
- No world-readable state files — chmod 600 minimum
- No databases — if JSON/JSONL isn't enough, rethink the feature
- No pip dependencies beyond watchdog (optional) and pyyaml (optional for DAG)

## Session Learnings
