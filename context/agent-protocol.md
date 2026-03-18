# Agent Communication Protocol

Read this before modifying how the orchestrator and worker agents communicate.

## Communication Channels

### Primary: EventMesh (filesystem)
- **Orchestrator → Agent**: Writes files to `.claive/inbox/<agent>/`
- **Agent → Orchestrator**: Writes `status.json` to `.claive/outbox/<agent>/`
- **Completion signal**: Agent creates `.claive/signals/<agent>.done`
- Latency: sub-second with watchdog, 2s with polling fallback

### Secondary: tmux send-keys / capture-pane
- `claive send <name> "msg"` — injects text + Enter into agent terminal
- `claive read <name>` — captures last N lines of agent's pane
- Used for immediate delivery and debugging, not primary coordination

### Sentinel Markers
Agents can embed structured signals in terminal output:
- `###CLAIVE_STATUS:<value>###` — parsed by `claive read`
- `###CLAIVE_DONE:<value>###` — parsed by `claive read`

## Worker Agent Bootstrap

When spawning, the orchestrator prefixes agent prompts with:
```
You are a claive worker agent named "<name>".
- Check .claive/inbox/<name>/ for messages from the orchestrator
- Write status to .claive/outbox/<name>/status.json periodically
- When done, write "success" to .claive/signals/<name>.done
- If on a git branch, commit your work before signaling done
```

## Status File Format

`.claive/outbox/<agent>/status.json`:
```json
{"status": "working", "progress": "50%", "current_task": "implementing JWT endpoints"}
```

## Context Pressure & Handoff

When an agent's context window fills (Claude Code emits "compressing prior messages"), the agent should self-report by writing a handoff signal:

**Signal file**: `.claive/signals/<name>.handoff`
```json
{"summary": "what was accomplished", "remaining": "what still needs doing", "files_modified": ["src/foo.ts"], "branch": "agent/backend"}
```

The orchestrator (or human) then runs `claive handoff <name>`, which:
1. Captures terminal output + sideband status + handoff signal
2. Kills the old agent
3. Spawns a fresh replacement with a continuation prompt and remaining budget
4. Audits the event

Agents should write the handoff signal proactively — don't wait for the orchestrator to ask.

## Session Learnings
