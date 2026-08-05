from ollama_summrizer import OllamaClient

# Initialize the client (sets a default model, but you can override it anytime)
ai = OllamaClient(default_model="qwen2.5:0.5b")

sys_prompt = "You are a senior systems engineer who gives brutally honest architectural feedback."
query = "Should I build my next microservice mesh entirely using custom Bash scripts and netcat?"


full_text = ai.get_full_response(
    system_prompt="""
// server.js
const express = require('express');
const path = require('path');
const http = require('http');
const WebSocket = require('ws');
const { spawn } = require('child_process');
const mysql = require('mysql2/promise');
const fs = require('fs');
const crypto = require('crypto');
const multer = require('multer');
const favicon = require('serve-favicon');

const app = express();
const PORT = 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
app.use(favicon(path.join(__dirname, 'assets', 'hina.png')));
const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: '/ws' });

// ============================================================
// File / image uploads — chat attachments
// ============================================================
const DATA_FILES_DIR = path.join(__dirname, 'data_files');
fs.mkdirSync(DATA_FILES_DIR, { recursive: true });

const IMAGE_EXT = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.heic', '.heif']);


function isImageFile(originalName, mimetype) {
    if (typeof mimetype === 'string' && mimetype.startsWith('image/')) return true;
    return IMAGE_EXT.has(path.extname(originalName || '').toLowerCase());
}

const uploadStorage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, DATA_FILES_DIR),
    filename: (req, file, cb) => {
        const safeBase = file.originalname.replace(/[^a-zA-Z0-9._-]/g, '_');
        const unique = crypto.randomBytes(6).toString('hex');
        cb(null, `${Date.now()}-${unique}-${safeBase}`);
    }
});

const upload = multer({
    storage: uploadStorage,
    limits: { fileSize: 50 * 1024 * 1024, files: 10 }
});

// ------------------------------------------------------------
// Image URL cache — local saved_name -> permanent ImageKit CDN url.
// image2text.py uploads every image to ImageKit and then deletes the
// local copy, which used to leave any chat bubble still pointing at
// /data_files/<saved_name> broken (404 / "wrong location" on click).
// Now image2text.py POSTs the mapping here BEFORE deleting the local
// file, and the /data_files route below 302-redirects to the cached
// CDN url whenever the local file is gone — old links keep working,
// and we're not re-uploading/re-hosting the image ourselves.
// ------------------------------------------------------------
const IMAGE_CACHE_FILE = path.join(__dirname, 'image_url_cache.json');

function readImageCache() {
    try {
        return JSON.parse(fs.readFileSync(IMAGE_CACHE_FILE, 'utf8'));
    } catch (_) {
        return {};
    }
}

function writeImageCache(cache) {
    try {
        fs.writeFileSync(IMAGE_CACHE_FILE, JSON.stringify(cache, null, 2));
    } catch (err) {
        console.error('[IMG CACHE] failed to persist cache:', err.message);
    }
}

// ============================================================
// HINA-generated files (code files the agent writes for the user
// to view/download) — separate from chat upload attachments above.
// Routes live in routes/hinaFiles.js.
// ============================================================
const hinaFilesRouter = require('./routes/hinaFiles');
app.use('/download/hina/files', hinaFilesRouter);
const HINA_DB_DIR = hinaFilesRouter.HINA_DB_DIR;


app.post('/internal/cache_image', (req, res) => {
    const { saved_name, imagekit_url } = req.body || {};
    if (!saved_name || !imagekit_url) {
        return res.status(400).json({ error: 'saved_name and imagekit_url required' });
    }
    const cache = readImageCache();
    cache[saved_name] = imagekit_url;
    writeImageCache(cache);
    res.json({ status: 'ok' });
});

// Intercept /data_files/<file> requests: if the file still exists
// locally, fall through to express.static below. If it doesn't
// (because image2text.py already shipped it to ImageKit and cleaned
// up), redirect to the cached CDN url instead of 404ing.
app.get('/data_files/:filename', (req, res, next) => {
    const filename = req.params.filename;
    const localPath = path.join(DATA_FILES_DIR, filename);
    if (fs.existsSync(localPath)) return next();

    const cache = readImageCache();
    const cdnUrl = cache[filename];
    if (cdnUrl) return res.redirect(302, cdnUrl);

    return res.status(404).json({ error: 'file not found and no cached CDN url for it' });
});

app.use('/data_files', express.static(DATA_FILES_DIR));

// ============================================================
// Voice-reply toggle — cached on disk so it survives restarts
// ============================================================
// Single source of truth for whether HINA should speak replies
// aloud. The browser toggle writes here (POST /voice/toggle) and
// caches the value in localStorage for instant UI state on load;
// the file on disk is authoritative and is what /voice/status
// (used by the browser AND by voice_status.py) reads from.
const VOICE_STATE_FILE = path.join(__dirname, 'voice_state.json');

function readVoiceState() {
    try {
        const raw = fs.readFileSync(VOICE_STATE_FILE, 'utf8');
        const parsed = JSON.parse(raw);
        return parsed && parsed.voice_enabled === true;
    } catch (_) {
        return false; // default: off
    }
}

function writeVoiceState(enabled) {
    fs.writeFileSync(VOICE_STATE_FILE, JSON.stringify({ voice_enabled: !!enabled, updated_at: new Date().toISOString() }, null, 2));
}

app.get('/voice/status', (req, res) => {
    const enabled = readVoiceState();
    res.json({ voice_enabled: enabled, value: enabled ? 1 : 0 });
});

app.post('/voice/toggle', (req, res) => {
    const enabled = (req.body && req.body.enabled) === true;
    try {
        writeVoiceState(enabled);
        res.json({ status: 'ok', voice_enabled: enabled, value: enabled ? 1 : 0 });
    } catch (err) {
        console.error('[VOICE ERR] failed to persist toggle state:', err.message);
        res.status(500).json({ error: 'failed to save voice toggle state' });
    }
});

// ============================================================
// MariaDB — conversation history / future memory store
// ============================================================
const DB_CONFIG = {
    host: '127.0.0.1',
    user: 'root',
    password: 'souravdp',
    database: 'hina_prod2'
};

let db;

async function initDb() {
    db = await mysql.createPool(DB_CONFIG);

    await db.query(`
        CREATE TABLE IF NOT EXISTS conversation_history (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(64) NOT NULL,
            role ENUM('user','agent','other') NOT NULL,
            kind ENUM('user_message','final_reply','trace_step','noise') NOT NULL DEFAULT 'trace_step',
            agent_name VARCHAR(100) DEFAULT NULL,
            state VARCHAR(100) DEFAULT NULL,
            icon VARCHAR(100) DEFAULT NULL,
            message TEXT NOT NULL,
            attachments JSON DEFAULT NULL,
            is_voice BOOLEAN DEFAULT FALSE,
            done BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_session (session_id),
            INDEX idx_created (created_at),
            INDEX idx_session_kind (session_id, kind)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    `);

    // The table may already exist from an earlier schema version.
    // CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so
    // patch older databases in place rather than requiring a manual
    // migration every time the schema grows.
    const migrations = [
        `ALTER TABLE conversation_history MODIFY COLUMN role ENUM('user','agent','other') NOT NULL`,
        `ALTER TABLE conversation_history ADD COLUMN IF NOT EXISTS kind ENUM('user_message','final_reply','trace_step','noise') NOT NULL DEFAULT 'trace_step'`,
        `ALTER TABLE conversation_history ADD COLUMN IF NOT EXISTS done BOOLEAN DEFAULT FALSE`,
        `ALTER TABLE conversation_history ADD COLUMN IF NOT EXISTS attachments JSON DEFAULT NULL`,
        `ALTER TABLE conversation_history ADD INDEX IF NOT EXISTS idx_session_kind (session_id, kind)`
    ];
    for (const sql of migrations) {
        try {
            await db.query(sql);
        } catch (err) {
            console.error('[DB ERR] migration failed:', err.message, '| sql:', sql);
        }
    }

    console.log('[DB] connected + conversation_history ready (full history retained, no trimming)');
}

// History is retained in FULL now — nothing is auto-deleted. The old
// HISTORY_LIMIT=10 trim was silently wiping everything past the last
// 10 rows per session, which is exactly why history used to vanish
// and reload messy. /history now differentiates rows by `kind`
// instead of deleting them, so the UI can reconstruct turns properly
// and a memory feed can pull only the clean signal.
async function saveMessage({ session_id, role, kind = 'trace_step', agent_name = null, state = null, icon = null, message, is_voice = false, done = false, attachments = null }) {
    if (!db) return;
    // message is NOT NULL in the schema — fall back to a placeholder
    // rather than silently dropping the row, so "store everything"
    // actually means everything, even a payload with no text/ui_data.
    const safeMessage = (typeof message === 'string' && message.trim()) ? message : '[no content]';
    // Stored as JSON so the frontend can re-render the actual <img>/file
    // chip on history reload instead of just the "[image:name]" text
    // note baked into `message` (that note stays too, since it's what
    // gives the LLM context that an attachment was present).
    const safeAttachments = (Array.isArray(attachments) && attachments.length) ? JSON.stringify(attachments) : null;
    try {
        await db.query(
            `INSERT INTO conversation_history (session_id, role, kind, agent_name, state, icon, message, is_voice, done, attachments)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
            [session_id, role, kind, agent_name, state, icon, safeMessage, is_voice, done, safeAttachments]
        );
    } catch (err) {
        console.error('[DB ERR] insert failed:', err.message);
    }
}

// ============================================================
// WebSocket telemetry
// ============================================================
let sessionActive = false;
let currentSessionId = null;

function broadcast(data) {
    const payload = JSON.stringify(data);
    wss.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) client.send(payload);
    });
}

wss.on('connection', (ws) => {
    console.log('[WS] client connected');
    ws.on('close', () => console.log('[WS] client disconnected'));
    ws.on('error', (err) => console.error('[WS ERR]', err.message));
});

// ============================================================
// stt_server.py — persistent STT process, handshake API
// ============================================================
// stt_server.py loads the whisper model ONCE and stays resident for
// the whole voice session — no more reloading the model on every
// utterance. It no longer touches the system mic either: live.js
// records audio in the browser (MediaRecorder) and POSTs the clip to
// /live/transcribe, which forwards the bytes to stt_server.py over a
// tiny local HTTP handshake (GET /health, POST /load, POST /unload,
// POST /transcribe) and relays the result back over /ws.
//
//   /live/start  -> spawn stt_server.py if not running, POST /load,
//                   poll /health until ready=true, THEN tell the
//                   client it's safe to start recording.
//   /live/transcribe -> forward one audio clip, get text back, kick
//                   off the normal hina_brain.py reply pipeline.
//   /live/stop   -> POST /unload (frees the model from memory) and
//                   kill the child process.
const STT_HOST = '127.0.0.1';
const STT_PORT = 8765;

let sttProc = null;

function sttRequest(method, urlPath, body, contentType) {
    return new Promise((resolve, reject) => {
        const data = body ? (Buffer.isBuffer(body) ? body : Buffer.from(body)) : null;
        const req = http.request({
            host: STT_HOST,
            port: STT_PORT,
            path: urlPath,
            method,
            headers: data ? { 'Content-Type': contentType || 'application/json', 'Content-Length': data.length } : {}
        }, (res) => {
            const chunks = [];
            res.on('data', (c) => chunks.push(c));
            res.on('end', () => {
                let parsed = {};
                try { parsed = JSON.parse(Buffer.concat(chunks).toString() || '{}'); } catch (_) {}
                resolve({ status: res.statusCode, body: parsed });
            });
        });
        req.on('error', reject);
        if (data) req.write(data);
        req.end();
    });
}

function spawnSttServer() {
    if (sttProc) return;
    sttProc = spawn('python3', [path.join(__dirname, 'core', 'stt_server.py'), String(STT_PORT)], {
        stdio: ['ignore', 'pipe', 'pipe']
    });
    sttProc.stdout.on('data', (c) => console.log(`[STT] ${c.toString().trim()}`));
    sttProc.stderr.on('data', (c) => console.error(`[STT ERR] ${c.toString().trim()}`));
    sttProc.on('exit', () => { sttProc = null; });
    sttProc.on('error', (err) => {
        console.error('[SPAWN ERR] Failed to launch stt_server.py:', err.message);
        sttProc = null;
    });
}

async function waitForSttReady(timeoutMs = 30000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        try {
            const r = await sttRequest('GET', '/health');
            if (r.body && r.body.ready) return true;
        } catch (_) { /* server still booting — keep polling */ }
        await new Promise((r) => setTimeout(r, 400));
    }
    return false;
}

function stopSttServer() {
    if (sttProc) {
        try { sttProc.kill(); } catch (_) {}
        sttProc = null;
    }
}

// Every voice (or text) turn should end in a 'done' push or a TTS
// close event, which is what returns the live page to 'listening'.
// If hina_brain.py crashes, hangs, or silently exits without ever
// pushing anything, nothing would otherwise fire — this watchdog is
// the fallback: if the turn hasn't resolved within TURN_TIMEOUT_MS,
// force the UI back to listening (with an error state flash) so the
// mic comes back instead of staying stuck on "thinking" forever.
const TURN_TIMEOUT_MS = 25000;
let turnWatchdog = null;

function armTurnWatchdog() {
    clearTurnWatchdog();
    turnWatchdog = setTimeout(() => {
        console.error('[WATCHDOG] turn timed out with no reply — recovering to listening');
        sessionActive = false;
        broadcast({ type: 'state', state: 'error' });
        setTimeout(() => broadcast({ type: 'state', state: 'listening' }), 1200);
    }, TURN_TIMEOUT_MS);
}

function clearTurnWatchdog() {
    if (turnWatchdog) { clearTimeout(turnWatchdog); turnWatchdog = null; }
}

// Voice reply -> the standard hina_brain.py text pipeline, reused so
// the reply, its DB row, and its TTS playback all go through the
// exact same path as a typed message (see /internal/push below).
function dispatchVoiceText(session_id, text) {
    sessionActive = true;
    currentSessionId = session_id;
    saveMessage({ session_id, role: 'user', kind: 'user_message', message: text, is_voice: true });
    armTurnWatchdog();

    const py = spawn('python3', [path.join(__dirname, 'core', 'hina_brain.py'), text], {
        detached: true,
        stdio: ['ignore', 'pipe', 'pipe']
    });
    py.stdout.on('data', (c) => console.log(`[PY OUT] ${c}`));
    py.stderr.on('data', (c) => console.error(`[PY ERR] ${c}`));
    py.on('error', (err) => {
        console.error('[SPAWN ERR] hina_brain.py:', err.message);
        clearTurnWatchdog();
        broadcast({ type: 'state', state: 'error' });
        setTimeout(() => broadcast({ type: 'state', state: 'listening' }), 1200);
    });
    py.on('exit', (code) => {
        // A clean run pushes {done:true} itself (handled in
        // /internal/push, which clears the watchdog there). If it
        // exited non-zero — or exited 0 but never actually pushed
        // anything — the watchdog is still armed and will catch it.
        // We only need to react here to the fast, obvious failure case
        // so the mic doesn't sit dark for the full timeout window.
        if (code !== 0 && turnWatchdog) {
            console.error(`[PY] hina_brain.py exited with code ${code}`);
            clearTurnWatchdog();
            broadcast({ type: 'state', state: 'error' });
            setTimeout(() => broadcast({ type: 'state', state: 'listening' }), 1200);
        }
    });
    py.unref();
}

app.post('/live/start', async (req, res) => {
    const session_id = (req.body && req.body.session_id) || 'default';
    currentSessionId = session_id;
    sessionActive = true;

    spawnSttServer();
    broadcast({ type: 'state', state: 'loading' });
    try { await sttRequest('POST', '/load'); } catch (_) {}
    const ready = await waitForSttReady();

    broadcast({ type: 'state', state: ready ? 'listening' : 'error' });
    res.json({ status: ready ? 'ready' : 'timeout' });
});

app.post('/live/stop', async (req, res) => {
    clearTurnWatchdog();
    try { await sttRequest('POST', '/unload'); } catch (_) {}
    stopSttServer();
    broadcast({ type: 'state', state: 'idle' });
    res.json({ status: 'stopped' });
});

// live.js records one utterance in the browser and POSTs the raw
// audio bytes here (Content-Type stays whatever MediaRecorder used,
// e.g. audio/webm — stt_server.py's PyAV backend decodes it directly,
// no client-side re-encoding needed).
app.post('/live/transcribe', express.raw({ type: '*/*', limit: '20mb' }), async (req, res) => {
    const session_id = req.query.session_id || currentSessionId || 'default';
    const audio = req.body;

    if (!audio || !audio.length) {
        return res.status(400).json({ error: 'no audio received' });
    }

    let text = '';
    try {
        const r = await sttRequest('POST', '/transcribe', audio, req.headers['content-type'] || 'audio/webm');
        if (r.status !== 200) throw new Error((r.body && r.body.error) || `stt server returned ${r.status}`);
        text = (r.body && r.body.text) || '';
    } catch (err) {
        console.error('[STT] transcribe request failed:', err.message);
        broadcast({ type: 'state', state: 'error' });
        return res.status(502).json({ error: 'stt request failed' });
    }

    if (!text.trim()) {
        // nothing intelligible — back to listening, no wasted turn
        broadcast({ type: 'state', state: 'listening' });
        return res.json({ status: 'empty', text: '' });
    }

    broadcast({ type: 'transcript', role: 'user', text });
    broadcast({ type: 'state', state: 'thinking' });
    dispatchVoiceText(session_id, text);

    res.json({ status: 'dispatched', text });
});

app.post('/internal/push', (req, res) => {
    const data = (req.body && typeof req.body === 'object') ? req.body : {};

    // 1. HYGIENE PROTOCOL: these classify what KIND of push this is —
    // they used to decide whether to store it at all. Now they only
    // decide the ROLE it's stored under and whether it's broadcast to
    // the live UI. Nothing gets silently dropped from history anymore.
    const isSystemArchitecture = data.text && data.text.includes('HINA CORE ARCHITECTURE');
    const isBackgroundAgent = data.agent_name === 'AI_CALL' || data.agent_name === 'system';
    const isRawToolLog = data.text && (data.text.startsWith('CallToolResult') || data.text.includes('[PY ERR]') || data.text.includes('HTTP Request:'));
    const isNoise = isSystemArchitecture || isBackgroundAgent || isRawToolLog;

    // 2. Store EVERYTHING — clean agent text, noisy/background pushes,
    // and structured ui_data payloads (which have no `text` at all).
    // Noise and anything that isn't a plain user/agent message goes in
    // under role 'other' so /history reads for 'user'/'agent' stay
    // clean, but nothing is lost — it's just filed correctly instead
    // of being thrown away.
    const storedMessage = typeof data.text === 'string' && data.text
        ? data.text
        : (data.ui_data !== undefined ? JSON.stringify({ ui_type: data.ui_type || null, ui_data: data.ui_data }) : JSON.stringify(data));

    const storedRole = isNoise ? 'other' : 'agent';
    const isDone = data.done === true || data.state === 'SYS_DONE';

    // kind is the thing that actually lets us tell "real message" from
    // "waste data" later: noise is always noise; a non-noise agent push
    // is only a final_reply once it's marked done (mirrors the same
    // done-flag split the live UI already uses to decide trace-step vs
    // finished bubble) — everything in between is just a trace_step.
    const storedKind = isNoise ? 'noise' : (isDone ? 'final_reply' : 'trace_step');

    saveMessage({
        session_id: currentSessionId || 'default',
        role: storedRole,
        kind: storedKind,
        agent_name: data.agent_name || null,
        state: data.state || null,
        icon: data.icon || null,
        message: storedMessage,
        is_voice: !!data.is_voice,
        done: isDone
    });

    if (!sessionActive) {
        // Silently drop broadcast logs for noise to avoid console clutter
        if (!isNoise) {
            console.log(`[PUSH IGNORED broadcast] no active session (agent: ${data.agent_name || 'unknown'})`);
        }
        return res.json({ status: 'stored_only' });
    }

    // 3. UI Broadcast: Guard the user interface from backend noise
    if (!isNoise) {
        broadcast(data);
    }

    if (data.done === true) {
        sessionActive = false;
        clearTurnWatchdog();
    }

    // 4. Voice playback: when a "send_state" push arrives with done=true
    // and it carries text, spawn play_voice.py with that text.
    const hasSpeakableReply = data.state === 'send_state' && data.done === true && typeof data.text === 'string' && data.text.trim();

    if (hasSpeakableReply) {
        broadcast({ type: 'state', state: 'speaking' });

        const voice = spawn('python3', [path.join(__dirname, 'core', 'play_voice.py'), data.text], {
            stdio: ['ignore', 'pipe', 'pipe']
        });

        voice.stdout.on('data', (chunk) => {
            console.log(`[VOICE OUT] ${chunk.toString()}`);
        });

        voice.stderr.on('data', (chunk) => {
            console.error(`[VOICE ERR] ${chunk.toString()}`);
        });

        voice.on('error', (err) => {
            console.error(`[SPAWN ERR] Failed to launch play_voice.py: ${err.message}`);
            broadcast({ type: 'state', state: 'listening' });
        });

        // Playback finished (or failed) — hand control back to the mic
        // so live.js knows it's safe to start recording the next turn.
        voice.on('close', () => {
            broadcast({ type: 'state', state: 'listening' });
        });
    } else if (data.done === true) {
        // Turn ended with nothing to speak (empty reply, or a
        // non-voice/non-send_state done) — still have to hand the mic
        // back, or the live page sits on "thinking" forever.
        broadcast({ type: 'state', state: 'listening' });
    }

    res.json({ status: 'ok' });
});

// ============================================================
// Routing & Execution
// ============================================================
app.post('/upload', upload.array('files', 10), (req, res) => {
    const files = req.files || [];
    if (!files.length) return res.status(400).json({ error: 'No files received' });

    const saved = files.map((f) => {
        const image = isImageFile(f.originalname, f.mimetype);
        return {
            original_name: f.originalname,
            saved_name: f.filename,
            path: f.path,
            url: `/data_files/${f.filename}`,
            mimetype: f.mimetype,
            size: f.size,
            type: image ? 'image' : 'file'
        };
    });

    res.json({ status: 'ok', files: saved });
});

app.get('/mcp/list', (req, res) => {
    try {
        const raw = fs.readFileSync(path.join(__dirname, 'mcp_servers.json'), 'utf8');
        res.json(JSON.parse(raw));
    } catch (err) {
        console.error('[MCP] failed to read mcp_servers.json:', err.message);
        res.status(500).json({ error: 'could not load mcp server list' });
    }
});

function resolveSavedAttachment(att) {
    if (!att || typeof att !== 'object') return null;
    const savedName = path.basename(att.saved_name || att.path || '');
    if (!savedName) return null;
    const resolved = path.join(DATA_FILES_DIR, savedName);
    if (!fs.existsSync(resolved)) return null;
    const type = att.type === 'image' ? 'image' : 'file';
    return {
        path: resolved,
        url: `/data_files/${savedName}`,
        type,
        original_name: att.original_name || savedName
    };
}

app.post('/agent/execute', (req, res) => {
    const text = (req.body && req.body.prompt) || '';
    const session_id = (req.body && req.body.session_id) || 'default';
    const mcp_server = (req.body && req.body.mcp_server) || null;
    const rawAttachments = Array.isArray(req.body && req.body.attachments) ? req.body.attachments : [];
    const attachments = rawAttachments.map(resolveSavedAttachment).filter(Boolean);
    const is_voice = (req.body && req.body.is_voice) === true;

    if (!text.trim() && !attachments.length) {
        return res.status(400).json({ error: 'Empty prompt' });
    }

    sessionActive = true;
    currentSessionId = session_id;

    const attachmentNote = attachments.length
        ? ' ' + attachments.map(a => `[${a.type}:${a.original_name}]`).join(' ')
        : '';
    saveMessage({
        session_id,
        role: 'user',
        kind: 'user_message',
        message: (mcp_server ? `@${mcp_server} ${text}` : text) + attachmentNote,
        is_voice,
        // Only the fields addUserBubble() actually needs to render a
        // chip/img — keep the local upload `path` out of the DB blob.
        attachments: attachments.map(a => ({ url: a.url, type: a.type, original_name: a.original_name }))
    });

    let script, args;

    if (attachments.length) {
        script = 'files_manager.py';
        args = [JSON.stringify(attachments), session_id, text];
    } else if (mcp_server) {
        script = 'mcp_call.py';
        args = [mcp_server, text, session_id];
    } else {
        script = 'hina_brain.py';
        args = [text];
    }

    const py = spawn('python3', [path.join(__dirname,"core",script), ...args], {
        detached: true,
        stdio: ['ignore', 'pipe', 'pipe']
    });

    py.stdout.on('data', (chunk) => {
        console.log(`[PY OUT] ${chunk.toString()}`);
    });

    py.stderr.on('data', (chunk) => {
        console.error(`[PY ERR] ${chunk.toString()}`);
    });

    py.on('error', (err) => {
        console.error(`[SPAWN ERR] Failed to launch ${script}: ${err.message}`);
    });

    py.unref();

    res.status(202).json({ status: 'dispatched', script, mcp_server, attachments: attachments.map(a => ({ url: a.url, type: a.type, original_name: a.original_name })) });
});

// GET /history?session_id=...              -> full history (every row,
//     every kind) for the chat UI to reconstruct turns + collapsed traces.
// GET /history?session_id=...&mode=clean    -> only user_message and
//     final_reply rows, in order — no trace_step/noise clutter. This is
//     the feed to use for memory / context-injection into the model,
//     since trace steps and background noise are not "content", just
//     telemetry, and would waste tokens / pollute recall.
app.get('/history', async (req, res) => {
    const session_id = req.query.session_id || 'default';
    const mode = req.query.mode === 'clean' ? 'clean' : 'full';
    // No forced ceiling of 10 anymore — history is retained in full,
    // so the default page size is generous and callers can still
    // request more explicitly.
    const limit = Math.min(parseInt(req.query.limit) || 2000, 5000);

    try {
        const kindFilter = mode === 'clean'
            ? `AND kind IN ('user_message','final_reply')`
            : '';

        const [rows] = await db.query(
            `SELECT role, kind, agent_name, state, icon, message, is_voice, done, attachments, created_at
             FROM conversation_history
             WHERE session_id = ? ${kindFilter}
             ORDER BY created_at ASC, id ASC
             LIMIT ?`,
            [session_id, limit]
        );
        // mysql2 returns JSON columns already parsed as JS values, but
        // guard for drivers/config that hand back a raw string instead.
        const history = rows.map(row => {
            let attachments = row.attachments;
            if (typeof attachments === 'string') {
                try { attachments = JSON.parse(attachments); } catch (_) { attachments = null; }
            }
            return { ...row, attachments };
        });
        res.json({ session_id, mode, history });
    } catch (err) {
        console.error('[DB ERR] history fetch failed:', err.message);
        res.status(500).json({ error: 'history fetch failed' });
    }
});

app.get('/live', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'live.html'));
});

process.on('SIGINT', () => { stopSttServer(); process.exit(0); });
process.on('SIGTERM', () => { stopSttServer(); process.exit(0); });

app.use((req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

initDb()
    .then(() => {
        server.listen(PORT, '127.0.0.1', () => {
            console.log(`=======================================================`);
            console.log(` HINA CORE running on http://127.0.0.1:${PORT}`);
            console.log(` WebSocket telemetry on ws://127.0.0.1:${PORT}/ws`);
            console.log(` History: GET /history?session_id=default`);
            console.log(`=======================================================`);
        });
    })
    .catch((err) => {
        console.error('[DB ERR] failed to connect to MariaDB:', err.message);
        process.exit(1);
    });

""",
    user_query="summarize the code in short",
    model="qwen2.5:0.5b"
)
print(full_text)
print("---------------------------------------")