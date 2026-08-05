#!/usr/bin/env bash
# /opt/hina-memory/summarize_shortterm.sh
#
# Always-on service (Restart=always via systemd). Loops forever,
# keeps a single rolling bullet-point summary per session in
# short_term_memory, fed entirely by a local Ollama model.
# No JSON in or out — the model just writes bullets.
set -uo pipefail   # no -e: a bad cycle should not kill the always-on service

DB_USER="root"
DB_PASS="${MARIADB_ROOT_PASSWORD:?set MARIADB_ROOT_PASSWORD in env file}"
DB_NAME="hina_prod2"
LOG_FILE="/var/log/hina-memory/shortterm.log"
STATE_DIR="/var/lib/hina-memory"
LOCK_FILE="$STATE_DIR/ollama.lock"     # SHARED with the long-term script — do not change independently

OLLAMA_URL="http://127.0.0.1:11434/api/generate"
MODEL="granite3.1-moe:1b"
LOCK_TIMEOUT=180        # seconds to wait for the shared ollama lock before giving up this cycle
LOOP_INTERVAL=45        # seconds between polling cycles
MAX_MESSAGES_PER_CALL=40
INTER_SESSION_SLEEP=2   # small breather between sessions in the same cycle

mkdir -p "$STATE_DIR"

mysql_exec() { mariadb -u "$DB_USER" -p"$DB_PASS" -N -B -D "$DB_NAME" -e "$1"; }
mysql_esc()  { printf '%s' "$1" | sed "s/'/''/g; s/\\\\/\\\\\\\\/g"; }
log()        { echo "$(date '+%Y-%m-%d %H:%M:%S') [short] $*" >> "$LOG_FILE"; }

# ollama_call: serializes on the shared lock so short-term and
# long-term never hit the Ollama server at the same instant.
ollama_call() {
    local prompt="$1"
    local payload response http_code

    payload=$(jq -n --arg model "$MODEL" --arg prompt "$prompt" \
        '{model:$model, prompt:$prompt, stream:false, options:{temperature:0.2}}')

    exec 200>"$LOCK_FILE"
    if ! flock -w "$LOCK_TIMEOUT" 200; then
        log "could not acquire ollama lock within ${LOCK_TIMEOUT}s, skipping this call"
        return 1
    fi

    response=$(curl -s -w "\n%{http_code}" "$OLLAMA_URL" \
        -H "Content-Type: application/json" -d "$payload")
    http_code=$(echo "$response" | tail -n1)
    response=$(echo "$response" | sed '$d')
    flock -u 200

    if [ "$http_code" != "200" ]; then
        log "ollama http=$http_code response=$response"
        return 1
    fi

    CONTENT=$(echo "$response" | jq -r '.response // empty')
    if [ -z "$CONTENT" ]; then
        log "empty ollama response"
        return 1
    fi
    return 0
}

process_session() {
    local session_id="$1"

    local last_id prev_summary
    last_id=$(mysql_exec "SELECT COALESCE(last_processed_id,0) FROM short_term_memory WHERE session_id='$session_id'")
    last_id=${last_id:-0}
    prev_summary=$(mysql_exec "SELECT COALESCE(summary,'') FROM short_term_memory WHERE session_id='$session_id'")

    local history_json max_id
    history_json=$(mysql_exec "
        SELECT JSON_ARRAYAGG(JSON_OBJECT('role', role, 'message', message))
        FROM (
            SELECT role, message FROM conversation_history
            WHERE session_id='$session_id' AND id > $last_id
            ORDER BY id ASC
            LIMIT $MAX_MESSAGES_PER_CALL
        ) t
    ")
    max_id=$(mysql_exec "
        SELECT MAX(id) FROM (
            SELECT id FROM conversation_history
            WHERE session_id='$session_id' AND id > $last_id
            ORDER BY id ASC
            LIMIT $MAX_MESSAGES_PER_CALL
        ) t
    ")

    if [ -z "$history_json" ] || [ "$history_json" = "NULL" ] || [ -z "$max_id" ] || [ "$max_id" = "NULL" ]; then
        return 0
    fi

    local prompt
    prompt=$(cat <<EOF
You maintain a running short-term summary of a conversation as plain bullet points.
Do not output JSON. Do not output headings or preamble. Output ONLY bullet lines, each starting with "- ".
Merge PREVIOUS_SUMMARY with NEW_MESSAGES into one updated list (max 12 bullets total).
Drop stale or least-relevant bullets if you'd otherwise exceed 12. Keep it factual and concise.

PREVIOUS_SUMMARY:
$prev_summary

NEW_MESSAGES (JSON):
$history_json

Updated bullet-point summary:
EOF
)

    if ! ollama_call "$prompt"; then
        log "session=$session_id ollama call failed, will retry next cycle"
        return 1
    fi

    local summary_escaped
    summary_escaped=$(mysql_esc "$CONTENT")

    mysql_exec "
        INSERT INTO short_term_memory (session_id, summary, last_processed_id)
        VALUES ('$session_id', '$summary_escaped', $max_id)
        ON DUPLICATE KEY UPDATE summary = '$summary_escaped', last_processed_id = $max_id, updated_at = CURRENT_TIMESTAMP
    "
    log "session=$session_id updated (through id=$max_id)"
    return 0
}

log "=== shortterm service starting (model=$MODEL, interval=${LOOP_INTERVAL}s) ==="

while true; do
    SESSIONS=$(mysql_exec "
        SELECT DISTINCT ch.session_id
        FROM conversation_history ch
        LEFT JOIN short_term_memory stm ON stm.session_id = ch.session_id
        WHERE ch.id > COALESCE(stm.last_processed_id, 0)
    ")

    if [ -n "$SESSIONS" ]; then
        while IFS= read -r SESSION_ID; do
            [ -z "$SESSION_ID" ] && continue
            process_session "$SESSION_ID"
            sleep "$INTER_SESSION_SLEEP"
        done <<< "$SESSIONS"
    fi

    sleep "$LOOP_INTERVAL"
done
