# Hina Memory Pipeline

A two-tier memory system for an AI assistant:

- **Short-term memory** — `conversation_history` table. Raw, messy, robust. Every message, every session, never summarized or deleted.
- **Long-term memory** — `long_term_memory` table. Clean, deduplicated, bullet-point facts about the user (favorite singer, birthday, key preferences, etc). Built automatically every 2 hours by a systemd timer that runs a bash script calling the Groq API.

```
short-term (conversation_history, messy/raw)
        │
        ▼
 summarize_memory.sh  (runs every 2h via systemd timer)
        │  reads new messages since last checkpoint
        │  sends them + existing long-term facts to Groq
        │  Groq extracts only NEW durable facts (semantic dedup)
        ▼
long-term (long_term_memory, clean bullet facts)
```

---

## 1. Database schema

Three tables, all living in `hina_prod2`:

| Table | Purpose |
|---|---|
| `conversation_history` | Already existed — raw chat log (short-term memory). |
| `long_term_memory` | New — stores extracted durable facts per session. |
| `memory_checkpoint` | New — tracks how far each session has been summarized, so the script never reprocesses old messages. |

See `schema.sql` for the exact `CREATE TABLE` statements. Key points:

- `session_id` collation on the new tables **must match** `conversation_history`'s collation (`utf8mb4_uca1400_ai_ci` in this setup), or joins will throw `Illegal mix of collations`. Always check with `SHOW CREATE TABLE conversation_history\G` before creating new tables that join against it.
- `long_term_memory` has a `UNIQUE KEY (session_id, fact_hash)` — this is the exact-duplicate safety net. `fact_hash` is a `sha256` of the lowercased fact text.
- `memory_checkpoint` has one row per session, tracking `last_processed_id` — the highest `conversation_history.id` already summarized for that session.

---

## 2. How deduplication works

Two layers:

1. **Exact dedup (DB level)** — `fact_hash` + `UNIQUE KEY`. If the exact same fact string is ever generated twice, the `INSERT ... ON DUPLICATE KEY UPDATE` just bumps `last_seen_at` instead of creating a duplicate row.
2. **Semantic dedup (LLM level)** — every time the script summarizes new messages for a session, it also sends the model the *existing* long-term facts for that session (`EXISTING_MEMORY` in the prompt) and instructs it: don't extract anything already covered, even if worded differently. This is what catches "same fact, different words" — e.g. "loves Lana Del Rey" vs "favorite singer is Lana Del Rey" — which a hash or fuzzy string match alone would miss.

---

## 3. The summarizer script

`/opt/hina-memory/summarize_memory.sh`. What it does on every run:

1. **Cooldown check** — if `/var/lib/hina-memory/cooldown_until` holds a future timestamp (set after too many 429s), the run exits immediately without calling the API. This prevents hammering Groq during a rate-limit window.
2. **Find sessions with new messages** — joins `conversation_history` against `memory_checkpoint` to find sessions where `id > last_processed_id`.
3. For each such session:
   - Pulls new messages since the checkpoint (`HISTORY_JSON`).
   - Pulls existing long-term facts for that session (`EXISTING_JSON`).
   - Calls Groq (see model fallback below) with a system prompt instructing extraction of only durable, important facts (favorites, birthdays, key dates, preferences) — explicitly excluding anything already in `EXISTING_JSON`.
   - Inserts any new facts into `long_term_memory`.
   - Advances `memory_checkpoint.last_processed_id` to the latest message id processed — **only if the API call succeeded**. If the whole model chain fails for a session, its checkpoint is left alone so it gets retried on the next run instead of silently losing that chunk of history.

### Model fallback chain

Not all Groq models support `response_format: json_schema` (strict structured output). The script tries, in order:

1. `openai/gpt-oss-120b`
2. `openai/gpt-oss-20b`
3. `qwen/qwen3-32b`

...all using strict `json_schema` mode (guarantees valid, schema-conformant JSON). If every one of those errors out or gets rate-limited, it falls back to:

4. `llama-3.3-70b-versatile`
5. `llama-3.1-8b-instant`

