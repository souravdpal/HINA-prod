#!/usr/bin/env bash
# /opt/hina-memory/summarize_memory.sh
set -euo pipefail

DB_USER="root"
DB_PASS="${MARIADB_ROOT_PASSWORD:?set MARIADB_ROOT_PASSWORD in env file}"
DB_NAME="hina_prod2"
GROQ_API_KEY="${GROQ_API_KEY:?set GROQ_API_KEY in env file}"
LOG_FILE="/var/log/hina-memory/summarize.log"
STATE_DIR="/var/lib/hina-memory"
COOLDOWN_FILE="$STATE_DIR/cooldown_until"

# Models to try in order. Only models supporting json_schema go first;
# json_object-capable models act as a final fallback.
MODELS=(
    "openai/gpt-oss-120b"
    "openai/gpt-oss-20b"
    "qwen/qwen3-32b"
)
# Fallback model list using json_object mode (works on any chat model,
# used only if every json_schema-capable model fails)
FALLBACK_MODELS=(
    "llama-3.3-70b-versatile"
    "llama-3.1-8b-instant"
)

MAX_429_PER_RUN=5
COOLDOWN_HOURS=3

mkdir -p "$STATE_DIR"

mysql_exec() {
    mariadb -u "$DB_USER" -p"$DB_PASS" -N -B -D "$DB_NAME" -e "$1"
}

mysql_esc() {
    printf '%s' "$1" | sed "s/'/''/g; s/\\\\/\\\\\\\\/g"
}

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE"
}

# --- cooldown check -----------------------------------------------------
now_epoch=$(date +%s)
if [ -f "$COOLDOWN_FILE" ]; then
    cooldown_until=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
    if [ "$now_epoch" -lt "$cooldown_until" ]; then
        remaining=$(( (cooldown_until - now_epoch) / 60 ))
        log "in cooldown (rate limited earlier), ${remaining}m remaining, skipping run"
        exit 0
    else
        rm -f "$COOLDOWN_FILE"
    fi
fi

log "=== run start ==="

count_429=0

trigger_cooldown() {
    local until=$(( $(date +%s) + COOLDOWN_HOURS * 3600 ))
    echo "$until" > "$COOLDOWN_FILE"
    log "too many 429s ($count_429), entering cooldown for ${COOLDOWN_HOURS}h"
}

