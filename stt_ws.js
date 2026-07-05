const express = require('express');
const WebSocket = require('ws');
const path = require('path');
const fs = require('fs');
const os = require('os');

const app = express();
const PORT = process.env.PORT || 3000;
const RESULT_FILE = path.join(__dirname, 'speech_result.json');

// How often the server pings each browser to check it's still alive.
const HEARTBEAT_INTERVAL_MS = 15000;

app.use(express.static(__dirname));

// Ngrok shows an interstitial warning page for plain HTTP fetches unless
// this header is present. Harmless on direct/LAN access.
app.use((req, res, next) => {
    res.setHeader('ngrok-skip-browser-warning', 'true');
    next();
});

app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'stt_frontend.html'));
});

app.get('/health', (req, res) => {
    res.json({
        ok: true,
        browserConnected: !!(activeBrowser && activeBrowser.readyState === WebSocket.OPEN),
    });
});

const server = app.listen(PORT, '0.0.0.0', () => {
    const nets = os.networkInterfaces();
    console.log('🚀 HINA Server Running');
    console.log(`Desktop → http://localhost:${PORT}`);
    for (const name of Object.keys(nets)) {
        for (const net of nets[name]) {
            if (net.family === 'IPv4' && !net.internal) {
                console.log(`Mobile  → http://${net.address}:${PORT}`);
            }
        }
    }
    console.log('For ngrok/HTTPS access, the frontend auto-detects wss:// — no config needed.');
});

const wss = new WebSocket.Server({ server });
let activeBrowser = null;

function heartbeat() {
    this.isAlive = true;
}

wss.on('connection', (ws) => {
    ws.isAlive = true;
    ws.on('pong', heartbeat);

    ws.on('message', (message) => {
        let data;
        try {
            data = JSON.parse(message);
        } catch (e) {
            console.warn('⚠️  Ignoring malformed message:', message.toString().slice(0, 100));
            return;
        }

        switch (data.type) {
            case 'register': {
                // If a different browser was previously registered, close it
                // cleanly so we never send commands to a stale socket.
                if (activeBrowser && activeBrowser !== ws && activeBrowser.readyState === WebSocket.OPEN) {
                    activeBrowser.close(1000, 'replaced-by-new-registration');
                }
                activeBrowser = ws;
                ws.send(JSON.stringify({ type: 'registered' }));
                console.log('✅ Browser registered');
                break;
            }
            case 'text_input': {
                fs.writeFileSync(RESULT_FILE, JSON.stringify({ text: data.text }));
                console.log(`📝 Received: ${data.text}`);
                ws.send(JSON.stringify({ type: 'ack' }));
                break;
            }
            case 'client_ping': {
                ws.send(JSON.stringify({ type: 'client_pong' }));
                break;
            }
            default:
                console.warn('⚠️  Unknown message type:', data.type);
        }
    });

    ws.on('close', () => {
        if (ws === activeBrowser) {
            activeBrowser = null;
            console.log('❌ Browser disconnected');
        }
    });

    ws.on('error', (err) => {
        console.warn('⚠️  Socket error:', err.message);
    });
});

// Detect dead connections (common over ngrok/mobile, where the TCP socket
// can die without a clean close event ever firing) and terminate them so
// a reconnect can happen instead of silently hanging forever.
const heartbeatTimer = setInterval(() => {
    wss.clients.forEach((ws) => {
        if (ws.isAlive === false) {
            if (ws === activeBrowser) activeBrowser = null;
            return ws.terminate();
        }
        ws.isAlive = false;
        ws.ping();
    });
}, HEARTBEAT_INTERVAL_MS);

wss.on('close', () => clearInterval(heartbeatTimer));

app.get('/listen', (req, res) => {
    if (!activeBrowser || activeBrowser.readyState !== WebSocket.OPEN) {
        return res.status(400).json({ error: 'Browser not connected/registered' });
    }

    if (fs.existsSync(RESULT_FILE)) fs.unlinkSync(RESULT_FILE);

    activeBrowser.send(JSON.stringify({ type: 'hina_ready' }));
    res.json({ status: 'ok' });
});