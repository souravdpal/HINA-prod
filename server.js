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

const app = express();
const PORT = 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

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

app.use('/data_files', express.static(DATA_FILES_DIR));

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
            role ENUM('user','agent') NOT NULL,
            agent_name VARCHAR(100) DEFAULT NULL,
            state VARCHAR(100) DEFAULT NULL,
            icon VARCHAR(100) DEFAULT NULL,
            message TEXT NOT NULL,
            is_voice BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_session (session_id),
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    `);

    console.log('[DB] connected + conversation_history ready');
}

const HISTORY_LIMIT = 10;

async function saveMessage({ session_id, role, agent_name = null, state = null, icon = null, message, is_voice = false }) {
    if (!db || !message) return;
    try {
        await db.query(
            `INSERT INTO conversation_history (session_id, role, agent_name, state, icon, message, is_voice)
             VALUES (?, ?, ?, ?, ?, ?, ?)`,
            [session_id, role, agent_name, state, icon, message, is_voice]
        );
        await trimSessionHistory(session_id);
    } catch (err) {
        console.error('[DB ERR] insert failed:', err.message);
    }
}

async function trimSessionHistory(session_id) {
    try {
        await db.query(
            `DELETE FROM conversation_history
             WHERE session_id = ?
               AND id NOT IN (
                   SELECT id FROM (
                       SELECT id FROM conversation_history
                       WHERE session_id = ?
                       ORDER BY created_at DESC, id DESC
                       LIMIT ?
                   ) keep
               )`,
            [session_id, session_id, HISTORY_LIMIT]
        );
    } catch (err) {
        console.error('[DB ERR] trim failed:', err.message);
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

app.post('/internal/push', (req, res) => {
    const data = (req.body && typeof req.body === 'object') ? req.body : {};

    // 1. HYGIENE PROTOCOL: Define strict garbage filters
    const isSystemArchitecture = data.text && data.text.includes('HINA CORE ARCHITECTURE');
    const isBackgroundAgent = data.agent_name === 'AI_CALL' || data.agent_name === 'system' || data.agent_name === 'duck_duck';
    const isRawToolLog = data.text && (data.text.startsWith('CallToolResult') || data.text.includes('[PY ERR]') || data.text.includes('HTTP Request:'));

    // 2. Strict Memory Insertion: Only clean, intentional output
    if (data.text && !isSystemArchitecture && !isBackgroundAgent && !isRawToolLog) {
        saveMessage({
            session_id: currentSessionId || 'default',
            role: 'agent',
            agent_name: data.agent_name || null,
            state: data.state || null,
            icon: data.icon || null,
            message: data.text,
            is_voice: !!data.is_voice
        });
    }

    if (!sessionActive) {
        // Silently drop broadcast logs for noise to avoid console clutter
        if (!isSystemArchitecture && !isBackgroundAgent && !isRawToolLog) {
            console.log(`[PUSH IGNORED broadcast] no active session (agent: ${data.agent_name || 'unknown'})`);
        }
        return res.json({ status: 'stored_only' });
    }

    // 3. UI Broadcast: Guard the user interface from backend noise
    if (!isSystemArchitecture && !isBackgroundAgent && !isRawToolLog) {
        broadcast(data);
    }

    if (data.done === true) {
        sessionActive = false;
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
        message: (mcp_server ? `@${mcp_server} ${text}` : text) + attachmentNote
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

app.get('/history', async (req, res) => {
    const session_id = req.query.session_id || 'default';
    const limit = Math.min(parseInt(req.query.limit) || 100, 500);

    try {
        const [rows] = await db.query(
            `SELECT role, agent_name, state, icon, message, is_voice, created_at
             FROM conversation_history
             WHERE session_id = ?
             ORDER BY created_at ASC
             LIMIT ?`,
            [session_id, limit]
        );
        res.json({ session_id, history: rows });
    } catch (err) {
        console.error('[DB ERR] history fetch failed:', err.message);
        res.status(500).json({ error: 'history fetch failed' });
    }
});

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