# call_groq: tries MODELS with json_schema, then FALLBACK_MODELS with json_object.
# Sets global CONTENT on success, empty on total failure.
call_groq() {
    local sys="$1" usr="$2"
    CONTENT=""

    for model in "${MODELS[@]}"; do
        local payload
        payload=$(jq -n \
            --arg model "$model" \
            --arg sys "$sys" \
            --arg usr "$usr" \
            '{
                model: $model,
                messages: [
                    {role: "system", content: $sys},
                    {role: "user", content: $usr}
                ],
                temperature: 0.1,
                response_format: {
                    type: "json_schema",
                    json_schema: {
                        name: "extracted_facts",
                        strict: true,
                        schema: {
                            type: "object",
                            properties: {
                                facts: {
                                    type: "array",
                                    items: {
                                        type: "object",
                                        properties: {
                                            category: {
                                                type: "string",
                                                enum: ["favorite_singer","favorite_person","favorite_place","birthday","key_date","preference","misc"]
                                            },
                                            fact: { type: "string" }
                                        },
                                        required: ["category","fact"],
                                        additionalProperties: false
                                    }
                                }
                            },
                            required: ["facts"],
                            additionalProperties: false
                        }
                    }
                }
            }')

        local http_code response retry_after
        response=$(curl -s -w "\n%{http_code}" https://api.groq.com/openai/v1/chat/completions \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $GROQ_API_KEY" \
            -d "$payload")
        http_code=$(echo "$response" | tail -n1)
        response=$(echo "$response" | sed '$d')

        if [ "$http_code" = "200" ]; then
            CONTENT=$(echo "$response" | jq -r '.choices[0].message.content // empty')
            if [ -n "$CONTENT" ]; then
                log "model=$model OK (json_schema)"
                return 0
            fi
        elif [ "$http_code" = "429" ]; then
            count_429=$((count_429 + 1))
            retry_after=$(echo "$response" | jq -r '.error.message // empty')
            log "model=$model 429 rate limited: $retry_after"
            if [ "$count_429" -ge "$MAX_429_PER_RUN" ]; then
                trigger_cooldown
                return 1
            fi
            continue
        else
            local err_type
            err_type=$(echo "$response" | jq -r '.error.type // empty')
            log "model=$model failed (http=$http_code type=$err_type), trying next model"
            continue
        fi
    done

    # fallback: json_object mode on plain chat models
    for model in "${FALLBACK_MODELS[@]}"; do
        local sys_fallback="$sys
Return ONLY a valid JSON object of the form {\"facts\":[{\"category\":\"...\",\"fact\":\"...\"}]}. No prose, no markdown fences."
        local payload
        payload=$(jq -n \
            --arg model "$model" \
            --arg sys "$sys_fallback" \
            --arg usr "$usr" \
            '{
                model: $model,
                messages: [
                    {role: "system", content: $sys},
                    {role: "user", content: $usr}
                ],
                temperature: 0.1,
                response_format: { type: "json_object" }
            }')

        local http_code response
        response=$(curl -s -w "\n%{http_code}" https://api.groq.com/openai/v1/chat/completions \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $GROQ_API_KEY" \
            -d "$payload")
        http_code=$(echo "$response" | tail -n1)
        response=$(echo "$response" | sed '$d')

        if [ "$http_code" = "200" ]; then
            CONTENT=$(echo "$response" | jq -r '.choices[0].message.content // empty')
            if [ -n "$CONTENT" ]; then
                log "model=$model OK (json_object fallback)"
                return 0
            fi
        elif [ "$http_code" = "429" ]; then
            count_429=$((count_429 + 1))
            log "model=$model 429 rate limited (fallback)"
            if [ "$count_429" -ge "$MAX_429_PER_RUN" ]; then
                trigger_cooldown
                return 1
            fi
            continue
        else
            log "model=$model failed (http=$http_code) (fallback)"
            continue
        fi
    done

    log "ERROR: all models exhausted, no valid response"
    return 1
}

SESSIONS=$(mysql_exec "
    SELECT DISTINCT ch.session_id
    FROM conversation_history ch
    LEFT JOIN memory_checkpoint mc ON mc.session_id = ch.session_id
    WHERE ch.id > COALESCE(mc.last_processed_id, 0)
")

if [ -z "$SESSIONS" ]; then
    log "no new sessions to process"
    exit 0
fi

while IFS= read -r SESSION_ID; do
    [ -z "$SESSION_ID" ] && continue

    # stop processing further sessions this run if we already hit cooldown
    if [ -f "$COOLDOWN_FILE" ]; then
        log "cooldown triggered mid-run, stopping further processing"
        break
    fi

    log "processing session=$SESSION_ID"

    LAST_ID=$(mysql_exec "SELECT COALESCE(last_processed_id,0) FROM memory_checkpoint WHERE session_id='$SESSION_ID'")
    LAST_ID=${LAST_ID:-0}

    HISTORY_JSON=$(mysql_exec "
        SELECT JSON_ARRAYAGG(JSON_OBJECT('role', role, 'message', message))
        FROM conversation_history
        WHERE session_id='$SESSION_ID' AND id > $LAST_ID
        ORDER BY id ASC
    ")

    MAX_ID=$(mysql_exec "SELECT MAX(id) FROM conversation_history WHERE session_id='$SESSION_ID'")

    if [ -z "$HISTORY_JSON" ] || [ "$HISTORY_JSON" = "NULL" ]; then
        log "no history rows for $SESSION_ID, skipping"
        continue
    fi

    EXISTING_JSON=$(mysql_exec "
        SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT('category', category, 'fact', fact)), JSON_ARRAY())
        FROM long_term_memory
        WHERE session_id='$SESSION_ID'
    ")

    SYSTEM_PROMPT='You extract durable long-term facts about the user from a conversation.
Rules:
- Only extract stable, important facts: favorite things (favorite_singer, favorite_person, favorite_place), birthdays/key dates, strong preferences, or important commitments.
- Do NOT extract small talk, transient statements, or anything already present in EXISTING_MEMORY (even if worded differently — check meaning, not exact text).
- Keep each fact short (under 15 words), third person, e.g. "User'\''s favorite singer is Arijit Singh".
- If nothing new and important is found, return an empty facts array.
- Do not overwhelm — only truly memorable, durable facts.'

    USER_PROMPT=$(cat <<EOF
EXISTING_MEMORY:
$EXISTING_JSON

NEW_CONVERSATION_HISTORY:
$HISTORY_JSON

Extract new durable facts not already covered in EXISTING_MEMORY.
EOF
)

    if ! call_groq "$SYSTEM_PROMPT" "$USER_PROMPT"; then
        log "skipping session=$SESSION_ID due to API failure (checkpoint NOT advanced)"
        continue
    fi

    CLEAN_JSON="$CONTENT"
    FACT_COUNT=$(echo "$CLEAN_JSON" | jq '.facts | length' 2>/dev/null || echo 0)

    if [ "$FACT_COUNT" -gt 0 ] 2>/dev/null; then
        echo "$CLEAN_JSON" | jq -c '.facts[]' | while read -r item; do
            CATEGORY=$(echo "$item" | jq -r '.category')
            FACT=$(echo "$item" | jq -r '.fact')
            FACT_ESCAPED=$(mysql_esc "$FACT")
            FACT_HASH=$(echo -n "$FACT" | tr '[:upper:]' '[:lower:]' | sha256sum | awk '{print $1}')

            mysql_exec "
                INSERT INTO long_term_memory (session_id, category, fact, fact_hash)
                VALUES ('$SESSION_ID', '$CATEGORY', '$FACT_ESCAPED', '$FACT_HASH')
                ON DUPLICATE KEY UPDATE last_seen_at = CURRENT_TIMESTAMP
            "
            log "saved fact [$CATEGORY]: $FACT"
        done
    else
        log "no new facts for session=$SESSION_ID"
    fi

    mysql_exec "
        INSERT INTO memory_checkpoint (session_id, last_processed_id)
        VALUES ('$SESSION_ID', $MAX_ID)
        ON DUPLICATE KEY UPDATE last_processed_id = $MAX_ID
    "

done <<< "$SESSIONS"

log "=== run complete (429s this run: $count_429) ==="