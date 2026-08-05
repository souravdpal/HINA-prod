// routes/hinaFiles.js
//
// Router for HINA-generated files (code files the agent writes to
// Hina_db/ for the user to view/download from chat) — separate
// from the chat-upload attachments handled in server.js.
//
// Mount with:
//   const hinaFilesRouter = require('./routes/hinaFiles');
//   app.use('/download/hina/files', hinaFilesRouter);
//
// Exposes:
//   GET /download/hina/files/:filename        -> stream file inline (used by the "View" button)
//   GET /download/hina/files/:filename/save   -> force Save-As (used by the "Download" button)

const express = require('express');
const path = require('path');
const fs = require('fs');

const router = express.Router();

const HINA_DB_DIR = path.join(__dirname, '..', 'Hina_db');
fs.mkdirSync(HINA_DB_DIR, { recursive: true });

// basename() strips any directory component so ../../ style
// traversal in the URL param can't escape Hina_db.
function safeHinaFilePath(filename) {
    const safeName = path.basename(String(filename || ''));
    if (!safeName || safeName === '.' || safeName === '..') return null;
    const resolved = path.join(HINA_DB_DIR, safeName);
    if (!resolved.startsWith(HINA_DB_DIR + path.sep)) return null;
    return resolved;
}

// Used by the frontend's "View" button — streams the raw file
// inline (no forced Save-As) so it can be fetched as text and shown
// in the in-app code canvas.
router.get('/:filename', (req, res) => {
    const resolved = safeHinaFilePath(req.params.filename);
    if (!resolved || !fs.existsSync(resolved)) {
        return res.status(404).json({ error: 'file not found' });
    }
    res.sendFile(resolved);
});

// Used by the frontend's "Download" button — same file, but forces
// a Save-As dialog via Content-Disposition: attachment.
router.get('/:filename/save', (req, res) => {
    const resolved = safeHinaFilePath(req.params.filename);
    if (!resolved || !fs.existsSync(resolved)) {
        return res.status(404).json({ error: 'file not found' });
    }
    res.download(resolved);
});

module.exports = router;
module.exports.HINA_DB_DIR = HINA_DB_DIR;