...using looser `json_object` mode (valid JSON guaranteed, but not schema-enforced — the prompt explicitly asks for the `{"facts":[...]}` shape).

### 429 / rate-limit handling

- Every `429` response is logged and counted (`count_429`).
- Hitting one model's rate limit just moves on to the next model — doesn't abort the whole run.
- If **5 or more** 429s happen in a single run (`MAX_429_PER_RUN`, edit in script), the script writes a cooldown timestamp 3 hours out (`COOLDOWN_HOURS`, edit in script) to `/var/lib/hina-memory/cooldown_until` and stops processing further sessions immediately.
- Every subsequent run checks that file first; while `now < cooldown_until`, it logs `in cooldown` and exits without touching the API at all.

### Logs

Everything is appended to `/var/log/hina-memory/summarize.log`:

```bash
tail -f /var/log/hina-memory/summarize.log
```

---

## 4. Setup from scratch

### a) Create directories
```bash
sudo mkdir -p /opt/hina-memory /var/log/hina-memory /etc/hina-memory /var/lib/hina-memory
```

### b) Secrets
```bash
sudo nano /etc/hina-memory/env
```
```
GROQ_API_KEY=your_groq_key_here
MARIADB_ROOT_PASSWORD=your_db_password_here
```
```bash
sudo chmod 600 /etc/hina-memory/env
```

### c) Database
```bash
mariadb -u root -p < schema.sql
```
(or paste the contents of `schema.sql` into the `mariadb` prompt manually)

### d) Script
```bash
sudo cp summarize_memory.sh /opt/hina-memory/
sudo chmod +x /opt/hina-memory/summarize_memory.sh
```

### e) systemd service + timer
```bash
sudo cp hina-memory.service /etc/systemd/system/
sudo cp hina-memory.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hina-memory.timer
```

### f) Verify
```bash
systemctl list-timers | grep hina-memory      # confirms scheduled
sudo systemctl start hina-memory.service       # run once immediately
tail -f /var/log/hina-memory/summarize.log      # watch it work
```

---

## 5. Manual testing

Run the script directly (bypassing the timer) to test changes:
```bash
sudo bash -c 'set -a; source /etc/hina-memory/env; set +a; /opt/hina-memory/summarize_memory.sh'
```

Force a session to be reprocessed (useful after editing the prompt/schema):
```sql
DELETE FROM memory_checkpoint WHERE session_id='some_session_id';
```

Inspect results:
```sql
SELECT * FROM long_term_memory ORDER BY created_at DESC LIMIT 20;
SELECT * FROM memory_checkpoint;
```

Check for accidental fact bloat (semantic dedup failing):
```sql
SELECT session_id, category, COUNT(*) 
FROM long_term_memory 
GROUP BY session_id, category 
ORDER BY COUNT(*) DESC;
```

Clear a cooldown manually if needed:
```bash
sudo rm -f /var/lib/hina-memory/cooldown_until
```

---

## 6. Tuning knobs (inside `summarize_memory.sh`)

| Variable | Default | Meaning |
|---|---|---|
| `MODELS` | gpt-oss-120b, gpt-oss-20b, qwen3-32b | Preferred models, tried in order, strict json_schema |
| `FALLBACK_MODELS` | llama-3.3-70b-versatile, llama-3.1-8b-instant | Last resort, json_object mode |
| `MAX_429_PER_RUN` | 5 | How many rate-limit hits in one run before triggering cooldown |
| `COOLDOWN_HOURS` | 3 | How long to pause all API calls after triggering cooldown |
| Timer `OnUnitActiveSec` | 2h | How often the systemd timer fires (edit `hina-memory.timer`) |

---

## 7. What's NOT built yet

- **Retrieval side**: a step that, before the AI responds to a new message, pulls the relevant `long_term_memory` rows for that session and injects them into the prompt context. Currently this pipeline only *writes* long-term memory — nothing reads it back into the live conversation yet.
- **Pruning**: no automatic cap on how many facts accumulate per session. If a session runs for a very long time, consider adding a periodic job to review/merge/retire stale facts (e.g. via `last_seen_at`).