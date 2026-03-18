# Security Model

Read this before modifying file permissions, state storage, or agent trust boundaries.

## Trust Boundaries

1. **Human → Orchestrator**: Full trust. Human talks directly to orchestrator.
2. **Orchestrator → Agents**: Controlled trust. Only orchestrator can read other agents' terminals. Agents cannot read each other (unless same tmux session — use `--socket` for strict isolation).
3. **Agents → Filesystem**: Standard Claude Code permissions per project directory.

## Hardening Measures

| Risk | Mitigation |
|------|-----------|
| State files leaked | chmod 600 on sessions.json, budget.json, audit.jsonl |
| Prompts linger on disk | Temp files in /tmp/claive-prompt-XXXXXX, cleaned after use |
| Session map world-readable | ~/.local/state/claive/ with 0700 dir permissions |
| Silent hook failures | Errors logged to tracker.log (never `except: pass`) |
| Supply chain attack | No remote fetching, all code local and version-controlled |
| Budget overrun | budget.py add returns False on exceed, exit code 1 |
| Concurrent state corruption | fcntl.flock on all state file reads/writes |

## Known Limitations

- A malicious agent can overwrite claive's own scripts (same user context)
- Secrets in prompts appear in tmux pane buffers (don't put secrets in prompts)
- Shared tmux session means agents could capture-pane on each other (use --socket for isolation)
- No encryption at rest for state files (relies on Unix file permissions)

## Session Learnings
