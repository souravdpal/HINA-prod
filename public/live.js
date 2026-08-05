// live.js
//
// ============================================================
// HINA /live — full-page, hands-free voice mode (v2 redesign).
//
// Audio capture lives in the BROWSER (MediaRecorder), not in Python —
// this file records one utterance at a time (simple energy-based VAD
// to detect "user stopped talking"), POSTs the clip to
// /live/transcribe, and renders whatever state/content the server
// pushes over /ws.
//
// v2 adds:
//   - a real reactive waveform (live mic frequency data while
//     listening; a synthetic "talking" waveform while speaking)
//   - a single big scrollable stream that renders transcript lines
//     AND any rich content the backend sends (ui_type/ui_data:
//     files, image galleries, search/data cards, links) — the same
//     structured-payload shape the main chat understands, so voice
//     mode never has to fall back to raw text for that content.
//
// Turn loop:
//   /live/start          -> server loads the model once, replies ready
//   record (VAD-gated)   -> stop on silence -> POST /live/transcribe
//   server: transcribe -> broadcast transcript+"thinking" -> hina_brain
//   reply streams in over /ws -> "speaking" -> TTS plays server-side
//   -> "listening" -> record again, automatically
//   /live/stop            -> server unloads the model, frees memory
// ============================================================

(function () {
    const COLORS = {
        idle:      '110,113,122',
        loading:   '124,138,255',
        listening: '45,209,230',
        thinking:  '124,138,255',
        speaking:  '214,110,235',
        error:     '235,90,100'
    };

    // Same semantic palette the main chat uses, for any ui_data
    // payload that arrives with a color_name instead of raw rgb.
    const COLOR_PALETTE = {
        idle: '110,113,122', think: '124,138,255', reason: '168,140,255',
        tool: '59,157,246', search: '45,190,190', success: '52,199,140',
        warn: '235,158,52', error: '235,90,100', voice: '45,209,230',
        creative: '214,110,235'
    };

    function getSessionId() {
        let id = localStorage.getItem('hina_session_id');
        if (!id) {
            id = 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
            localStorage.setItem('hina_session_id', id);
        }
        return id;
    }

    // NOTE: el/wctx are populated inside init() (after DOMContentLoaded).
    // Nothing at module top-level touches the DOM anymore — a missing or
    // renamed element id must never be able to throw before the page boots.
    const el = {};
    let wctx = null;

    let state = 'idle';       // idle | loading | listening | thinking | speaking | error
    let muted = false;
    let ws = null, wsReconnectTimer = null;
    let hasConnectedBefore = false; // distinguishes the first connect from a reconnect
    let transcribeInFlight = false; // hard guard against ever submitting two overlapping turns
    let lastUserTranscript = '', lastUserTranscriptAt = 0; // dedupe a duplicated broadcast
    let orbTime = 0;
    let currentAgentLineEl = null;
    // Per your instruction: the client must NEVER guess that a turn is
    // over and reopen the mic on its own — not even after a timeout.
    // run_hina_voice() plays audio out of this machine's own speakers,
    // right next to this machine's own mic, so any locally-guessed
    // "listening" state risks the mic hearing (and transcribing) HINA's
    // own voice. The ONLY things allowed to change state now are: a
    // real {type:"state", ...} push from the server, or the user
    // manually tapping the mic. No timer, no auto-error, no
    // auto-recover. If the backend genuinely hangs, the UI just stays
    // on "thinking" / "speaking" until the server sends something —
    // that's a backend issue to fix, not something the client papers
    // over by guessing.
    let clientWatchdog = null; // unused now; kept so any stray caller is a harmless no-op
    function armClientWatchdog(_forState) { /* intentionally does nothing */ }
    function clearClientWatchdog() { /* intentionally does nothing */ }

    // ---- browser-side recording + VAD ----
    let micStream = null, audioCtx = null, analyser = null, meterRAF = null;
    let recorder = null, recordedChunks = [];
    let recording = false;
    let speechStarted = false;
    let silenceTimer = null;
    // Separate from silenceTimer on purpose. The old code reused
    // `silenceTimer` for BOTH the "stop after 900ms of quiet" logic AND
    // the "hard cap so a long ramble can't hang forever" 15s timer —
    // every animation frame that saw isSpeech===true called
    // clearTimeout(silenceTimer) + a fresh setTimeout(...SILENCE_MS),
    // which silently clobbered the 15s cap too. So if the mic ever saw
    // *continuous* energy above the threshold — someone talking a long
    // time, or (worse) HINA's own music leaking into the mic — the cap
    // kept getting pushed back and effectively never fired: recording
    // never stopped, the turn never got sent, "she just keeps
    // listening". maxRecordingTimer is now armed once per recording
    // and never touched by the per-frame VAD logic, so it always fires.
    let maxRecordingTimer = null;
    const SILENCE_MS = 900;        // gap of quiet before we treat the turn as finished
    const MIN_SPEECH_MS = 300;     // ignore blips shorter than this
    const MAX_RECORDING_MS = 15000; // absolute cap, independent of VAD state
    let speechStartedAt = 0;
    let energyFloor = 0.01;        // adaptive-ish baseline, refined as we listen

    // Set true while a music_player/music_control "play"/"resume" event
    // is active, cleared on stop/pause. HINA's own YouTube audio comes
    // out of the same device speakers the mic is listening on, so
    // without this the mic can hear its own music, treat it as speech,
    // and either transcribe song lyrics as a "user turn" or (combined
    // with the timer bug above) just keep the mic open indefinitely.
    // echoCancellation in getUserMedia below does most of the real
    // work; this is a cheap second line of defense that raises how
    // much louder something has to be than the room floor before the
    // VAD treats it as a deliberate utterance.
    let musicPlaying = false;

    // ================================================================
    // Reactive waveform — the visual heart of the redesign.
    // While listening: real mic frequency-bin data drives bar heights.
    // While speaking/thinking/idle/error: a smooth synthetic pattern,
    // since TTS audio plays server-side and we have no direct signal
    // to analyse — but it's still an animated, "talking" cadence
    // rather than a static shape.
    // ================================================================
    const BAR_COUNT = 48;
    const barHeights = new Array(BAR_COUNT).fill(0.06);
    const barTargets = new Array(BAR_COUNT).fill(0.06);

    function sizeWaveform() {
        if (!el.waveCanvas || !wctx) return;
        const rect = el.waveCanvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        el.waveCanvas.width = rect.width * dpr;
        el.waveCanvas.height = rect.height * dpr;
        wctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function roundRect(c, x, y, w, h, r) {
        const rad = Math.min(r, w / 2, h / 2);
        c.beginPath();
        c.moveTo(x + rad, y);
        c.arcTo(x + w, y, x + w, y + h, rad);
        c.arcTo(x + w, y + h, x, y + h, rad);
        c.arcTo(x, y + h, x, y, rad);
        c.arcTo(x, y, x + w, y, rad);
        c.closePath();
    }

    function computeBarTargets() {
        if (state === 'listening' && analyser) {
            const freqData = new Uint8Array(analyser.frequencyBinCount);
            analyser.getByteFrequencyData(freqData);
            const usable = Math.floor(freqData.length * 0.65); // skip mostly-empty high end
            const bucket = Math.max(1, Math.floor(usable / BAR_COUNT));
            for (let i = 0; i < BAR_COUNT; i++) {
                let sum = 0;
                const start = i * bucket;
                for (let j = 0; j < bucket; j++) sum += freqData[start + j] || 0;
                const avg = (sum / bucket) / 255;
                barTargets[i] = Math.max(0.05, Math.min(1, avg * 1.9));
            }
        } else if (state === 'speaking') {
            for (let i = 0; i < BAR_COUNT; i++) {
                const phase = i * 0.33;
                const v = 0.22 + Math.abs(Math.sin(orbTime * 3.4 + phase) * Math.cos(orbTime * 1.5 - phase * 0.6)) * 0.7;
                barTargets[i] = v;
            }
        } else if (state === 'thinking') {
            for (let i = 0; i < BAR_COUNT; i++) {
                barTargets[i] = 0.14 + Math.abs(Math.sin(orbTime * 1.3 + i * 0.45)) * 0.22;
            }
        } else if (state === 'loading') {
            for (let i = 0; i < BAR_COUNT; i++) {
                barTargets[i] = 0.1 + Math.abs(Math.sin(orbTime * 2.2 + i * 0.6)) * 0.12;
            }
        } else if (state === 'error') {
            for (let i = 0; i < BAR_COUNT; i++) barTargets[i] = 0.08 + Math.random() * 0.22;
        } else { // idle
            for (let i = 0; i < BAR_COUNT; i++) barTargets[i] = 0.07 + Math.sin(orbTime * 0.6 + i * 0.22) * 0.025;
        }
    }

    function drawWaveform() {
        if (!el.waveCanvas || !wctx) return; // nothing to draw on this page
        computeBarTargets();
        orbTime += state === 'thinking' ? 0.045 : (state === 'speaking' ? 0.05 : (state === 'loading' ? 0.06 : 0.02));

        const w = el.waveCanvas.clientWidth, h = el.waveCanvas.clientHeight;
        wctx.clearRect(0, 0, w, h);
        if (!w || !h) { requestAnimationFrame(drawWaveform); return; }

        const gap = 4;
        const barW = Math.max(2, (w - (BAR_COUNT - 1) * gap) / BAR_COUNT);
        const rgb = COLORS[state] || COLORS.idle;
        const cy = h / 2;

        for (let i = 0; i < BAR_COUNT; i++) {
            barHeights[i] += (barTargets[i] - barHeights[i]) * 0.22;
            const bh = Math.max(3, barHeights[i] * h * 0.92);
            const x = i * (barW + gap);
            const y = cy - bh / 2;
            wctx.fillStyle = `rgba(${rgb}, ${0.5 + barHeights[i] * 0.45})`;
            roundRect(wctx, x, y, barW, bh, barW / 2);
            wctx.fill();
        }

        requestAnimationFrame(drawWaveform);
    }

    // ---------------- state ----------------
    function setState(next) {
        state = next;
        const rgb = COLORS[state] || COLORS.idle;
        if (el.app) el.app.style.setProperty('--live-rgb', rgb);
        if (el.dot) el.dot.classList.toggle('live', state !== 'idle');
        if (el.micBtn) el.micBtn.classList.remove('listening', 'thinking', 'speaking', 'error', 'loading');
        if (el.muteBtn) el.muteBtn.classList.toggle('muted', muted);

        const icon = el.micBtn ? el.micBtn.querySelector('i') : null;
        switch (state) {
            case 'idle':
                if (el.statusText) el.statusText.textContent = muted ? 'Muted' : 'Idle';
                if (el.caption) el.caption.textContent = muted ? 'Muted' : 'Tap the mic to start talking';
                if (icon) icon.className = 'fa-solid fa-microphone';
                break;
            case 'loading':
                if (el.micBtn) el.micBtn.classList.add('loading');
                if (el.statusText) el.statusText.textContent = 'Waking up…';
                if (el.caption) el.caption.textContent = 'Loading voice model — one moment';
                if (icon) icon.className = 'fa-solid fa-circle-notch';
                break;
            case 'listening':
                if (el.micBtn) el.micBtn.classList.add('listening');
                if (el.statusText) el.statusText.textContent = 'Listening…';
                if (el.caption) el.caption.textContent = 'Listening — go ahead';
                if (icon) icon.className = 'fa-solid fa-microphone';
                break;
            case 'thinking':
                if (el.micBtn) el.micBtn.classList.add('thinking');
                if (el.statusText) el.statusText.textContent = 'Thinking…';
                if (el.caption) el.caption.textContent = 'HINA is thinking';
                if (icon) icon.className = 'fa-solid fa-circle-notch';
                break;
            case 'speaking':
                if (el.micBtn) el.micBtn.classList.add('speaking');
                if (el.statusText) el.statusText.textContent = 'Speaking…';
                if (el.caption) el.caption.textContent = 'HINA is replying';
                if (icon) icon.className = 'fa-solid fa-volume-high';
                break;
            case 'error':
                if (el.micBtn) el.micBtn.classList.add('error');
                if (el.statusText) el.statusText.textContent = 'Error';
                if (icon) icon.className = 'fa-solid fa-triangle-exclamation';
                break;
        }

        // recording only happens while we're actually in "listening"
        if (state === 'listening' && !muted) { startRecording(); clearClientWatchdog(); }
        else stopRecordingIfActive();

        if (state === 'thinking' || state === 'speaking') armClientWatchdog(state);
    }

    // ================================================================
    // LIVE STREAM — shared scrollable panel for transcript lines and
    // any rich content the backend pushes in.
    // ================================================================
    function hideEmptyState() {
        if (el.streamEmpty && el.streamEmpty.parentNode) el.streamEmpty.remove();
    }

    function isNearBottom() {
        if (!el.stream) return true;
        return el.stream.scrollHeight - el.stream.scrollTop - el.stream.clientHeight < 120;
    }

    function scrollStreamToBottom(force) {
        if (!el.stream) return;
        if (force || isNearBottom()) el.stream.scrollTop = el.stream.scrollHeight;
    }

    function escapeHtml(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function addLine(role, text) {
        if (!el.stream) return null;
        hideEmptyState();
        const line = document.createElement('div');
        line.className = `live-line ${role}`;
        line.textContent = text;
        el.stream.appendChild(line);
        scrollStreamToBottom();
        return line;
    }

    function addBlock(labelHtml, bodyHtml) {
        if (!el.stream) return null;
        hideEmptyState();
        const block = document.createElement('div');
        block.className = 'live-block';
        block.innerHTML = `${labelHtml ? `<div class="live-block-tag">${labelHtml}</div>` : ''}${bodyHtml}`;
        el.stream.appendChild(block);
        scrollStreamToBottom();
        return block;
    }

    // ---------------- link handling ----------------
    function stripTrailingPunct(url) { return url.replace(/[).,;:!?\]}'"]+$/, ''); }

    function sanitizeUrl(raw) {
        if (typeof raw !== 'string') return null;
        const trimmed = stripTrailingPunct(raw.trim());
        try {
            const u = new URL(trimmed, window.location.origin);
            if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
            return u.href;
        } catch (e) { return null; }
    }

    function hostnameOf(url) {
        try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return url; }
    }
    function faviconUrl(url) {
        try { return `https://www.google.com/s2/favicons?sz=64&domain=${new URL(url).hostname}`; } catch (e) { return ''; }
    }

    function buildInlineLinkChip(rawUrl, labelOverride) {
        const safe = sanitizeUrl(rawUrl);
        if (!safe) return escapeHtml(rawUrl);
        const host = labelOverride || hostnameOf(safe);
        return `<a class="live-link-chip" href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(safe)}">
            <img src="${faviconUrl(safe)}" alt="" loading="lazy" onerror="this.style.display='none'">
            <span>${escapeHtml(host)}</span>
            <i class="fa-solid fa-arrow-up-right-from-square"></i></a>`;
    }

    const URL_RE = /\bhttps?:\/\/[^\s<>"'`)\]]+/gi;
    function linkifyText(str) {
        if (typeof str !== 'string') return '';
        return escapeHtml(str).replace(/\bhttps?:\/\/[^\s<>&]+/gi, (m) => {
            const clean = stripTrailingPunct(m);
            const trailing = m.slice(clean.length);
            return buildInlineLinkChip(clean) + trailing;
        });
    }

    // ---------------- HINA-generated file cards ----------------
    const HINA_FILE_LINK_RE = /\/download\/hina\/files\/([^\/?#\s"'<>]+)\/?$/i;
    const FILE_EXT_ICON = {
        js: 'fa-js', jsx: 'fa-react', ts: 'fa-js', tsx: 'fa-react',
        py: 'fa-python', html: 'fa-html5', htm: 'fa-html5',
        css: 'fa-css3-alt', scss: 'fa-css3-alt', java: 'fa-java',
        php: 'fa-php', sh: 'fa-terminal', bash: 'fa-terminal',
        md: 'fa-markdown', json: 'fa-code'
    };
    function fileNameOf(pathOrUrl) {
        try {
            const clean = pathOrUrl.split(/[?#]/)[0];
            const parts = clean.split(/[\\/]/);
            return decodeURIComponent(parts[parts.length - 1] || pathOrUrl);
        } catch (e) { return pathOrUrl; }
    }
    function buildFileCard(rawUrl, displayName) {
        const safe = sanitizeUrl(rawUrl);
        if (!safe) return null;
        const name = displayName || fileNameOf(safe);
        const ext = (name.split('.').pop() || '').toLowerCase();
        const iconClass = FILE_EXT_ICON[ext] ? `fa-brands ${FILE_EXT_ICON[ext]}` : 'fa-solid fa-file-lines';
        return `<div class="live-card">
            <div class="live-file-card">
                <div class="live-file-icon"><i class="${iconClass.includes('fa-brands') ? iconClass : iconClass}"></i></div>
                <div class="live-file-info">
                    <div class="live-file-name">${escapeHtml(name)}</div>
                    <div class="live-file-sub">${escapeHtml(ext ? ext.toUpperCase() + ' file' : 'File')} · generated by HINA</div>
                </div>
                <div class="live-file-actions">
                    <a class="live-file-btn" href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer" title="View"><i class="fa-solid fa-eye"></i></a>
                    <a class="live-file-btn" href="${escapeHtml(safe)}" download title="Download"><i class="fa-solid fa-download"></i></a>
                </div>
            </div>
        </div>`;
    }

    // ---------------- image gallery + lightbox ----------------
    let lightboxEl = null;
    function ensureLightbox() {
        if (lightboxEl) return lightboxEl;
        lightboxEl = document.createElement('div');
        lightboxEl.className = 'live-lightbox hidden';
        lightboxEl.innerHTML = `<button type="button" class="live-lightbox-close"><i class="fa-solid fa-xmark"></i></button><img alt="">`;
        lightboxEl.addEventListener('click', (e) => {
            if (e.target === lightboxEl || e.target.closest('.live-lightbox-close')) lightboxEl.classList.add('hidden');
        });
        document.body.appendChild(lightboxEl);
        return lightboxEl;
    }
    function openLightbox(src) {
        const box = ensureLightbox();
        box.querySelector('img').src = src;
        box.classList.remove('hidden');
    }

    function buildImageGallery(images) {
        const safeImages = images.map(it => ({ url: sanitizeUrl(it.url), title: it.title || '' })).filter(it => it.url);
        if (!safeImages.length) return '';
        const thumbs = safeImages.map(it => `
            <button type="button" class="live-gallery-thumb" data-full="${escapeHtml(it.url)}" title="${escapeHtml(it.title || 'Open image')}">
                <img src="${escapeHtml(it.url)}" alt="" loading="lazy">
                <span class="live-gallery-thumb-overlay"><i class="fa-solid fa-up-right-and-down-left-from-center"></i></span>
            </button>`).join('');
        return `<div class="live-card">
            <div class="live-gallery-heading"><i class="fa-solid fa-images"></i> Images <span class="count">${safeImages.length}</span></div>
            <div class="live-gallery-grid">${thumbs}</div>
        </div>`;
    }

    function wireGalleries(root) {
        root.querySelectorAll('.live-gallery-thumb').forEach(btn => {
            btn.addEventListener('click', () => openLightbox(btn.dataset.full));
        });
    }

    // ---------------- generic key/value data card ----------------
    function isPlainObject(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }

    function buildGenericValue(value, depth) {
        if (value === null || value === undefined) return '<span style="opacity:.4">—</span>';
        if (Array.isArray(value)) {
            if (!value.length) return '<span style="opacity:.4">—</span>';
            if (depth >= 3) return `<span>${escapeHtml(JSON.stringify(value))}</span>`;
            const allPrimitive = value.every(v => !v || typeof v !== 'object');
            if (allPrimitive) return `<div class="live-chip-row">${value.map(v => `<span class="live-chip">${escapeHtml(String(v))}</span>`).join('')}</div>`;
            return value.map(item => buildGenericValue(item, depth + 1)).join('<hr style="border-color:rgba(255,255,255,.08);margin:8px 0;">');
        }
        if (isPlainObject(value)) {
            if (depth >= 3) return `<span>${escapeHtml(JSON.stringify(value))}</span>`;
            const rows = Object.entries(value).map(([k, v]) => `
                <div class="live-kv-row">
                    <div class="live-kv-key">${escapeHtml(String(k).replace(/_/g, ' '))}</div>
                    <div class="live-kv-value">${buildGenericValue(v, depth + 1)}</div>
                </div>`).join('');
            return `<div class="live-kv-grid">${rows}</div>`;
        }
        if (typeof value === 'string' && /^https?:\/\/\S+$/i.test(value.trim())) return buildInlineLinkChip(value);
        if (typeof value === 'string') return linkifyText(value);
        return escapeHtml(String(value));
    }

    function buildGenericCard(data) {
        return `<div class="live-card">
            <div class="live-card-head"><i class="fa-solid fa-shapes"></i> Data</div>
            <div class="live-card-body">${buildGenericValue(data, 0)}</div>
        </div>`;
    }

    // ---------------- search-result card ----------------
    function buildSearchCard(data) {
        const organic = Array.isArray(data.organic_results) ? data.organic_results
                       : Array.isArray(data.ai_links) ? data.ai_links : [];
        const images = Array.isArray(data.image_links) ? data.image_links.map(u => ({ url: u })) : [];
        let body = '';
        if (organic.length) {
            body += organic.slice(0, 8).map(r => {
                const url = sanitizeUrl(r.url || r.link || r.href);
                const title = r.title || (url ? hostnameOf(url) : 'Result');
                const snippet = r.snippet || r.description || '';
                return `<div style="margin-bottom:10px;">
                    ${url ? buildInlineLinkChip(url, title) : escapeHtml(title)}
                    ${snippet ? `<div style="font-size:13px;color:rgba(236,238,244,.6);margin-top:4px;">${linkifyText(snippet)}</div>` : ''}
                </div>`;
            }).join('');
        }
        const galleryHtml = images.length ? buildImageGallery(images) : '';
        return `<div class="live-card">
            <div class="live-card-head"><i class="fa-solid fa-magnifying-glass"></i> Web results</div>
            <div class="live-card-body">${body || '<span style="opacity:.5">No results</span>'}</div>
        </div>${galleryHtml}`;
    }

    // ---------------- dispatcher for structured ui_type/ui_data ----------------
    function detectUiKind(uiType, data) {
        if (uiType === 'search' || uiType === 'search_results') return 'search';
        if (uiType === 'file') return 'file';
        if (uiType === 'music_player') return 'music_player';
        if (uiType === 'music_control') return 'music_control';
        if (data && typeof data === 'object' && (Array.isArray(data.organic_results) || Array.isArray(data.ai_links))) return 'search';
        if (data && typeof data === 'object' && !Array.isArray(data) && typeof data.filename === 'string' && typeof data.view_url === 'string') return 'file';
        if (Array.isArray(data) && data.length && data.every(it => it && typeof it === 'object' && (it.media_url || it.image_url))) return 'media';
        return 'generic';
    }

    function renderUiData(uiType, data) {
        if (!data) return '';
        const kind = detectUiKind(uiType, data);
        if (kind === 'file') {
            const rawViewUrl = typeof data.view_url === 'string' ? data.view_url : '';
            const card = buildFileCard(rawViewUrl, data.display_name || data.filename);
            return card || buildGenericCard(data);
        }
        if (kind === 'search') return buildSearchCard(data);
        if (kind === 'media') {
            // Plain image galleries from other tools (astro_mcp, etc.) —
            // unrelated to music_mcp.py, which uses music_player/
            // music_control below instead of raw audio/video URLs.
            const imgs = data.filter(it => (it.media_type || (it.image_url ? 'image' : '')) === 'image' || it.image_url)
                              .map(it => ({ url: it.media_url || it.image_url, title: it.title }));
            return imgs.length ? buildImageGallery(imgs) : buildGenericCard(data);
        }
        if (kind === 'music_player') {
            playHinaMusic(data.video_id, data.title);
            return ''; // instruction, not a card — nothing to render inline
        }
        if (kind === 'music_control') {
            controlHinaMusic(data.action);
            return '';
        }
        return buildGenericCard(data);
    }

    // ------------------------------------------------------------
    // Background music — music_mcp.py's play_music/pause_music/
    // resume_music/stop_music send {ui_type:"music_player",
    // ui_data:{video_id, title}} and {ui_type:"music_control",
    // ui_data:{action}}. This drives one shared YouTube IFrame Player
    // instance instead of a raw <audio src="..."> — that never worked
    // because what yt_helper resolves is a normal youtube.com/watch
    // page, not an audio stream a browser <audio> tag can play. The
    // IFrame API takes a video ID and gives back a real JS control
    // surface (playVideo/pauseVideo/stopVideo).
    //
    // No visible player UI: the mount div is created once, hidden
    // (1x1, off-screen) and NEVER removed from the DOM. Everything the
    // user sees is a normal stream line ("🎵 Playing: <title>" /
    // "Paused" / "Resumed" / "Stopped") added via addBlock, same as
    // any other stream item.
    //
    // This also fixes the old "player is not attached to DOM" /
    // postMessage-origin bug: that happened because the widget's close
    // button removed the DOM node but left `ytPlayer` pointing at the
    // now-destroyed instance, so the next play_music call tried to
    // call methods on a dead object. Since the mount div is permanent
    // now, `ytPlayer` never goes stale.
    // ------------------------------------------------------------
    let ytPlayer = null;
    let ytApiLoading = false;
    const ytApiWaiters = [];

    function ensureYtIframeApi(cb) {
        if (window.YT && window.YT.Player) { cb(); return; }
        ytApiWaiters.push(cb);
        if (ytApiLoading) return;
        ytApiLoading = true;
        const prevReady = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = () => {
            if (typeof prevReady === 'function') prevReady();
            ytApiWaiters.splice(0).forEach((fn) => fn());
        };
        if (!document.getElementById('yt-iframe-api-script')) {
            const tag = document.createElement('script');
            tag.id = 'yt-iframe-api-script';
            tag.src = 'https://www.youtube.com/iframe_api';
            document.head.appendChild(tag);
        }
    }

    function ensureHiddenMusicMount() {
        let mount = document.getElementById('hina-music-player-mount');
        if (mount) return mount;
        mount = document.createElement('div');
        mount.id = 'hina-music-player-mount';
        // Kept in the DOM (required for the IFrame API to attach to)
        // but visually gone — no widget, no overlay, ever.
        mount.style.cssText = 'position:fixed; width:1px; height:1px; left:-9999px; bottom:-9999px; overflow:hidden;';
        document.body.appendChild(mount);
        return mount;
    }

    function addMusicStreamLine(text, icon) {
        addBlock(`<i class="${icon || 'fa-solid fa-music'}"></i> Music player`,
            `<div class="live-card"><div class="live-card-body">${escapeHtml(text)}</div></div>`);
    }

    function playHinaMusic(videoId, title) {
        if (!videoId) return;
        const label = title || 'Music';
        musicPlaying = true;
        addMusicStreamLine(`🎵 Playing: ${label}`, 'fa-solid fa-music');
        ensureYtIframeApi(() => {
            ensureHiddenMusicMount();
            if (ytPlayer && typeof ytPlayer.loadVideoById === 'function') {
                ytPlayer.loadVideoById(videoId);
                try { ytPlayer.playVideo(); } catch (e) {}
                return;
            }
            ytPlayer = new YT.Player('hina-music-player-mount', {
                height: '1',
                width: '1',
                videoId,
                playerVars: { autoplay: 1, controls: 0, playsinline: 1 },
                events: {
                    onReady: (e) => { try { e.target.playVideo(); } catch (err) {} },
                    onError: () => addMusicStreamLine(`Playback failed — "${label}" is unavailable`, 'fa-solid fa-triangle-exclamation')
                }
            });
        });
    }

    function controlHinaMusic(action) {
        if (!ytPlayer) return;
        if (action === 'pause' && typeof ytPlayer.pauseVideo === 'function') {
            ytPlayer.pauseVideo();
            musicPlaying = false;
            addMusicStreamLine('⏸ Paused music', 'fa-solid fa-pause');
        } else if (action === 'resume' && typeof ytPlayer.playVideo === 'function') {
            ytPlayer.playVideo();
            musicPlaying = true;
            addMusicStreamLine('▶️ Resumed music', 'fa-solid fa-play');
        } else if (action === 'stop' && typeof ytPlayer.stopVideo === 'function') {
            ytPlayer.stopVideo();
            musicPlaying = false;
            addMusicStreamLine('⏹ Stopped music', 'fa-solid fa-stop');
            // Deliberately NOT destroying/removing the mount or nulling
            // ytPlayer here — that removal is exactly what caused the
            // old stale-reference bug. The hidden mount and player
            // instance just sit idle until the next play_music call.
        }
    }

    function renderIncomingRichContent(uiType, data, agentName) {
        const html = renderUiData(uiType, data);
        if (!html) return; // covers music_player/music_control, which act directly and render nothing inline
        const tagIcon = detectUiKind(uiType, data) === 'file' ? 'fa-solid fa-file-arrow-down'
                      : detectUiKind(uiType, data) === 'search' ? 'fa-solid fa-magnifying-glass'
                      : detectUiKind(uiType, data) === 'media' ? 'fa-solid fa-images'
                      : 'fa-solid fa-shapes';
        const block = addBlock(`<i class="${tagIcon}"></i> ${escapeHtml(agentName || 'HINA')}`, html);
        if (block) wireGalleries(block);
    }

    // ---------------- mic acquisition (kept open for the whole session) ----------------
    async function ensureMic() {
        if (micStream) return micStream;
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                // Lets the browser subtract known output (HINA's TTS
                // voice, her background music) from what the mic
                // captures, instead of us guessing after the fact.
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        });
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioCtx.createMediaStreamSource(micStream);
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.75;
        source.connect(analyser);
        meterTick();
        return micStream;
    }

    function releaseMic() {
        if (meterRAF) cancelAnimationFrame(meterRAF);
        meterRAF = null;
        if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
        if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
        analyser = null;
    }

    function currentEnergy() {
        if (!analyser) return 0;
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
            const v = (data[i] - 128) / 128;
            sum += v * v;
        }
        return Math.sqrt(sum / data.length);
    }

    function meterTick() {
        if (!analyser) return;
        const energy = currentEnergy();

        if (state === 'listening' && recording) {
            // While HINA's own music is playing, echoCancellation won't
            // always fully scrub it (Bluetooth speakers, loud external
            // playback, etc.), so require a much bigger jump over the
            // room floor before we call it "speech" — a real voice
            // interrupting music is usually much louder than the music
            // leaking into the mic.
            const threshold = energyFloor * (musicPlaying ? 3.5 : 1.6);
            const isSpeech = energy > threshold;
            if (isSpeech) {
                if (!speechStarted) { speechStarted = true; speechStartedAt = Date.now(); }
                clearTimeout(silenceTimer);
                silenceTimer = setTimeout(onSilenceDetected, SILENCE_MS);
            } else if (!speechStarted) {
                // still quiet — slowly track the room's noise floor
                energyFloor = energyFloor * 0.98 + energy * 0.02;
            }
        }

        meterRAF = requestAnimationFrame(meterTick);
    }

    // ---------------- recording one utterance ----------------
    async function startRecording() {
        if (recording) return;
        try {
            await ensureMic();
        } catch (err) {
            console.error('[live] mic permission failed:', err);
            if (el.caption) el.caption.textContent = 'Microphone access blocked — allow it to use voice mode.';
            setState('error');
            return;
        }

        recordedChunks = [];
        speechStarted = false;
        clearTimeout(silenceTimer);
        clearTimeout(maxRecordingTimer);

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : 'audio/webm';
        recorder = new MediaRecorder(micStream, { mimeType });
        recorder.ondataavailable = (e) => { if (e.data && e.data.size) recordedChunks.push(e.data); };
        recorder.onstop = handleRecordingStopped;
        recorder.start();
        recording = true;

        // Hard cap so one long ramble (or continuous background noise
        // being misread as speech) can't hang the turn forever. Armed
        // exactly once per recording, on its own timer variable — never
        // touched by meterTick, so unlike the old code it can't be
        // reset every frame by ongoing "speech" energy.
        maxRecordingTimer = setTimeout(onSilenceDetected, MAX_RECORDING_MS);
    }

    function stopRecordingIfActive() {
        clearTimeout(silenceTimer);
        clearTimeout(maxRecordingTimer);
        if (recording && recorder && recorder.state !== 'inactive') {
            try { recorder.stop(); } catch (_) {}
        }
        recording = false;
    }

    function onSilenceDetected() {
        if (!recording) return;
        recording = false;
        clearTimeout(silenceTimer);
        clearTimeout(maxRecordingTimer);
        if (recorder && recorder.state !== 'inactive') {
            try { recorder.stop(); } catch (_) {}
        }
    }

    async function handleRecordingStopped() {
        const hadSpeech = speechStarted && (Date.now() - speechStartedAt) > MIN_SPEECH_MS;
        const blob = new Blob(recordedChunks, { type: recorder.mimeType || 'audio/webm' });
        recordedChunks = [];

        if (!hadSpeech || blob.size < 800) {
            // essentially silence — just keep listening, no request sent
            if (state === 'listening' && !muted) startRecording();
            return;
        }

        if (transcribeInFlight) {
            // a turn is already out to the server (or awaiting its ack) —
            // never fire a second one on top of it, that's how one
            // utterance ends up sent (and shown) twice
            console.warn('[live] dropping recording — a turn is already in flight');
            return;
        }
        transcribeInFlight = true;

        try {
            await fetch(`/live/transcribe?session_id=${encodeURIComponent(getSessionId())}`, {
                method: 'POST',
                headers: { 'Content-Type': blob.type || 'audio/webm' },
                body: blob
            });
            // server pushes {type:"state","thinking"|"listening"} etc over
            // /ws from here — this page just reacts to that. transcribeInFlight
            // clears as soon as that real state push arrives (handleWsPayload),
            // not here — the request resolving just means it was received,
            // not that the turn is finished.
        } catch (err) {
            console.error('[live] transcribe upload failed:', err);
            transcribeInFlight = false;
            setState('error');
            if (el.caption) el.caption.textContent = "Couldn't reach HINA — check the backend.";
            setTimeout(() => { if (!muted) setState('listening'); }, 1800);
        }
    }

    // ---------------- websocket ----------------
    function connectWs() {
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        ws = new WebSocket(`${proto}://${window.location.host}/ws`);

        ws.onopen = () => {
            if (hasConnectedBefore) {
                // This is a RECONNECT, not the initial page load. Anything the
                // server pushed while we were disconnected is gone — there is
                // no resync/replay, so if we were mid-turn we have no way to
                // know whether HINA already replied or is still working.
                // Leaving the UI silently stuck on "thinking"/"speaking"
                // forever (which is exactly what a lost message looks like)
                // is worse than surfacing it — go to error so the user can
                // just tap the mic and re-ask instead of staring at a dead
                // spinner.
                if (state === 'thinking' || state === 'speaking' || state === 'loading') {
                    console.warn('[live] websocket reconnected mid-turn — the previous reply may have been lost');
                    transcribeInFlight = false;
                    if (!muted) {
                        setState('error');
                        if (el.caption) el.caption.textContent = 'Connection dropped — tap the mic to try again.';
                    }
                } else if (state === 'idle' && !muted && el.statusText) {
                    el.statusText.textContent = 'Ready';
                }
            } else {
                hasConnectedBefore = true;
                if (state === 'idle' && !muted && el.statusText) el.statusText.textContent = 'Ready';
            }
        };

        ws.onmessage = (event) => {
            let data;
            try { data = JSON.parse(event.data); }
            catch (err) { console.error('[live] bad ws payload', err); return; }
            handleWsPayload(data);
        };

        ws.onclose = () => {
            clearTimeout(wsReconnectTimer);
            wsReconnectTimer = setTimeout(connectWs, 2000);
        };
        ws.onerror = (err) => console.error('[live] ws error', err);
    }

    function handleWsPayload(data) {
        if (!data || typeof data !== 'object') return;

        // hin_voice_engine.py -> Node -> here: each synthesized speech
        // chunk arrives as {type:'voice_chunk', ...}. This was never
        // routed to voice-player.js on the /live page either — same
        // missing wiring as the main chat page, and the same reason
        // voice was completely silent while music kept working (music
        // goes through the separate YouTube IFrame path).
        if (data.type === 'voice_chunk') {
            if (window.HinaVoicePlayer) window.HinaVoicePlayer.handleChunk(data, ws);
            return;
        }

        if (data.type === 'state' && typeof data.state === 'string') {
            if (data.state === 'thinking') currentAgentLineEl = null;
            // any real state push from the server means the current turn
            // has been acknowledged (or a new one is starting) — safe to
            // allow another submission again
            transcribeInFlight = false;
            if (!muted) setState(data.state);
            return;
        }

        if (data.type === 'transcript' && typeof data.text === 'string' && data.text.trim()) {
            if (data.role === 'user') {
                const text = data.text.trim();
                const now = Date.now();
                // defensive dedupe: if the exact same user line shows up
                // again within a few seconds (e.g. a duplicated broadcast
                // after a reconnect), don't render it a second time
                if (text === lastUserTranscript && (now - lastUserTranscriptAt) < 4000) {
                    return;
                }
                lastUserTranscript = text;
                lastUserTranscriptAt = now;
                addLine('user', text);
            } else {
                if (!currentAgentLineEl) currentAgentLineEl = addLine('agent', data.text.trim());
                else currentAgentLineEl.textContent = data.text.trim();
                scrollStreamToBottom();
            }
            // a transcript event can still carry rich content alongside text
            if (data.ui_data) renderIncomingRichContent(data.ui_type, data.ui_data, data.agent_name);
            return;
        }

        // Rich structured content (files, images, search/data cards) —
        // same send_ui_json() shape the main chat renders.
        if (data.ui_data) {
            renderIncomingRichContent(data.ui_type, data.ui_data, data.agent_name);
            if (typeof data.text === 'string' && data.text.trim()) {
                if (!currentAgentLineEl) currentAgentLineEl = addLine('agent', data.text.trim());
                else currentAgentLineEl.textContent = data.text.trim();
            }
            if (data.done === true) currentAgentLineEl = null;
            return;
        }

        // fallback: generic agent push (same shape the main chat's /ws
        // messages use) while a reply is streaming in
        if (typeof data.text === 'string' && data.text.trim() && (state === 'thinking' || state === 'speaking')) {
            if (!currentAgentLineEl) currentAgentLineEl = addLine('agent', data.text.trim());
            else currentAgentLineEl.textContent = data.text.trim();
            scrollStreamToBottom();
        }
        if (data.done === true) currentAgentLineEl = null;
    }

    // ---------------- server-side engine control (handshake) ----------------
    async function startEngine() {
        setState('loading');
        try {
            const res = await fetch('/live/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: getSessionId() })
            });
            const data = await res.json().catch(() => ({}));
            if (data.status !== 'ready') {
                setState('error');
                if (el.caption) el.caption.textContent = 'Voice model took too long to load — try again.';
                return;
            }
            // server has already broadcast "listening" over /ws, which
            // will flip state and start recording via setState()
        } catch (err) {
            console.error('[live] failed to start engine:', err);
            setState('error');
            if (el.caption) el.caption.textContent = "Couldn't reach HINA — check the backend.";
        }
    }

    async function stopEngine() {
        stopRecordingIfActive();
        releaseMic();
        try { await fetch('/live/stop', { method: 'POST' }); } catch (err) {
            console.error('[live] failed to stop engine:', err);
        }
    }

    // ---------------- controls ----------------
    function toggleMute() {
        muted = !muted;
        if (el.muteBtn) {
            el.muteBtn.classList.toggle('muted', muted);
            const icon = el.muteBtn.querySelector('i');
            if (icon) icon.className = muted ? 'fa-solid fa-microphone-slash' : 'fa-solid fa-microphone';
        }
        if (muted) {
            stopRecordingIfActive();
            setState('idle');
        } else {
            transcribeInFlight = false;
            setState('listening');
        }
    }

    // ---------------- boot ----------------
    // Everything that touches the DOM happens in here, after
    // DOMContentLoaded, and every element lookup is null-checked before
    // a listener is attached to it. A missing/renamed id in live.html
    // now just silently skips that one piece of UI instead of throwing
    // and freezing the whole page on "Connecting…".
    function init() {
        el.app = document.getElementById('live-app');
        el.backBtn = document.getElementById('live-back-btn');
        el.muteBtn = document.getElementById('live-mute-btn');
        el.dot = document.getElementById('live-dot');
        el.statusText = document.getElementById('live-status-text');
        el.dock = document.getElementById('live-dock');
        el.waveCanvas = document.getElementById('live-waveform');
        el.caption = document.getElementById('live-caption');
        el.stream = document.getElementById('live-stream');
        el.streamEmpty = document.getElementById('live-stream-empty');
        el.scrollBtn = document.getElementById('live-scroll-btn');
        el.micBtn = document.getElementById('live-mic-btn');

        if (el.waveCanvas) {
            try { wctx = el.waveCanvas.getContext('2d'); } catch (e) { console.error('[live] canvas ctx failed', e); }
        }

        window.addEventListener('resize', sizeWaveform);
        if (el.stream) {
            el.stream.addEventListener('scroll', () => {
                if (el.scrollBtn) el.scrollBtn.classList.toggle('hidden', isNearBottom());
            });
        }
        if (el.scrollBtn) el.scrollBtn.addEventListener('click', () => scrollStreamToBottom(true));

        if (el.backBtn) el.backBtn.addEventListener('click', () => {
            stopEngine();
            window.location.href = '/';
        });
        if (el.muteBtn) el.muteBtn.addEventListener('click', toggleMute);
        if (el.micBtn) el.micBtn.addEventListener('click', () => {
            if (muted) { toggleMute(); return; }
            if (state === 'error') { clearClientWatchdog(); transcribeInFlight = false; setState('listening'); }
        });
        if (el.dock) el.dock.addEventListener('click', () => {
            if (muted) { toggleMute(); return; }
            if (state === 'error') { clearClientWatchdog(); transcribeInFlight = false; setState('listening'); }
        });

        sizeWaveform();
        setState('idle');
        connectWs();
        drawWaveform();
        startEngine(); // handshake: loads the model once for this session; server then
                        // drives listening -> thinking -> speaking -> listening via /ws,
                        // and this page just reacts — it never guesses when HINA is done talking.
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOMContentLoaded already fired (script loaded late/async) — run now.
        init();
    }

    window.addEventListener('beforeunload', () => {
        stopEngine();
        if (ws) ws.close();
    });
})();