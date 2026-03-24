#!/usr/bin/env bash
# claive/lib/comms.sh — Agent communication (read/send)

do_read() {
    local name=""
    local lines=50

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --lines)  lines="$2"; shift 2 ;;
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
        echo "Usage: claive read <name> [--lines N]"
        return 1
    fi

    if ! tmux list-windows -t "$CLAIVE_TMUX" -F '#{window_name}' 2>/dev/null | grep -qx "$name"; then
        echo "Error: agent '$name' not found"
        return 1
    fi

    # Capture terminal output
    local output
    output=$(tmux capture-pane -t "$CLAIVE_TMUX:$name" -p -S "-$lines" 2>/dev/null)

    echo "=== Agent: $name (last $lines lines) ==="
    echo "$output"

    # Check for sentinel markers
    if echo "$output" | grep -q '###CLAIVE_DONE:'; then
        local status_val
        status_val=$(echo "$output" | grep -o '###CLAIVE_DONE:[^#]*###' | tail -1 | sed 's/###CLAIVE_DONE:\(.*\)###/\1/')
        echo ""
        echo "[SIGNAL] Agent '$name' reports DONE: $status_val"
    elif echo "$output" | grep -q '###CLAIVE_STATUS:'; then
        local status_val
        status_val=$(echo "$output" | grep -o '###CLAIVE_STATUS:[^#]*###' | tail -1 | sed 's/###CLAIVE_STATUS:\(.*\)###/\1/')
        echo ""
        echo "[STATUS] Agent '$name': $status_val"
    fi

    # Check sideband status file
    local sideband="$CLAIVE_MESH/outbox/$name/status.json"
    if [ -f "$sideband" ]; then
        echo ""
        echo "[SIDEBAND] $(cat "$sideband")"
    fi

    # Log the read
    python3 "$CLAIVE_LIB/audit.py" log read "$name" 2>/dev/null || true
}

do_send() {
    local name="${1:-}"
    local message="${2:-}"

    if [ -z "$name" ] || [ -z "$message" ]; then
        echo "Usage: claive send <name> \"message\""
        return 1
    fi

    if ! tmux list-windows -t "$CLAIVE_TMUX" -F '#{window_name}' 2>/dev/null | grep -qx "$name"; then
        echo "Error: agent '$name' not found"
        return 1
    fi

    # Write to inbox (file-based messaging)
    local inbox_dir="$CLAIVE_MESH/inbox/$name"
    mkdir -p "$inbox_dir"
    local ts
    ts=$(date -u +%Y%m%dT%H%M%SZ)
    echo "$message" > "$inbox_dir/$ts-message.md"

    # Also inject via tmux send-keys for immediate delivery
    tmux send-keys -t "$CLAIVE_TMUX:$name" "$message" Enter

    # Log the action
    python3 "$CLAIVE_LIB/audit.py" log send "$name: $(echo "$message" | head -c 80)" 2>/dev/null || true

    echo "Sent message to '$name'"
}
