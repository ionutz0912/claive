#!/usr/bin/env bash
# claive/lib/spawn.sh — Agent lifecycle management

do_spawn() {
    local name="" prompt="" budget="" branch="" model="sonnet" effort=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prompt)  prompt="$2"; shift 2 ;;
            --budget)  budget="${2#\$}"; shift 2 ;;  # strip leading $
            --branch)  branch="$2"; shift 2 ;;
            --model)   model="$2"; shift 2 ;;
            --effort)  effort="$2"; shift 2 ;;
            *)
                if [ -z "$name" ]; then
                    name="$1"; shift
                else
                    echo "Error: unexpected argument '$1'"; return 1
                fi
                ;;
        esac
    done

    if [ -z "$name" ]; then
        echo "Usage: claive spawn <name> [--prompt \"...\"] [--budget \$N] [--branch <b>] [--model opus|sonnet] [--effort low|medium|high|max]"
        return 1
    fi

    if tmux list-windows -t "$CLAIVE_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$name"; then
        echo "Error: agent '$name' already exists"
        return 1
    fi

    if [ -n "$budget" ]; then
        python3 "$CLAIVE_LIB/budget.py" set "$name" "$budget"
    fi

    mkdir -p "$CLAIVE_MESH/inbox/$name" "$CLAIVE_MESH/outbox/$name"

    if [ -n "$branch" ]; then
        git branch "$branch" 2>/dev/null || true
    fi

    local claude_flags="--dangerously-skip-permissions --model $model"
    [ -n "$effort" ] && claude_flags="$claude_flags --effort $effort"

    local cmd="claude $claude_flags"
    if [ -n "$prompt" ]; then
        local tmpfile
        tmpfile=$(mktemp /tmp/claive-prompt-XXXXXX)
        chmod 600 "$tmpfile"
        cat > "$tmpfile" <<BOOTSTRAP
You are a claive worker agent named "$name".
- If you notice context compression ("compressing prior messages"), write a handoff signal:
  echo '{"summary":"...","remaining":"...","files_modified":[...]}' > .claive/signals/$name.handoff
BOOTSTRAP
        echo "$prompt" >> "$tmpfile"

        if [ -n "$branch" ]; then
            cmd="git checkout $branch && claude $claude_flags \"\$(cat $tmpfile)\" ; rm -f $tmpfile"
        else
            cmd="claude $claude_flags \"\$(cat $tmpfile)\" ; rm -f $tmpfile"
        fi
    elif [ -n "$branch" ]; then
        cmd="git checkout $branch && claude $claude_flags"
    fi

    tmux new-window -t "$CLAIVE_SESSION" -n "$name" "$cmd"
    tmux select-window -t "$CLAIVE_SESSION:orchestrator" 2>/dev/null || true

    python3 "$CLAIVE_LIB/audit.py" log spawn "$name" 2>/dev/null || true

    echo "Spawned agent '$name'"
    echo "  Model: $model${effort:+ (effort: $effort)}"
    [ -n "$budget" ] && echo "  Budget: \$$budget"
    [ -n "$branch" ] && echo "  Branch: $branch"
}

do_kill() {
    local name="${1:-}"

    if [ -z "$name" ]; then
        echo "Usage: claive kill <name>"
        return 1
    fi

    if ! tmux list-windows -t "$CLAIVE_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$name"; then
        echo "Error: agent '$name' not found"
        return 1
    fi

    tmux kill-window -t "$CLAIVE_SESSION:$name"

    # Clean up EventMesh directories
    rm -rf "$CLAIVE_MESH/inbox/$name" "$CLAIVE_MESH/outbox/$name"
    rm -f "$CLAIVE_MESH/signals/$name.done"

    # Log the action
    python3 "$CLAIVE_LIB/audit.py" log kill "$name" 2>/dev/null || true

    echo "Killed agent '$name'"
}

do_merge() {
    local name="${1:-}"

    if [ -z "$name" ]; then
        echo "Usage: claive merge <name>"
        return 1
    fi

    local branch="agent/$name"

    # Check if branch exists
    if ! git rev-parse --verify "$branch" >/dev/null 2>&1; then
        echo "Error: branch '$branch' does not exist"
        return 1
    fi

    # Attempt merge without committing first (dry run)
    if ! git merge --no-commit --no-ff "$branch" 2>/dev/null; then
        echo "CONFLICT: agent/$name has conflicts with current branch"
        git merge --abort
        python3 "$CLAIVE_LIB/audit.py" log merge-conflict "$name" 2>/dev/null || true
        return 1
    fi

    # Commit the merge
    git commit -m "Merge agent/$name outputs into $(git branch --show-current)"
    python3 "$CLAIVE_LIB/audit.py" log merge "$name" 2>/dev/null || true

    # Clean up branch
    git branch -d "$branch" 2>/dev/null || true

    echo "Merged branch '$branch' successfully"
}
