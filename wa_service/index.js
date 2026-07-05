const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } = require('@whiskeysockets/baileys');
const express = require('express');
const qrcode = require('qrcode-terminal');

const app = express();
app.use(express.json());
let sock;

async function startSock() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_info'); // persists session
    sock = makeWASocket({ auth: state, printQRInTerminal: false });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, qr, lastDisconnect } = update;
        if (qr) qrcode.generate(qr, { small: true }); // scan once, then never again
        if (connection === 'close') {
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
            if (shouldReconnect) startSock();
        }
    });
}
startSock();

app.post('/send', async (req, res) => {
    const { number, message } = req.body; // number in format 91XXXXXXXXXX
    try {
        await sock.sendMessage(`${number}@s.whatsapp.net`, { text: message });
        res.json({ ok: true });
    } catch (e) {
        res.status(500).json({ ok: false, error: e.message });
    }
});

app.listen(3001, () => console.log('WA service on :3001'));
