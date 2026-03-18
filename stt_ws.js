// stt_ws.js
const express = require('express');
const WebSocket = require('ws');
const path = require('path');
const fs = require('fs');
const os = require('os');

const app = express();
const PORT = 3000;
const RESULT_FILE = path.join(__dirname, 'speech_result.json');

app.use(express.static(__dirname));

app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'stt_frontend.html'));
});

function getLocalIP() {
    const interfaces = os.networkInterfaces();
    for (const name of Object.keys(interfaces)) {
        for (const iface of interfaces[name]) {
            if (iface.family === 'IPv4' && !iface.internal) {
                return iface.address;
            }
        }
    }
    return 'localhost';
}

const localIP = getLocalIP();

const server = app.listen(PORT, '0.0.0.0', () => {
    console.log(`\n🚀 HINA Server Running`);
    console.log(`Desktop → http://localhost:${PORT}`);
    console.log(`Mobile  → http://${localIP}:${PORT}`);
    console.log(`\n⚠️  MOBILE USERS: If mic fails, go to chrome://flags/#unsafely-treat-insecure-origin-as-secure`);
    console.log(`Add 'http://${localIP}:${PORT}' to the list and enable it.\n`);
});

const wss = new WebSocket.Server({ server });

let chromeClient = null;

wss.on('connection', (ws) => {
    console.log('📱 New Device Connected');
    
    ws.on('message', (data) => {
        try {
            const msg = JSON.parse(data);
            if (msg.type === 'register' && msg.client === 'chrome') {
                chromeClient = ws;
                console.log('✅ Browser Registered as Controller');
            }
            if (msg.type === 'finalTranscript' && msg.text) {
                const text = msg.text.trim();
                console.log(`📝 Received: "${text}"`);
                fs.writeFileSync(RESULT_FILE, JSON.stringify({ text, timestamp: Date.now() }));
            }
        } catch (e) {
            console.error("Error parsing message:", e);
        }
    });

    ws.on('close', () => {
        if (ws === chromeClient) {
            console.log('❌ Browser Disconnected');
            chromeClient = null;
        }
    });
});

app.get('/listen', (req, res) => {
    if (!chromeClient) {
        return res.status(400).json({ error: "Browser not connected" });
    }
    if (fs.existsSync(RESULT_FILE)) fs.unlinkSync(RESULT_FILE);
    
    // Send command to the browser
    chromeClient.send(JSON.stringify({ type: 'startListening' }));
    res.json({ status: "Listening command sent to browser" });
});