-- Hina memory schema (Ollama edition)
-- Run against the same DB as conversation_history (hina_prod2)
-- IMPORTANT: collation matches conversation_history's session_id collation
-- (utf8mb4_uca1400_ai_ci). Check yours first with:
--   SHOW CREATE TABLE conversation_history\G
-- and adjust COLLATE below if it differs.

USE hina_prod2;

DROP TABLE IF EXISTS long_term_memory;
DROP TABLE IF EXISTS memory_checkpoint;
DROP TABLE IF EXISTS short_term_memory;

-- ============================================================
-- LONG-TERM: durable, deduplicated facts. One new fact per
-- session per run (the single most important one), never a
-- batch. Same shape as before, just fed by Ollama now instead
-- of Groq.
-- ============================================================
CREATE TABLE long_term_memory (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci NOT NULL,
    category VARCHAR(50) NOT NULL,        -- favorite_singer, favorite_person, favorite_place,
                                           -- birthday, key_date, preference, misc
    fact TEXT NOT NULL,                   -- the bullet point itself, third person, <15 words
    fact_hash CHAR(64) NOT NULL,          -- sha256 of lowercased fact, for exact dedup
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_session_fact (session_id, fact_hash),
    KEY idx_session (session_id),
    KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

CREATE TABLE memory_checkpoint (
    session_id VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci PRIMARY KEY,
    last_processed_id BIGINT NOT NULL DEFAULT 0,  -- highest conversation_history.id summarized for long-term
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;

-- ============================================================
-- SHORT-TERM: a single rolling bullet-point summary per session.
-- Unlike long-term, this is REPLACED every cycle (not appended)
-- and can hold many bullets at once. Its own checkpoint lives
-- right on the row so the two pipelines never share state.
-- ============================================================
CREATE TABLE short_term_memory (
    session_id VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci PRIMARY KEY,
    summary TEXT NOT NULL,                         -- bullet points, "- " prefixed, one per line
    last_processed_id BIGINT NOT NULL DEFAULT 0,   -- highest conversation_history.id folded into summary
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
