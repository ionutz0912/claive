# claive — Multi-Agent Orchestrator for Claude Code

## Purpose
claive coordinates multiple Claude Code agents through tmux, with budget governance, audit trails, goal hierarchies, and event-driven communication. Built on tmux + Python 3 + Bash with zero external servers. The design philosophy is radical simplicity: you own every line, state is files not databases, and the constraint IS the strategy. Created by @ionutz0912 as a synthesis of cmux (terminal multiplexing) and Paperclip (organizational management).

## Tree
```
bin/claive              — CLI entrypoint (Bash dispatcher for all commands)
lib/spawn.sh            — Agent lifecycle: spawn, kill, merge (tmux window mgmt)
lib/comms.sh            — Read agent output + send messages (tmux capture/send-keys)
lib/lock.py             — File locking helpers (fcntl.flock context manager)
lib/budget.py           — Per-agent budget governance (arbitrary units, not billing)
lib/audit.py            — Append-only JSONL audit trail
lib/dag.py              — DAG pipeline parser, topo sort, scheduler, task board
lib/mesh.py             — EventMesh: watchdog filesystem events (replaces polling)
lib/heartbeat.py        — Agent liveness monitoring (stale detection)
lib/handoff.py          — Context handoff: capture → kill → respawn with continuation
lib/__init__.py         — Python package marker
hooks/session-tracker.py — Claude Code hook mapping sessions to tmux windows
state/goals.md          — Mission + project hierarchy (strategic, human-curated)
state/board.json        — Mutable task board (operational, agent-writable) [gitignored]
state/budget.json       — Per-agent budget tracking [gitignored]
state/audit.jsonl       — Action log [gitignored]
pipelines/              — User-created DAG pipeline YAML files
pipelines/examples/     — Reference pipeline patterns (auth, refactor, docs)
templates/solo-dev.yaml — Pre-built 4-agent team configuration
.claive/                — EventMesh runtime (inbox/outbox/signals) [gitignored]
context/agent-protocol.md       — Agent communication channels and bootstrap protocol
context/architecture-decisions.md — Core design choices and anti-patterns
context/security-model.md       — Trust boundaries, hardening, known limitations
SKILL.md                — Orchestrator brain prompt (teaches Claude Code to coordinate)
ARCHITECTURE.md         — Full design document with phases and data flow
README.md               — Public-facing project description
LICENSE                 — Project license
.gitignore              — Git ignore rules
```

## Rules
- Read ARCHITECTURE.md before making structural changes to any component
- Read SKILL.md before modifying orchestrator behavior or agent protocol
- All state files must use lib/lock.py for concurrent access — never raw open/write
- Audit every user-facing action via lib/audit.py — the trail is accountability
- Security: chmod 600 on state files, no world-readable paths, no remote fetching
- Keep total codebase under ~1500 lines — simplicity is the moat (learned 3/16)
- Bash for CLI + shell glue, Python for logic + state — don't mix concerns (learned 3/16)
- Never add a GUI dashboard or web server — terminal-native is a design choice (learned 3/16)
- Test Python modules with direct invocation: `python3 lib/budget.py report` (learned 3/16)
- `claive plan` targets Option B: AI-generated pipeline YAML from goal description — revisit feasibility after first real usage (learned 3/16)

## Note-Taking
- **When**: After every task, log corrections, preferences, or patterns learned.
- **Where**: Write to the matching `context/` file's "Session learnings" section. If no context file fits, add to Rules above.
- **How**: One line. Dated. Plain language. Example: `"Budget tracker returns exit code 1 on overspend for scripting (learned 3/16)"`
- **Graduate**: When 3+ related notes accumulate in Rules, create a new `context/` file. Move the notes there. Update the Tree. Keep CLAUDE.md under 100 lines.
