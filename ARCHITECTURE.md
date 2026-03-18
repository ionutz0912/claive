# claive v2 — Architecture

> Self-owned multi-agent orchestrator for Claude Code.
> Synthesizes cmux (terminal multiplexing) + Paperclip (organizational management) into a single, tmux-native tool with zero external dependencies.

## Component Architecture

```
Human
  │
  ▼
Orchestrator (tmux window 0, Claude Code + SKILL.md)
  │
  ├─── reads ──→ state/goals.md           (strategic direction)
  ├─── reads ──→ state/board.json          (operational tasks)
  ├─── reads ──→ state/budget.json         (governance limits, arbitrary units)
  ├─── reads ──→ pipelines/*.yaml          (execution plans)
  │
  ├─── lib/dag.py ──→ topological sort ──→ spawn agents in order
  │
  ├─── claive spawn ──→ creates .claive/inbox/<name>/
  │                  ──→ creates git branch (if --branch)
  │                  ──→ creates tmux window
  │
  ├─── lib/mesh.py ──→ watches .claive/outbox/ and .claive/signals/
  │                 ──→ triggers callbacks on agent status changes
  │
  ├─── claive read  ──→ tmux capture-pane (debugging/fallback)
  ├─── claive send  ──→ writes to .claive/inbox/<name>/ (primary)
  │                 ──→ tmux send-keys (fallback)
  │
  ├─── lib/heartbeat.py ──→ scans sideband status files
  │                      ──→ flags stale agents
  │
  └─── writes ──→ state/audit.jsonl        (all actions logged)
```

## Implementation Phases

### Phase 1: Foundation (~350 lines)
- CLI with spawn/list/read/send/kill/status
- Session tracker hook
- Budget governance with per-agent caps (arbitrary units, not real billing)
- Audit trail (append-only JSONL)
- Goal hierarchy (markdown)
- SKILL.md orchestrator brain

### Phase 2: File Locking + Structured Messages (~80 lines)
- fcntl.flock on all state files
- Sentinel markers (###CLAIVE_STATUS:...###)
- Sideband status files

### Phase 3: EventMesh (~120 lines)
- Replace polling with watchdog filesystem events
- Inbox/outbox/signals directory convention
- Sub-second agent communication

### Phase 4: DAG Pipeline (~150 lines)
- claive plan / claive run
- YAML pipeline definitions with dependencies
- Topological sort + automatic parallelism
- Checkpoint/resume

### Phase 5: Git Branch Isolation (~60 lines)
- --branch flag for agent spawning
- Artifact passing via git commits
- claive merge with conflict detection

### Phase 6: Heartbeat + Task Board (~80 lines)
- Stale agent detection
- Mutable board.json for operational tasks

### Phase 7: SKILL.md v2 + Templates (~60 lines)
- Updated orchestrator brain for all v2 features
- Worker agent protocol instructions

## Security Model

| Risk | Mitigation |
|------|-----------|
| State files leaked | chmod 600 on all state files |
| Prompts linger on disk | Temp files cleaned up after use |
| Session map world-readable | Stored in ~/.local/state/claive/ with 0700 |
| Silent hook failures | Errors logged to tracker.log |
| Supply chain attack | No remote fetching, all code local |
| Budget overrun | budget.py returns False on exceed |
| Audit tampering | JSONL append-only by convention |

## Line Budget

| File | Language | Lines | Purpose |
|------|----------|-------|---------|
| bin/claive | Bash | ~120 | CLI dispatcher |
| lib/spawn.sh | Bash | ~80 | Agent lifecycle + branches |
| lib/comms.sh | Bash | ~50 | Read/send + sentinel parsing |
| lib/budget.py | Python | ~70 | Per-agent caps with locking |
| lib/audit.py | Python | ~50 | JSONL logger with locking |
| lib/dag.py | Python | ~180 | Pipeline + scheduler + board |
| lib/mesh.py | Python | ~100 | EventMesh watcher |
| lib/lock.py | Python | ~25 | fcntl.flock wrapper |
| lib/heartbeat.py | Python | ~40 | Stale detection |
| lib/handoff.py | Python | ~55 | Context handoff |
| hooks/session-tracker.py | Python | ~55 | Hook handler |
| SKILL.md | Markdown | ~80 | Orchestrator brain |
| **Total** | | **~935** | |
