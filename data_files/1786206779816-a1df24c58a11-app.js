// app.js
//
// ============================================================
// SEND_STATE COLOR PALETTE
// ------------------------------------------------------------
// Your backend can drive the UI's color entirely through the
// payload it sends over the websocket / POST'd to the client.
// Two ways to set color on any payload:
//
//   1) { "color": "124,138,255" }        -> raw "r,g,b" string
//   2) { "color_name": "think" }         -> looks up the table below
//
// If neither is given, HINA hashes agent_name to a stable color
// from this same table so the same agent always looks the same.
//
// Available color_name values (semantic, matches CSS vars in
// style.css under :root so the orb / status dot / trace icons /
// agent avatar all stay in sync with the palette):
//
//   name        rgb                depict / suggested use
//   ----------  -----------------  --------------------------------
//   idle        110,113,122        standby, no active agent
//   think       124,138,255        general reasoning / planning
//   reason      168,140,255        deep/extended reasoning
//   tool        59,157,246         calling a tool / function
//   search       45,190,190        retrieval, web search, RAG
//   success      52,199,140        completed successfully
//   warn        235,158, 52        caution, retry, degraded
//   error       235, 90,100        failure / exception
//   voice        45,209,230        live voice / audio input
//   creative    214,110,235        generation, creative writing
//
// Example payload your backend can emit:
//   { "agent_name": "PLANNER", "state": "SYS_THINK",
//     "msg": "Breaking task into steps", "color_name": "reason",
//     "icon": "fa-solid fa-diagram-project", "done": false }
// ============================================================

const COLOR_PALETTE = {
    idle:     '110,113,122',
    think:    '124,138,255',
    reason:   '168,140,255',
    tool:     '59,157,246',
    search:   '45,190,190',
    success:  '52,199,140',
    warn:     '235,158,52',
    error:    '235,90,100',
    voice:    '45,209,230',
    creative: '214,110,235'
};
const PALETTE_FALLBACK_ORDER = Object.values(COLOR_PALETTE);

// ============================================================
// NOTE: HINA has no logo mark. Any "logo" / brand-glyph fields a
// backend state payload might send (icon, color used for a mark,
// etc.) are intentionally ignored here — the header is text-only.
// The "thinking" visual identity lives entirely in the weave
// animation below (.thinking-dots), driven purely by CSS.
// ============================================================

function sanitizePayload(raw) {
    const data = (raw && typeof raw === 'object') ? raw : {};

    const agent_name = typeof data.agent_name === 'string' && data.agent_name.trim() ? data.agent_name.trim() : 'SYSTEM';
    const state = typeof data.state === 'string' && data.state.trim() ? data.state.trim() : 'PROCESSING';
    const msg = typeof data.msg === 'string' ? data.msg : '';
    const text = typeof data.text === 'string' ? data.text : null;
    const icon = typeof data.icon === 'string' && data.icon.trim() ? data.icon.trim() : 'fa-solid fa-circle-notch';

    // Structured UI payload (send_ui_json on the backend) — arrives
    // as a real object/array, not text, so there's no ~~ / quoting
    // dance needed for this path.
    const ui_type = typeof data.ui_type === 'string' && data.ui_type.trim() ? data.ui_type.trim().toLowerCase() : null;
    const ui_data = (data.ui_data && typeof data.ui_data === 'object') ? data.ui_data : null;

    let color = null;
    if (typeof data.color === 'string' && /^\d+,\s*\d+,\s*\d+$/.test(data.color)) {
        color = data.color;
    } else if (typeof data.color_name === 'string' && COLOR_PALETTE[data.color_name]) {
        color = COLOR_PALETTE[data.color_name];
    }
    if (!color) {
        let hash = 0;
        for (let i = 0; i < agent_name.length; i++) hash = agent_name.charCodeAt(i) + ((hash << 5) - hash);
        color = PALETTE_FALLBACK_ORDER[Math.abs(hash) % PALETTE_FALLBACK_ORDER.length];
    }

    const is_voice = data.is_voice === true;
    const done = data.done === true || state === 'SYS_DONE';

    return { agent_name, state, msg, text, icon, color, is_voice, done, ui_type, ui_data };
}

document.addEventListener('DOMContentLoaded', () => {
    const ui = {
        chat: document.getElementById('chat-window'),
        emptyState: document.getElementById('empty-state'),
        stateLabel: document.getElementById('ui-state-label'),
        statusDot: document.getElementById('status-dot'),
        tokenEcho: document.getElementById('live-token-echo'),
        input: document.getElementById('prompt-input'),
        sendBtn: document.getElementById('send-btn'),
        scrollBtn: document.getElementById('scroll-bottom-btn'),
        clearBtn: document.getElementById('clear-chat-btn')
    };

    // ------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------
    function escapeHtml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
    // user sees is a normal chat line ("🎵 Playing: <title>" /
    // "Paused" / "Resumed" / "Stopped") added via addAgentBubble, same
    // as any other agent message.
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

    // Chat-visible line for a music event. Ends any in-progress token
    // stream first so this lands as its own bubble instead of getting
    // glued onto whatever the model was mid-sentence on.
    function addMusicChatLine(text, icon) {
        ensureTurn();
        finalizeStream(activeStream);
        activeStream = null;
        const el = addAgentBubble(currentTurnEl, 'Music player', icon || 'fa-solid fa-music', COLOR_PALETTE.idle);
        el.textContent = text;
        scrollToBottom();
    }

    function playHinaMusic(videoId, title) {
        if (!videoId) return;
        const label = title || 'Music';
        addMusicChatLine(`🎵 Playing: ${label}`, 'fa-solid fa-music');
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
                    onError: () => addMusicChatLine(`Playback failed — "${label}" is unavailable`, 'fa-solid fa-triangle-exclamation')
                }
            });
        });
    }

    function controlHinaMusic(action) {
        if (!ytPlayer) return;
        if (action === 'pause' && typeof ytPlayer.pauseVideo === 'function') {
            ytPlayer.pauseVideo();
            addMusicChatLine('⏸ Paused music', 'fa-solid fa-pause');
        } else if (action === 'resume' && typeof ytPlayer.playVideo === 'function') {
            ytPlayer.playVideo();
            addMusicChatLine('▶️ Resumed music', 'fa-solid fa-play');
        } else if (action === 'stop' && typeof ytPlayer.stopVideo === 'function') {
            ytPlayer.stopVideo();
            addMusicChatLine('⏹ Stopped music', 'fa-solid fa-stop');
            // Deliberately NOT destroying/removing the mount or nulling
            // ytPlayer here — that removal is exactly what caused the
            // old stale-reference bug. The hidden mount and player
            // instance just sit idle until the next play_music call.
        }
    }

    // ------------------------------------------------------------
    // Link detection & sanitization
    // ------------------------------------------------------------
    // URLs can arrive in all sorts of ways: a full search-results
    // payload, a structured ui_data blob, a trace step whose msg
    // IS a bare url ("Links" / "https://..."), or just a stray
    // "check this out: https://example.com" sitting inside normal
    // prose. All of those funnel through the helpers below so a
    // link never renders as raw, unstyled, unsafe text.
    const URL_RE = /\bhttps?:\/\/[^\s<>"'`)\]]+/gi;

    // Trailing punctuation ("...serp.)" or a sentence period) often
    // gets swept up by the URL match — strip it off the end so the
    // link itself stays clean while the punctuation stays in prose.
    function stripTrailingPunct(url) {
        return url.replace(/[).,;:!?\]}'"]+$/, '');
    }

    // Only http/https survive — javascript:, data:, file:, etc. are
    // never allowed to reach an href, no matter where the string
    // came from (model output, tool result, or user text).
    function sanitizeUrl(raw) {
        if (typeof raw !== 'string') return null;
        const trimmed = stripTrailingPunct(raw.trim());
        try {
            const u = new URL(trimmed);
            if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
            return u.href;
        } catch (e) { return null; }
    }

    function looksLikeBareUrl(str) {
        if (typeof str !== 'string') return false;
        const t = str.trim();
        return /^https?:\/\/\S+$/i.test(t);
    }

    function hostnameOf(url) {
        try { return new URL(url).hostname.replace(/^www\./, ''); }
        catch (e) { return url; }
    }
    function faviconUrl(url) {
        try { return `https://www.google.com/s2/favicons?sz=64&domain=${new URL(url).hostname}`; }
        catch (e) { return ''; }
    }

    // A small inline "chip" for a URL found in the middle of prose
    // — favicon + hostname + external-link glyph, not a raw string.
    function buildInlineLinkChip(rawUrl) {
        const safe = sanitizeUrl(rawUrl);
        if (!safe) return escapeHtml(rawUrl);
        const host = hostnameOf(safe);
        return `<a class="text-link-chip" href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(safe)}">` +
            `<img class="text-link-favicon" src="${faviconUrl(safe)}" alt="" loading="lazy" onerror="this.style.display='none'">` +
            `<span>${escapeHtml(host)}</span>` +
            `<i class="fa-solid fa-arrow-up-right-from-square"></i></a>`;
    }

    // ------------------------------------------------------------
    // Video detection & inline player
    // ------------------------------------------------------------
    // Any URL that resolves to a YouTube / Vimeo watch page, or a
    // direct link to a video file (remote http(s) OR a local
    // file:// / bare filesystem path ending in a video extension),
    // gets swapped for a real inline player instead of a plain
    // link chip. Site-hosted videos (YouTube, Vimeo) use that
    // site's own embeddable player. Direct video files get a
    // custom-skinned HTML5 player styled to look like a small
    // native (mpv-ish) window: title bar + controls, dark chrome,
    // matching the rest of HINA's theme.
    let videoPlayerCounter = 0;

    function extractYouTubeId(url) {
        try {
            const u = new URL(url);
            const host = u.hostname.replace(/^www\./, '');
            if (host === 'youtu.be') {
                const id = u.pathname.slice(1).split('/')[0];
                return id || null;
            }
            if (host === 'youtube.com' || host === 'm.youtube.com' || host === 'music.youtube.com') {
                if (u.pathname === '/watch') return u.searchParams.get('v');
                const shortsMatch = u.pathname.match(/^\/(shorts|embed|live)\/([^/?]+)/);
                if (shortsMatch) return shortsMatch[2];
            }
        } catch (e) { /* not a valid URL */ }
        return null;
    }

    function extractVimeoId(url) {
        try {
            const u = new URL(url);
            const host = u.hostname.replace(/^www\./, '');
            if (host !== 'vimeo.com' && host !== 'player.vimeo.com') return null;
            const m = u.pathname.match(/(\d{6,})/);
            return m ? m[1] : null;
        } catch (e) { return null; }
    }

    const VIDEO_FILE_RE = /\.(mp4|webm|ogg|ogv|mov|m4v|mkv)(\?.*)?$/i;

    // Bare local paths (no scheme) like "/home/user/clip.mp4" or
    // "C:\Videos\clip.mkv" that a backend/tool might drop into text
    // as plain strings rather than a proper file:// URL.
    const LOCAL_VIDEO_PATH_RE = /^(?:[a-zA-Z]:\\|\/|\.\.?\/)[^\s<>"'`]*\.(mp4|webm|ogg|ogv|mov|m4v|mkv)$/i;

    function isDirectVideoUrl(url) {
        return VIDEO_FILE_RE.test(url);
    }

    function fileNameOf(pathOrUrl) {
        try {
            const clean = pathOrUrl.split(/[?#]/)[0];
            const parts = clean.split(/[\\/]/);
            return parts[parts.length - 1] || pathOrUrl;
        } catch (e) { return pathOrUrl; }
    }

    // Build the little chrome/title bar shared by both the embed
    // iframe wrapper and the native <video> player, so YouTube,
    // Vimeo, and local mp4 all read as "one player component"
    // rather than three unrelated widgets.
    function buildPlayerChrome(iconClass, label, bodyHtml, extraClass) {
        const safeLabel = escapeHtml(label);
        return `<div class="video-embed-wrap ${extraClass || ''}">
            <div class="video-embed-titlebar">
                <span class="video-embed-dots"><i></i><i></i><i></i></span>
                <i class="${iconClass} video-embed-titleicon"></i>
                <span class="video-embed-title" title="${safeLabel}">${safeLabel}</span>
            </div>
            <div class="video-embed-body">${bodyHtml}</div>
        </div>`;
    }

    function buildYouTubeEmbed(videoId) {
        const src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}?rel=0&modestbranding=1`;
        const body = `<div class="video-embed-ratio">
                <iframe src="${src}" title="YouTube video player" loading="lazy"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>
            </div>`;
        return buildPlayerChrome('fa-brands fa-youtube', 'YouTube', body, 'video-embed-site');
    }

    function buildVimeoEmbed(videoId) {
        const src = `https://player.vimeo.com/video/${encodeURIComponent(videoId)}`;
        const body = `<div class="video-embed-ratio">
                <iframe src="${src}" title="Vimeo video player" loading="lazy"
                    allow="autoplay; fullscreen; picture-in-picture; clipboard-write" allowfullscreen></iframe>
            </div>`;
        return buildPlayerChrome('fa-brands fa-vimeo-v', 'Vimeo', body, 'video-embed-site');
    }

    // Direct video file — remote http(s) or local file:// / bare
    // path. Uses the browser's native <video> element (the in-
    // browser equivalent of handing the file to mpv: no site, no
    // player to fetch, just the raw media), skinned to look like a
    // small dark native player window rather than the browser's
    // default unstyled control bar.
    function buildNativeVideoEmbed(src, displayLabel) {
        const id = `hina-video-${Date.now()}-${videoPlayerCounter++}`;
        const safeSrc = escapeHtml(src);
        const body = `<div class="video-embed-ratio video-embed-native-ratio">
                <video id="${id}" class="video-embed-native-el" controls preload="metadata" playsinline>
                    <source src="${safeSrc}">
                    Your browser can't play this video file directly.
                </video>
            </div>`;
        return buildPlayerChrome('fa-solid fa-play', displayLabel, body, 'video-embed-native');
    }

    // Entry point: given a raw URL/path string, return embed HTML
    // if it's a recognized video source, else null (caller falls
    // back to the normal link chip).
    function buildVideoEmbedIfApplicable(rawUrl) {
        if (typeof rawUrl !== 'string' || !rawUrl.trim()) return null;
        const trimmed = stripTrailingPunct(rawUrl.trim());

        // Local filesystem path with no scheme (mpv-style local file).
        if (LOCAL_VIDEO_PATH_RE.test(trimmed)) {
            return buildNativeVideoEmbed(trimmed, fileNameOf(trimmed));
        }

        let u;
        try { u = new URL(trimmed); } catch (e) { return null; }

        if (u.protocol === 'file:') {
            return buildNativeVideoEmbed(trimmed, fileNameOf(u.pathname));
        }
        if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;

        const ytId = extractYouTubeId(trimmed);
        if (ytId) return buildYouTubeEmbed(ytId);

        const vimeoId = extractVimeoId(trimmed);
        if (vimeoId) return buildVimeoEmbed(vimeoId);

        if (isDirectVideoUrl(trimmed)) {
            return buildNativeVideoEmbed(trimmed, fileNameOf(trimmed));
        }

        return null;
    }

    // ------------------------------------------------------------
    // HINA-generated file cards — any link the backend sends that
    // points at /download/hina/files/<filename> (hina_sdk.py's
    // send_file()) gets rendered as a file card instead of a plain
    // link chip: filename + language-colored icon, a View button
    // that opens the file in the code-canvas modal, and a Download
    // button that saves it straight to disk.
    // ------------------------------------------------------------
    const HINA_FILE_LINK_RE = /\/download\/hina\/files\/([^\/?#\s"'<>]+)\/?$/i;

    const FILE_EXT_LANG = {
        js: 'javascript', jsx: 'jsx', ts: 'typescript', tsx: 'tsx',
        py: 'python', rb: 'ruby', go: 'go', rs: 'rust', java: 'java',
        c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', cs: 'csharp',
        php: 'php', sh: 'bash', bash: 'bash', zsh: 'bash',
        html: 'xml', htm: 'xml', xml: 'xml', css: 'css', scss: 'scss',
        json: 'json', yml: 'yaml', yaml: 'yaml', sql: 'sql',
        md: 'markdown', txt: 'plaintext', csv: 'plaintext',
        kt: 'kotlin', swift: 'swift', dart: 'dart', lua: 'lua'
    };

    const FILE_EXT_ICON = {
        js: 'fa-js', jsx: 'fa-react', ts: 'fa-js', tsx: 'fa-react',
        py: 'fa-python', html: 'fa-html5', htm: 'fa-html5',
        css: 'fa-css3-alt', scss: 'fa-css3-alt', java: 'fa-java',
        php: 'fa-php', sh: 'fa-terminal', bash: 'fa-terminal',
        md: 'fa-markdown', json: 'fa-code'
    };

    function fileExtOf(filename) {
        const m = /\.([a-z0-9]+)$/i.exec(filename || '');
        return m ? m[1].toLowerCase() : '';
    }

    let hinaFileCardCounter = 0;

    // Returns file-card HTML if rawUrl is a HINA-generated-file
    // link, else null (caller falls back to the normal link chip).
    // `displayName`, when given (e.g. code_mcp.py's human-readable
    // display_name), is what's shown on the card and used for the
    // download attribute; the raw hashed filename from the URL is
    // still kept in data-filename for the view/download requests,
    // it's just never shown to the user.
    function buildHinaFileCardIfApplicable(rawUrl, displayName) {
        if (typeof rawUrl !== 'string' || !rawUrl.trim()) return null;
        const trimmed = stripTrailingPunct(rawUrl.trim());
        const safe = sanitizeUrl(trimmed);
        if (!safe) return null;
        const m = HINA_FILE_LINK_RE.exec(safe);
        if (!m) return null;

        const rawFilename = decodeURIComponent(m[1]);
        const label = (typeof displayName === 'string' && displayName.trim()) ? displayName.trim() : rawFilename;
        const ext = fileExtOf(label) || fileExtOf(rawFilename);
        const iconClass = FILE_EXT_ICON[ext] || 'fa-file-lines';
        const cardId = `hina-file-${Date.now()}-${hinaFileCardCounter++}`;
        const downloadUrl = safe.replace(/\/?$/, '') + '/save';

        return `<div class="hina-file-card" id="${cardId}" data-view-url="${escapeHtml(safe)}" data-download-url="${escapeHtml(downloadUrl)}" data-filename="${escapeHtml(label)}" data-ext="${escapeHtml(ext)}">
            <div class="hina-file-icon"><i class="fa-solid ${iconClass}"></i></div>
            <div class="hina-file-info">
                <div class="hina-file-name">${escapeHtml(label)}</div>
                <div class="hina-file-sub">${ext ? escapeHtml(ext.toUpperCase()) + ' file' : 'File'} · from HINA</div>
            </div>
            <div class="hina-file-actions">
                <button type="button" class="hina-file-btn hina-file-view-btn" data-target="${cardId}" title="View">
                    <i class="fa-solid fa-eye"></i><span>view</span>
                </button>
                <a class="hina-file-btn hina-file-download-btn" href="${escapeHtml(downloadUrl)}" title="Download" download="${escapeHtml(label)}">
                    <i class="fa-solid fa-download"></i><span>download</span>
                </a>
            </div>
        </div>`;
    }

    // ------------------------------------------------------------
    // File-card modal — reuses the same highlightToLines()/
    // splitHighlightedHtml() pipeline as inline code fences, just
    // rendered full-screen with its own copy button, opened by the
    // hina-file-card's View button.
    // ------------------------------------------------------------
    let hinaFileModalEl = null;

    function ensureHinaFileModal() {
        if (hinaFileModalEl) return hinaFileModalEl;
        const el = document.createElement('div');
        el.className = 'hina-file-modal hidden';
        el.innerHTML = `
            <div class="hina-file-modal-backdrop"></div>
            <div class="hina-file-modal-panel">
                <div class="hina-file-modal-head">
                    <span class="hina-file-modal-name"></span>
                    <div class="hina-file-modal-actions">
                        <button type="button" class="code-btn hina-file-modal-copy" title="Copy code">
                            <i class="fa-solid fa-copy"></i><span>copy</span>
                        </button>
                        <a class="code-btn hina-file-modal-download" title="Download" download>
                            <i class="fa-solid fa-download"></i><span>download</span>
                        </a>
                        <button type="button" class="code-btn hina-file-modal-close" title="Close">
                            <i class="fa-solid fa-xmark"></i>
                        </button>
                    </div>
                </div>
                <div class="hina-file-modal-body"></div>
            </div>`;
        document.body.appendChild(el);

        const close = () => el.classList.add('hidden');
        el.querySelector('.hina-file-modal-backdrop').addEventListener('click', close);
        el.querySelector('.hina-file-modal-close').addEventListener('click', close);
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !el.classList.contains('hidden')) close();
        });

        hinaFileModalEl = el;
        return el;
    }

    async function openHinaFileModal(card) {
        const viewUrl = card.dataset.viewUrl;
        const downloadUrl = card.dataset.downloadUrl;
        const filename = card.dataset.filename;
        const ext = card.dataset.ext;

        const modal = ensureHinaFileModal();
        const body = modal.querySelector('.hina-file-modal-body');
        modal.querySelector('.hina-file-modal-name').textContent = filename;
        const dl = modal.querySelector('.hina-file-modal-download');
        dl.href = downloadUrl;
        dl.setAttribute('download', filename);
        body.innerHTML = '<div class="hina-file-modal-loading"><i class="fa-solid fa-spinner fa-spin"></i> Loading…</div>';
        modal.classList.remove('hidden');

        let raw;
        try {
            const resp = await fetch(viewUrl);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            raw = await resp.text();
        } catch (err) {
            body.innerHTML = `<div class="hina-file-modal-error"><i class="fa-solid fa-triangle-exclamation"></i> Couldn't load file: ${escapeHtml(err.message)}</div>`;
            return;
        }

        const lang = FILE_EXT_LANG[ext] || '';
        body.innerHTML = buildCodeCanvas(lang, raw);
        wireCodeCanvasButtons(body);

        const copyBtn = modal.querySelector('.hina-file-modal-copy');
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(raw).then(() => {
                const original = copyBtn.innerHTML;
                copyBtn.innerHTML = '<i class="fa-solid fa-check"></i><span>copied</span>';
                setTimeout(() => { copyBtn.innerHTML = original; }, 1200);
            });
        };
    }

    function wireHinaFileCards(root) {
        root.querySelectorAll('.hina-file-view-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const card = document.getElementById(btn.dataset.target);
                if (card) openHinaFileModal(card);
            });
        });
    }

    // Escapes plain text while swapping any bare URL inside it for
    // a link chip. Use this ANYWHERE raw text is about to hit the
    // DOM instead of a plain escapeHtml() call, so links never
    // render as dumb underlined text strings again.
    function linkifyEscaped(text) {
        if (typeof text !== 'string' || !text) return escapeHtml(text || '');
        let out = '';
        let last = 0;
        let m;
        URL_RE.lastIndex = 0;
        while ((m = URL_RE.exec(text)) !== null) {
            out += escapeHtml(text.slice(last, m.index));
            const rawMatch = m[0];
            const trimmedUrl = stripTrailingPunct(rawMatch);
            const trailing = rawMatch.slice(trimmedUrl.length);
            const fileCard = buildHinaFileCardIfApplicable(trimmedUrl);
            const videoEmbed = fileCard ? null : buildVideoEmbedIfApplicable(trimmedUrl);
            out += fileCard || videoEmbed || buildInlineLinkChip(trimmedUrl);
            out += escapeHtml(trailing);
            last = m.index + rawMatch.length;
        }
        out += escapeHtml(text.slice(last));
        return out;
    }

    function isNearBottom() {
        return ui.chat.scrollHeight - ui.chat.scrollTop - ui.chat.clientHeight < 120;
    }
    function scrollToBottom(force) {
        if (force || isNearBottom()) ui.chat.scrollTop = ui.chat.scrollHeight;
    }
    ui.chat.addEventListener('scroll', () => {
        ui.scrollBtn.classList.toggle('hidden', isNearBottom());
    });
    ui.scrollBtn.addEventListener('click', () => scrollToBottom(true));

    function hideEmptyState() {
        if (ui.emptyState) { ui.emptyState.remove(); ui.emptyState = null; }
    }

    // ------------------------------------------------------------
    // Code canvas — highlights the WHOLE block once, then splits
    // the highlighted HTML into per-line rows while keeping any
    // span that crosses a line boundary correctly closed/reopened.
    // This is what actually fixes "code loses its newlines": the
    // old build applied a single global `\n -> <br>` regex across
    // the entire message AFTER code was already inlined, and then
    // handed the code element to hljs.highlightElement(), which
    // re-reads .textContent — where <br> tags contribute nothing —
    // collapsing the whole block back to one line. We never let
    // hljs touch the DOM after insertion, and we never run that
    // global replace over code content.
    // ------------------------------------------------------------
    function splitHighlightedHtml(html) {
        const lines = [];
        const openTags = [];
        let current = '';
        let i = 0;
        while (i < html.length) {
            const ch = html[i];
            if (ch === '<') {
                const end = html.indexOf('>', i);
                if (end === -1) { current += html.slice(i); break; }
                const tag = html.slice(i, end + 1);
                current += tag;
                if (tag.startsWith('</')) openTags.pop();
                else if (!tag.endsWith('/>')) openTags.push(tag);
                i = end + 1;
                continue;
            }
            if (ch === '\n') {
                let closer = '';
                for (let k = openTags.length - 1; k >= 0; k--) closer += '</span>';
                lines.push(current + closer);
                current = openTags.join('');
                i++;
                continue;
            }
            current += ch;
            i++;
        }
        lines.push(current);
        return lines;
    }

    function highlightToLines(code, lang) {
        let html;
        try {
            if (window.hljs && lang && hljs.getLanguage(lang)) {
                html = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
            } else if (window.hljs) {
                html = hljs.highlightAuto(code).value;
            } else {
                html = escapeHtml(code);
            }
        } catch (err) {
            html = escapeHtml(code);
        }
        return splitHighlightedHtml(html);
    }

    let codeBlockCounter = 0;
    function buildCodeCanvas(lang, code) {
        const lines = highlightToLines(code, (lang || '').toLowerCase());
        const rows = lines.map((lineHtml, idx) =>
            `<tr><td class="ln">${idx + 1}</td><td class="lc">${lineHtml || ' '}</td></tr>`
        ).join('');
        const codeId = `code-${Date.now()}-${codeBlockCounter++}`;
        return `<div class="code-canvas wrap" data-code-id="${codeId}">
            <div class="code-canvas-header">
                <span class="code-lang">${escapeHtml(lang || 'text')}</span>
                <div class="code-actions">
                    <button type="button" class="code-btn wrap-toggle active" data-target="${codeId}" title="Toggle line wrapping">
                        <i class="fa-solid fa-text-width"></i><span>wrap</span>
                    </button>
                    <button type="button" class="code-btn copy-btn" data-target="${codeId}" title="Copy code">
                        <i class="fa-solid fa-copy"></i><span>copy</span>
                    </button>
                </div>
            </div>
            <div class="code-body">
                <table class="code-table" id="${codeId}" data-raw="${encodeURIComponent(code)}">${rows}</table>
            </div>
        </div>`;
    }

    // ------------------------------------------------------------
    // Raw-code auto-fence — for models that never emit ``` at all
    // and just dump code mixed straight into prose. Runs once,
    // before the real fence regex below, and only touches text
    // that (a) already has zero fences and (b) contains a chunk
    // that scores as code. Everything else in the pipeline is
    // unaware this ran: it just sees ``` fences that "were already
    // there". A well-behaved model that already emits fences never
    // even reaches this scoring path (see the guard at the top).
    // ------------------------------------------------------------
    const CODE_KEYWORDS_RE = /\b(def|function|class\s+\w+|import\s|from\s+\w+\s+import|const\s|let\s|var\s|return\b|#include|public\s+static|SELECT\s+.+\s+FROM|export\s+(default\s+)?|async\s+function|=>|console\.log|System\.out|print\()/;

    function codeLikelihoodScore(block) {
        const lines = block.split('\n').filter(l => l.trim() !== '');
        if (lines.length === 0) return 0;

        const len = block.length;
        const symbolChars = (block.match(/[{}();=<>\[\]:|&]/g) || []).length;
        const symbolRatio = symbolChars / Math.max(len, 1);

        const indentLines = lines.filter(l => /^(\s{2,}|\t)/.test(l)).length;
        const indentRatio = indentLines / lines.length;

        const kwHits = (block.match(new RegExp(CODE_KEYWORDS_RE, 'g')) || []).length;

        const words = (block.toLowerCase().match(/[a-z]+/g)) || [];
        const stopwords = new Set(['the','is','a','an','and','or','of','to','in','on','for','with','this','that','it','as','be','are']);
        const stopRatio = words.length ? words.filter(w => stopwords.has(w)).length / words.length : 1;

        const opens = (block.match(/[{(\[]/g) || []).length;
        const closes = (block.match(/[)}\]]/g) || []).length;
        const balanceBonus = opens > 0 && Math.abs(opens - closes) <= 1 ? 1 : 0;

        // A prose sentence ending in normal punctuation followed by
        // a capital letter is a strong "this is NOT code" signal.
        const sentenceLike = (block.match(/[a-z]\.\s+[A-Z]/g) || []).length;

        return symbolRatio * 3
            + indentRatio * 2
            + Math.min(kwHits, 5) * 0.6
            + balanceBonus
            - stopRatio * 2
            - sentenceLike * 0.8;
    }

    function guessLang(block) {
        if (/^\s*(from\s+\w+\s+import|import\s+\w+|def\s+\w+\(|print\()/m.test(block)) return 'python';
        if (/\bconsole\.log\(|=>|const\s+\w+\s*=|let\s+\w+\s*=/.test(block)) return 'javascript';
        if (/<\/?[a-z][\s\S]*>/i.test(block) && /<html|<div|<body|<span/i.test(block)) return 'html';
        if (/^\s*(public|private)\s+(static\s+)?(class|void|int|String)\b/m.test(block)) return 'java';
        if (/^\s*SELECT\s+.+\s+FROM\s+/im.test(block)) return 'sql';
        if (/^\s*#include\s*</m.test(block)) return 'cpp';
        return '';
    }

    function autoFenceRawCode(rawText) {
        if (typeof rawText !== 'string' || rawText.indexOf('```') !== -1) return rawText;

        // Split on blank-line boundaries so we can fence just the
        // code-looking chunks and leave surrounding prose alone.
        const blocks = rawText.split(/\n{2,}/);
        let touchedAny = false;

        const out = blocks.map(block => {
            if (block.trim() === '') return block;
            // Require a couple of lines minimum — single short lines
            // are too ambiguous to safely auto-canvas.
            if (block.split('\n').length < 2 && block.length < 40) return block;

            const score = codeLikelihoodScore(block);
            if (score >= 1.4) {
                touchedAny = true;
                const lang = guessLang(block);
                return '```' + lang + '\n' + block.replace(/\n$/, '') + '\n```';
            }
            return block;
        });

        return touchedAny ? out.join('\n\n') : rawText;
    }

    // ------------------------------------------------------------
    // Markup renderer.
    //   ```lang\ncode\n```   -> code canvas (line numbers, wrap toggle, copy)
    //   # / ## / ###          -> headings
    //   - item / * item        -> bullet list
    //   1. item                 -> numbered list
    //   > quote                  -> blockquote
    //   **text** or *text*        -> bold
    //   %text%                      -> blue highlight
    //   `text`                        -> inline code
    //
    // Code is extracted first and re-inserted after everything else
    // has run, so markup characters inside code (e.g. `Node*`, `a % b`,
    // `# comment`) are never touched.
    //
    // This is deliberately a real block parser (line-by-line, tracking
    // list/paragraph state) rather than one flat regex pass -- a flat
    // pass on inline-only rules is exactly what let raw "- item" and
    // "*emphasis whole sentence*" leak through as literal characters
    // instead of rendering, which is what we're fixing here.
    // ------------------------------------------------------------
    function renderInline(s) {
        s = linkifyEscaped(s);
        s = s.replace(/`([^`\n]+?)`/g, '<code>$1</code>');
        s = s.replace(/\*\*([^*]+?)\*\*/g, '<strong class="md-bold">$1</strong>');
        s = s.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<strong class="md-bold">$1</strong>');
        s = s.replace(/%([^%]+?)%/g, '<span class="md-highlight">$1</span>');
        return s;
    }

    // ------------------------------------------------------------
    // <think>...</think> — model reasoning / chain-of-thought.
    // Rendered as a small, quiet, collapsible panel with each token
    // fading in on a stagger so it reads like it's streaming in even
    // when the whole block landed in one payload. A trailing, still-
    // unclosed <think> (model is mid-thought) gets the live pulsing
    // "Thinking" state instead of the collapsed "Thought process" one.
    // ------------------------------------------------------------
    // ------------------------------------------------------------
    // <think>...</think> — model reasoning / chain-of-thought.
    //
    // Rendered as a small, quiet, collapsible panel — expanded with a
    // live pulse while the tag is still open, then a "Thought for
    // X.Xs" pill that auto-collapses once it closes (same shape as
    // Claude/ChatGPT's reasoning UI).
    //
    // `stableLen` is how many characters of this block's content were
    // ALREADY on screen as of the previous render. Only the new tail
    // beyond that point gets the token-fade-in treatment — without
    // this, a full re-render on every streaming tick would replay the
    // fade-in on text that's already visible, which reads as flicker
    // instead of streaming. When ctx isn't supplied (e.g. loading a
    // finished message from history) stableLen defaults to "all of
    // it", so nothing animates and nothing flickers.
    // ------------------------------------------------------------
    function buildThinkBlock(rawContent, isOpen, stableLen, elapsedSeconds, expanded) {
        const content = rawContent.replace(/^\n+/, '').replace(/\n+$/, '');
        const label = isOpen ? 'Thinking' : (elapsedSeconds != null ? `Thought for ${elapsedSeconds.toFixed(1)}s` : 'Thought process');
        const openClass = expanded ? ' think-open' : '';
        const liveClass = isOpen ? ' think-live' : '';

        if (!content.trim()) {
            if (!isOpen) return '';
            return `<div class="think-block think-open think-live">
                        <button type="button" class="think-head" data-think-toggle>
                            <i class="fa-solid fa-brain think-icon"></i>
                            <span class="think-label">${label}</span>
                            <span class="thinking-dots"><span></span><span></span><span></span></span>
                            <i class="fa-solid fa-chevron-down think-chevron"></i>
                        </button>
                        <div class="think-body-wrap"><div class="think-body"></div></div>
                   </div>`;
        }

        const safeStableLen = Math.max(0, Math.min(content.length, stableLen == null ? content.length : stableLen));
        const already = content.slice(0, safeStableLen);
        const fresh = content.slice(safeStableLen);

        const staticHtml = already ? linkifyEscaped(already).replace(/\n/g, '<br>') : '';

        const STEP = 14, MAX_ANIMATED = 240;
        let delay = 0, animated = 0;
        const freshHtml = fresh.split(/(\s+)/).map(part => {
            if (!part || !part.trim()) return part.replace(/\n/g, '<br>');
            let out;
            if (animated < MAX_ANIMATED) {
                out = `<span class="think-tok" style="animation-delay:${delay}ms">${linkifyEscaped(part)}</span>`;
                delay += STEP;
                animated++;
            } else {
                out = linkifyEscaped(part);
            }
            return out;
        }).join('');

        return `<div class="think-block${openClass}${liveClass}">
            <button type="button" class="think-head" data-think-toggle>
                <i class="fa-solid fa-brain think-icon"></i>
                <span class="think-label">${label}</span>
                ${isOpen ? '<span class="thinking-dots"><span></span><span></span><span></span></span>' : ''}
                <i class="fa-solid fa-chevron-down think-chevron"></i>
            </button>
            <div class="think-body-wrap"><div class="think-body">${staticHtml}${freshHtml}</div></div>
        </div>`;
    }

    function wireThinkBlocks(root) {
        root.querySelectorAll('[data-think-toggle]').forEach(btn => {
            btn.addEventListener('click', () => {
                btn.closest('.think-block').classList.toggle('think-open');
            });
        });
        // Keep the reasoning panel scrolled to its latest line while
        // it's live/expanded, so newly streamed-in text stays in view.
        root.querySelectorAll('.think-block.think-open .think-body-wrap').forEach(w => {
            w.scrollTop = w.scrollHeight;
        });
    }

    // Splits raw text into (a) the text with each <think>...</think> —
    // or a trailing, still-unclosed <think> — swapped for a numbered
    // marker, and (b) the ordered list of {inner, open} block contents
    // those markers stand in for. Used identically by renderMarkup and
    // by the streaming bookkeeping below so block order/identity stays
    // consistent frame to frame.
    function splitThinkBlocks(rawText) {
        const blocks = [];
        let text = rawText;

        // Case-insensitive throughout: backends inconsistently emit
        // <think>, <THINK>, <Think>, etc. Matching only the lowercase
        // form let anything else through as literal, unparsed text —
        // the exact bug behind raw "<THINK>...</THINK>" showing up in
        // the chat. We search on a lowercased copy to find indices,
        // then slice the ORIGINAL text so casing inside the reasoning
        // content itself stays untouched.
        while (true) {
            const l = text.toLowerCase();
            const openIdx = l.indexOf('<think>');
            if (openIdx === -1) break;
            const closeIdx = l.lastIndexOf('</think>');
            if (closeIdx === -1 || closeIdx < openIdx + 7) break; // no valid close after this open
            const inner = text.slice(openIdx + 7, closeIdx);
            blocks.push({ inner, open: false });
            const marker = `\n\n\u0001TH${blocks.length - 1}\u0001\n\n`;
            text = text.slice(0, openIdx) + marker + text.slice(closeIdx + 8);
        }

        text = text.replace(/<think>([\s\S]*)$/i, (match, inner) => {
            blocks.push({ inner, open: true });
            return `\n\n\u0001TH${blocks.length - 1}\u0001\n\n`;
        });
        return { text, blocks };
    }

    function renderMarkup(rawText, ctx) {
        rawText = autoFenceRawCode(rawText);

        // Pull <think> blocks out before any paragraph/list/heading
        // parsing touches the text, same marker-swap trick used for
        // fenced code below.
        const { text: textAfterThink, blocks } = splitThinkBlocks(rawText);

        const thinkBlocks = blocks.map((b, i) => {
            let stableLen = null, elapsedSeconds = null, expanded = !b.open;
            if (ctx) {
                if (!ctx.thinkMeta) ctx.thinkMeta = [];
                let meta = ctx.thinkMeta[i];
                if (!meta) { meta = { startedAt: Date.now(), closedAt: null, elapsed: null }; ctx.thinkMeta[i] = meta; }
                stableLen = meta.stableLen || 0;
                if (!b.open && meta.elapsed === null) meta.elapsed = (Date.now() - meta.startedAt) / 1000;
                elapsedSeconds = meta.elapsed;
                if (b.open) {
                    expanded = true;
                } else {
                    if (!meta.closedAt) meta.closedAt = Date.now();
                    expanded = (Date.now() - meta.closedAt) < 1100; // brief look-back before auto-collapsing
                }
                meta.stableLen = b.inner.length; // commit for next frame's diff
            }
            const marker = `\u0001TH${i}\u0001`;
            return { marker, html: buildThinkBlock(b.inner, b.open, stableLen, elapsedSeconds, expanded) };
        });

        const codeBlocks = [];
        let text = textAfterThink.replace(/```(\w+)?\n?([\s\S]*?)```/g, (match, lang, code) => {
            const marker = `\u0001CB${codeBlocks.length}\u0001`;
            codeBlocks.push({ marker, html: buildCodeCanvas(lang, code.replace(/\n$/, '')) });
            return marker;
        });

        const lines = text.split('\n');
        let html = '';
        let para = [];
        let list = null; // { type: 'ul'|'ol', items: [] }

        const flushPara = () => {
            if (para.length) {
                const joined = para.join(' ').trim();
                const squished = trySquishedTable(joined);
                if (squished) {
                    html += squished;
                    para = [];
                    return;
                }
                const soleVideo = LOCAL_VIDEO_PATH_RE.test(joined) ? buildVideoEmbedIfApplicable(joined) : null;
                html += soleVideo ? soleVideo : `<p>${renderInline(joined)}</p>`;
                para = [];
            }
        };
        const flushList = () => {
            if (list && list.items.length) {
                const tag = list.type;
                html += `<${tag} class="md-list">${list.items.map(it => `<li>${renderInline(it)}</li>`).join('')}</${tag}>`;
            }
            list = null;
        };

        // ------------------------------------------------------------
        // Markdown pipe tables
        // ------------------------------------------------------------
        // A table is: a header row "| a | b |", a separator row made of
        // only -, :, |, and whitespace ("|---|:--:|"), then 1+ data rows.
        // Without this, table lines used to fall through to the plain
        // paragraph branch, where flushPara() joins every line with a
        // single space — collapsing the whole table into one unreadable
        // run of "| a | b | | c | d |" text (what was happening before).
        const TABLE_SEP_RE = /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$/;
        const looksLikeTableRow = (l) => /\|/.test(l);
        const splitTableRow = (l) => {
            let s = l.trim();
            if (s.startsWith('|')) s = s.slice(1);
            if (s.endsWith('|')) s = s.slice(0, -1);
            return s.split('|').map(c => c.trim());
        };
        const buildTable = (headerCells, aligns, bodyRows) => {
            const alignStyle = (i) => {
                const a = aligns[i];
                if (a === 'center') return ' style="text-align:center"';
                if (a === 'right') return ' style="text-align:right"';
                return '';
            };
            const thead = `<tr>${headerCells.map((c, i) => `<th${alignStyle(i)}>${renderInline(c)}</th>`).join('')}</tr>`;
            const tbody = bodyRows.map(row => `<tr>${headerCells.map((_, i) =>
                `<td${alignStyle(i)}>${renderInline(row[i] !== undefined ? row[i] : '')}</td>`).join('')}</tr>`).join('');
            return `<div class="md-table-wrap"><table class="md-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
        };
        // Shared by both the normal (one-row-per-line) path and the
        // squished-single-line fallback below: given an array of row
        // strings where rowLines[1] is the separator, build the table.
        const buildTableFromRowLines = (rowLines) => {
            if (rowLines.length < 2 || !TABLE_SEP_RE.test(rowLines[1])) return null;
            const headerCells = splitTableRow(rowLines[0]);
            const sepCells = splitTableRow(rowLines[1]);
            const aligns = sepCells.map(c => {
                const left = c.startsWith(':'), right = c.endsWith(':');
                if (left && right) return 'center';
                if (right) return 'right';
                if (left) return 'left';
                return '';
            });
            const bodyRows = rowLines.slice(2).filter(r => r.trim()).map(splitTableRow);
            return buildTable(headerCells, aligns, bodyRows);
        };
        // Fallback: some model output arrives as ONE paragraph line with
        // every table row concatenated by spaces instead of newlines --
        // e.g. "| A | B | |---|---| | 1 | 2 | | 3 | 4 |" -- because the
        // newlines between rows got collapsed upstream. Row boundaries in
        // that shape are marked by "| |" (a cell-close immediately
        // followed by a cell-open), so re-inserting a break there recovers
        // the original rows before handing off to the normal table logic.
        const trySquishedTable = (joined) => {
            const s = joined.trim();
            if ((s.match(/\|/g) || []).length < 6) return null;
            if (!/\|\s*[-: ]{3,}\s*\|/.test(s)) return null;
            const rowLines = s.split(/\|\s*\|/).map((chunk, i, arr) => {
                let piece = chunk.trim();
                if (i > 0) piece = '|' + piece;
                if (i < arr.length - 1) piece = piece + '|';
                return piece;
            });
            return buildTableFromRowLines(rowLines);
        };

        for (let li = 0; li < lines.length; li++) {
            const rawLine = lines[li];
            const line = rawLine.replace(/\s+$/, '');

            if (!line.trim()) { flushPara(); flushList(); continue; }

            // Code-block marker line -- flush current block context and
            // drop it straight into the html stream as-is.
            if (/^\u0001CB\d+\u0001$/.test(line.trim())) {
                flushPara(); flushList();
                html += line.trim();
                continue;
            }

            // Table: current line + next line look like a header/separator
            // pair -> consume rows until a blank line or a non-pipe line.
            if (looksLikeTableRow(line) && li + 1 < lines.length && TABLE_SEP_RE.test(lines[li + 1])) {
                flushPara(); flushList();
                let j = li + 2;
                const rowLines = [line, lines[li + 1]];
                while (j < lines.length && lines[j].trim() && looksLikeTableRow(lines[j]) && !/^\u0001CB\d+\u0001$/.test(lines[j].trim())) {
                    rowLines.push(lines[j]);
                    j++;
                }
                const tableHtml = buildTableFromRowLines(rowLines);
                html += tableHtml || `<p>${renderInline(line)}</p>`;
                li = j - 1;
                continue;
            }

            const heading = line.match(/^(#{1,4})\s+(.*)$/);
            if (heading) {
                flushPara(); flushList();
                const level = Math.min(heading[1].length + 2, 6); // # -> h3, ## -> h4, etc (keeps chat-scale headings)
                html += `<h${level} class="md-heading">${renderInline(heading[2].trim())}</h${level}>`;
                continue;
            }

            const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
            if (bullet) {
                flushPara();
                if (!list || list.type !== 'ul') { flushList(); list = { type: 'ul', items: [] }; }
                list.items.push(bullet[1].trim());
                continue;
            }

            const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
            if (numbered) {
                flushPara();
                if (!list || list.type !== 'ol') { flushList(); list = { type: 'ol', items: [] }; }
                list.items.push(numbered[1].trim());
                continue;
            }

            const quote = line.match(/^\s*>\s?(.*)$/);
            if (quote) {
                flushPara(); flushList();
                html += `<blockquote class="md-quote">${renderInline(quote[1].trim())}</blockquote>`;
                continue;
            }

            flushList();
            para.push(line.trim());
        }
        flushPara();
        flushList();

        codeBlocks.forEach(cb => {
            const re = new RegExp(`<p>\\s*${cb.marker}\\s*</p>|${cb.marker}`, 'g');
            html = html.replace(re, cb.html);
        });

        thinkBlocks.forEach(tb => {
            const re = new RegExp(`<p>\\s*${tb.marker}\\s*</p>|${tb.marker}`, 'g');
            html = html.replace(re, tb.html);
        });

        return html || `<p>${renderInline(text)}</p>`;
    }

    function wireCodeCanvasButtons(root) {
        wireHinaFileCards(root);
        root.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const table = document.getElementById(btn.dataset.target);
                if (!table) return;
                const raw = decodeURIComponent(table.dataset.raw || '');
                navigator.clipboard.writeText(raw).then(() => {
                    const original = btn.innerHTML;
                    btn.innerHTML = '<i class="fa-solid fa-check"></i><span>copied</span>';
                    setTimeout(() => { btn.innerHTML = original; }, 1200);
                });
            });
        });
        root.querySelectorAll('.wrap-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const canvas = btn.closest('.code-canvas');
                canvas.classList.toggle('wrap');
                btn.classList.toggle('active');
            });
        });
    }

    // ------------------------------------------------------------
    // Inline control-JSON filter
    // ------------------------------------------------------------
    // "data.text" isn't necessarily written by our own backend —
    // it can come straight from an LLM, or from an MCP tool result
    // that passed back through the model. Either of those can end
    // up mixing a JSON control block into what's supposed to be
    // plain prose for the user (by accident, or because something
    // upstream got confused/tricked). We don't want that JSON ever
    // rendered as literal text, and we don't want to just guess at
    // stripping any "{...}" either, since models legitimately print
    // JSON all the time (code answers, API examples, etc.) and a
    // bare-brace heuristic would eat those.
    //
    // Convention: a control block meant to be pulled out of free
    // text must be wrapped in double tildes: ~~{...}~~ or ~~[...]~~
    // Content inside ~~ ~~ is only ever touched if it BOTH looks
    // like a JSON object/array AND actually parses — anything else
    // inside ~~ ~~ is left byte-for-byte untouched.
    //
    // This is a rough display-layer filter, not a security boundary.
    // Anything extracted is routed back through sanitizePayload()'s
    // narrow whitelist (via processPayload), the exact same path a
    // normal backend-sent payload takes — it's never given any more
    // trust than that.
    // Some MCP tools (web_search_mcp here) hand back a Python dict's
    // str() representation instead of real JSON — single-quoted
    // strings, True/False/None instead of true/false/null. That's
    // not valid JSON so a plain JSON.parse rejects it. This walks the
    // string character-by-character (respecting whichever quote —
    // ' or " — actually opened each string, since Python's repr
    // switches per-string to avoid escaping) and rewrites it into
    // real JSON. If anything about it doesn't fit this pattern, it
    // throws and the caller falls back to leaving the text untouched.
    function pyLiteralToJson(src) {
        let out = '';
        let i = 0;
        const n = src.length;
        while (i < n) {
            const ch = src[i];
            if (ch === "'" || ch === '"') {
                const quote = ch;
                let j = i + 1;
                let body = '';
                while (j < n && src[j] !== quote) {
                    if (src[j] === '\\' && j + 1 < n) { body += src[j] + src[j + 1]; j += 2; continue; }
                    body += src[j]; j++;
                }
                if (j >= n) throw new Error('unterminated string');
                let jsonBody = '';
                for (let k = 0; k < body.length; k++) {
                    const c = body[k];
                    if (c === '\\' && k + 1 < body.length) {
                        const c2 = body[k + 1];
                        if (c2 === "'") { jsonBody += "'"; k++; continue; }      // \' -> '
                        if (c2 === '"') { jsonBody += '\\"'; k++; continue; }    // keep escaped "
                        jsonBody += c + c2; k++; continue;                       // \n \t \\ etc pass through
                    }
                    if (c === '"') { jsonBody += '\\"'; continue; }              // bare " needs escaping now
                    jsonBody += c;
                }
                out += '"' + jsonBody + '"';
                i = j + 1;
                continue;
            }
            if (/[A-Za-z_]/.test(ch)) {
                let j = i;
                while (j < n && /[A-Za-z_]/.test(src[j])) j++;
                const word = src.slice(i, j);
                if (word === 'True') out += 'true';
                else if (word === 'False') out += 'false';
                else if (word === 'None') out += 'null';
                else throw new Error('unexpected bareword: ' + word); // don't guess on unknown identifiers
                i = j;
                continue;
            }
            out += ch;
            i++;
        }
        return out;
    }

    function extractInlineControlBlocks(rawText) {
        if (typeof rawText !== 'string' || rawText.indexOf('~~') === -1) {
            return { clean: rawText, blocks: [] };
        }
        const blocks = [];
        const clean = rawText.replace(/~~([\s\S]*?)~~/g, (match, inner) => {
            const trimmed = inner.trim();
            const looksLikeJson =
                (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
                (trimmed.startsWith('[') && trimmed.endsWith(']'));
            if (!looksLikeJson) return match; // not JSON-shaped -> leave verbatim

            let parsed;
            try {
                parsed = JSON.parse(trimmed);
            } catch (e) {
                // Not valid JSON as-is — try treating it as a Python
                // dict/list literal (single quotes, True/False/None)
                // before giving up, since that's what some MCP tools emit.
                try { parsed = JSON.parse(pyLiteralToJson(trimmed)); }
                catch (e2) { return match; } // still no good -> leave verbatim, don't guess
            }

            (Array.isArray(parsed) ? parsed : [parsed]).forEach(item => {
                if (item && typeof item === 'object') blocks.push(item);
            });
            return ''; // strip the wrapped block out of the visible text
        });
        return { clean: clean.trim(), blocks };
    }

    // ------------------------------------------------------------
    // Search-results card — when the backend hands back a raw
    // search/AI-overview payload (query, ai_overview_text, ai_links,
    // organic_results, status) as a JSON string, render it as a
    // proper result card instead of dumping raw JSON text.
    // ------------------------------------------------------------
    function tryDetectSearchPayload(rawText) {
        if (typeof rawText !== 'string') return null;
        const trimmed = rawText.trim();
        if (!trimmed.startsWith('{')) return null;
        let obj;
        try { obj = JSON.parse(trimmed); } catch (e) { return null; }
        if (obj && typeof obj === 'object' &&
            (Array.isArray(obj.ai_links) || Array.isArray(obj.organic_results))) {
            return obj;
        }
        return null;
    }

    // Strips bare citation badges ("BBC", "+2", "YouTube · BBC News")
    // that Google's AI Overview scrape leaves inline as their own
    // lines, so the overview reads as prose instead of noise.
    function cleanOverviewLines(raw) {
        return raw.split('\n').map(l => l.trim()).filter(l => {
            if (!l) return false;
            const words = l.split(/\s+/).filter(Boolean);
            const endsPunct = /[.!?:]$/.test(l);
            const looksLikeBadge = l.length <= 28 && words.length <= 4 && !endsPunct &&
                (/^\+\d+$/.test(l) || /^[A-Z][\w.&'· -]*$/.test(l));
            return !looksLikeBadge;
        });
    }

    function buildOverviewHtml(rawOverview) {
        // The overview text can itself contain a <think>...</think>
        // block (some backends route reasoning through the same field
        // as the summary). Pull it out and render it as a proper
        // collapsible think-block first, instead of letting the raw
        // tag leak into buildOverviewHtml's heading-detection heuristic
        // (which is exactly what turned "<THINK>" into a bolded fake
        // heading before).
        const { text: withoutThink, blocks } = splitThinkBlocks(rawOverview);
        const thinkHtml = blocks
            .map(b => buildThinkBlock(b.inner, b.open, null, null, false))
            .join('');
        const cleanOverview = withoutThink.replace(/\u0001TH\d+\u0001/g, '').trim();

        const lines = cleanOverviewLines(cleanOverview);
        let html = '', buf = [], list = [];
        const flushPara = () => { if (buf.length) { html += `<p>${renderInline(buf.join(' '))}</p>`; buf = []; } };
        const flushList = () => {
            if (list.length) html += `<ul class="md-list">${list.map(it => `<li>${renderInline(it)}</li>`).join('')}</ul>`;
            list = [];
        };
        for (let i = 0; i < lines.length; i++) {
            let l = lines[i];
            const next = lines[i + 1];

            const bullet = l.match(/^\s*[-*•]\s+(.*)$/);
            if (bullet) { flushPara(); list.push(bullet[1].trim()); continue; }
            flushList();

            // Strip stray leading/trailing single asterisks some scraped
            // overviews wrap whole sentences in (not real emphasis, just
            // scrape noise) before deciding if this line is a heading.
            const stripped = l.replace(/^\*+\s*/, '').replace(/\s*\*+$/, '');
            const words = stripped.split(/\s+/).filter(Boolean).length;
            const isHeading = words <= 6 && !/[.!?:]$/.test(stripped) && next && next.split(/\s+/).filter(Boolean).length >= 5;
            if (isHeading) { flushPara(); html += `<h4 class="search-overview-heading">${escapeHtml(stripped)}</h4>`; }
            else buf.push(stripped);
        }
        flushPara();
        flushList();
        return thinkHtml + html;
    }

    function buildLinkCard(url, title) {
        const safe = sanitizeUrl(url);
        if (!safe) return '';
        const host = hostnameOf(safe);
        const label = (title && title.trim()) ? title.trim() : host;
        return `<a class="search-link-card" href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">
            <img class="search-link-favicon" src="${faviconUrl(safe)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
            <div class="search-link-body">
                <div class="search-link-title">${escapeHtml(label)}</div>
                <div class="search-link-host"><i class="fa-solid fa-link"></i>${escapeHtml(host)}</div>
            </div>
            <i class="fa-solid fa-arrow-up-right-from-square search-link-go"></i>
        </a>`;
    }

    // Bing news-thumbnail URLs (what DuckDuckGo's image proxy wraps)
    // carry an explicit w=/h= size in the query string. Bumping those
    // up gets a materially sharper asset from the same endpoint
    // instead of the small default thumbnail — as close to "best
    // quality" as we can get without a real image-search API.
    function upscaleImageUrl(url) {
        try {
            const u = new URL(url);
            const inner = u.searchParams.get('u');
            if (inner) {
                const innerUrl = new URL(decodeURIComponent(inner));
                if (innerUrl.searchParams.has('w')) innerUrl.searchParams.set('w', '1200');
                if (innerUrl.searchParams.has('h')) innerUrl.searchParams.set('h', '1200');
                if (innerUrl.searchParams.has('pid')) innerUrl.searchParams.set('pid', 'Api');
                u.searchParams.set('u', encodeURIComponent(innerUrl.href));
            }
            return u.href;
        } catch (e) { return url; }
    }

    function buildImageGallery(imageLinks, sourceItems) {
        const safeImages = imageLinks.map(sanitizeUrl).filter(Boolean);
        if (!safeImages.length) return '';

        // Pair each image with the source link at the same position
        // (best-effort — DDG returns them in matching order) so a
        // click can jump straight to the article, not just the raw image.
        const cards = safeImages.map((raw, i) => {
            const hq = upscaleImageUrl(raw);
            const source = sourceItems[i] || null;
            const host = source ? hostnameOf(source.url) : '';
            return `<button type="button" class="gallery-thumb"
                data-full="${escapeHtml(hq)}"
                data-source="${source ? escapeHtml(source.url) : ''}"
                title="${escapeHtml(source && source.title ? source.title : 'Open image')}">
                <img src="${escapeHtml(raw)}" data-hq="${escapeHtml(hq)}" alt="" loading="lazy"
                     onerror="this.onerror=null;this.src=this.dataset.hq;">
                <span class="gallery-thumb-overlay">
                    <i class="fa-solid fa-up-right-and-down-left-from-center"></i>
                    ${host ? `<span class="gallery-thumb-host">${escapeHtml(host)}</span>` : ''}
                </span>
            </button>`;
        }).join('');

        return `<div class="search-links-heading"><i class="fa-solid fa-images"></i> Images <span class="search-links-count">${safeImages.length}</span></div>
        <div class="gallery-grid">${cards}</div>`;
    }

    // Lightbox: one shared overlay, reused for every gallery card.
    // Click backdrop/close to dismiss, click "visit source" to open
    // the original article in a new tab (or the raw image if none).
    let lightboxEl = null;
    function ensureLightbox() {
        if (lightboxEl) return lightboxEl;
        lightboxEl = document.createElement('div');
        lightboxEl.className = 'img-lightbox hidden';
        lightboxEl.innerHTML = `
            <div class="img-lightbox-backdrop"></div>
            <div class="img-lightbox-content">
                <button type="button" class="img-lightbox-close" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
                <img class="img-lightbox-img" src="" alt="">
                <a class="img-lightbox-visit" href="#" target="_blank" rel="noopener noreferrer">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i> Open source
                </a>
            </div>`;
        document.body.appendChild(lightboxEl);
        const close = () => lightboxEl.classList.add('hidden');
        lightboxEl.querySelector('.img-lightbox-backdrop').addEventListener('click', close);
        lightboxEl.querySelector('.img-lightbox-close').addEventListener('click', close);
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
        return lightboxEl;
    }
    function openLightbox(fullUrl, sourceUrl) {
        const box = ensureLightbox();
        const img = box.querySelector('.img-lightbox-img');
        const visit = box.querySelector('.img-lightbox-visit');
        img.src = fullUrl;
        visit.href = sourceUrl || fullUrl;
        box.classList.remove('hidden');
    }

    function wireGallery(root) {
        root.querySelectorAll('.gallery-thumb').forEach(btn => {
            btn.addEventListener('click', () => {
                openLightbox(btn.dataset.full, btn.dataset.source || null);
            });
        });
    }

    // ------------------------------------------------------------
    // Title/image-link cards — some MCP tools (e.g. get_nasa_image_
    // links) return a flat stream of small JSON objects, one per
    // result, each shaped like {"title": "...", "image_url": "..."}.
    // In raw form these show up wrapped in Python log noise
    // (CallToolResult(content=[TextContent(...)])) or just a run of
    // back-to-back JSON blobs — either way it reads as a mess. This
    // scans arbitrary text for that {title + image/url/link} shape
    // anywhere inside it (log wrapper and all), pulls out every
    // matching object regardless of how much noise surrounds them,
    // and hands back a clean list to render as cards.
    // ------------------------------------------------------------
    function extractJsonObjectStrings(rawText) {
        const objs = [];
        let depth = 0, start = -1, inStr = false, esc = false;
        for (let i = 0; i < rawText.length; i++) {
            const c = rawText[i];
            if (inStr) {
                if (esc) esc = false;
                else if (c === '\\') esc = true;
                else if (c === '"') inStr = false;
                continue;
            }
            if (c === '"') { inStr = true; continue; }
            if (c === '{') { if (depth === 0) start = i; depth++; }
            else if (c === '}') {
                depth = Math.max(0, depth - 1);
                if (depth === 0 && start !== -1) { objs.push(rawText.slice(start, i + 1)); start = -1; }
            }
        }
        return objs;
    }

    // Some tool/log output carries literal two-character "\n" / "\t"
    // sequences (from a Python repr) sitting between JSON tokens
    // rather than real whitespace bytes — invalid JSON as-is even
    // though the object is otherwise well-formed. Swapping those for
    // real whitespace fixes it without touching anything inside an
    // actual string value's own escapes (there's nothing to swap
    // if a string legitimately contains "\n").
    function normalizeLooseEscapes(s) {
        return s.replace(/\\n/g, '\n').replace(/\\t/g, ' ').replace(/\\r/g, '');
    }

    function tryDetectTitleLinkItems(rawText) {
        if (typeof rawText !== 'string' || !rawText.includes('{')) return null;
        const candidates = extractJsonObjectStrings(rawText);
        if (!candidates.length) return null;

        const items = [];
        candidates.forEach(str => {
            let obj = null;
            try { obj = JSON.parse(str); }
            catch (e) {
                try { obj = JSON.parse(normalizeLooseEscapes(str)); }
                catch (e2) {
                    try { obj = JSON.parse(pyLiteralToJson(str)); } catch (e3) { /* not JSON-ish, skip */ }
                }
            }
            if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return;

            const title = obj.title || obj.name || obj.label || obj.caption;
            const url = obj.image_url || obj.imageUrl || obj.url || obj.link || obj.href;
            if (typeof url !== 'string') return;
            const safeUrl = sanitizeUrl(url);
            if (!safeUrl) return;

            const isImage = /\.(png|jpe?g|gif|webp|avif|svg)(\?|~|$)/i.test(safeUrl) ||
                /image/i.test(String(obj.image_url || obj.imageUrl || ''));
            items.push({ title: title ? String(title) : '', url: safeUrl, isImage });
        });

        // Only worth a card grid once there's a real, uniform set —
        // one stray object shouldn't hijack normal prose that just
        // happens to contain a JSON-looking aside.
        return items.length >= 1 ? items : null;
    }

    function buildTitleLinkCards(items) {
        const cards = items.map(it => {
            if (it.isImage) {
                return `<a class="link-media-card" href="${escapeHtml(it.url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(it.title || 'Open image')}">
                    <div class="link-media-thumb">
                        <img src="${escapeHtml(it.url)}" alt="${escapeHtml(it.title || '')}" loading="lazy"
                             onerror="this.closest('.link-media-card').classList.add('link-media-broken')">
                    </div>
                    ${it.title ? `<div class="link-media-title">${escapeHtml(it.title)}</div>` : ''}
                    <i class="fa-solid fa-arrow-up-right-from-square link-media-go"></i>
                </a>`;
            }
            return buildLinkCard(it.url, it.title);
        }).filter(Boolean).join('');

        return `<div class="search-links-heading"><i class="fa-solid fa-images"></i> Results <span class="search-links-count">${items.length}</span></div>
        <div class="link-media-grid">${cards}</div>`;
    }

    function buildSearchResultsCard(data) {
        const query = typeof data.query === 'string' ? data.query : '';
        const overviewHtml = typeof data.ai_overview_text === 'string' ? buildOverviewHtml(data.ai_overview_text) : '';

        const seen = new Set();
        const items = [];
        (Array.isArray(data.organic_results) ? data.organic_results : []).forEach(r => {
            if (r && r.link && !seen.has(r.link)) { seen.add(r.link); items.push({ url: r.link, title: r.title }); }
        });
        (Array.isArray(data.ai_links) ? data.ai_links : []).forEach(u => {
            if (u && !seen.has(u)) { seen.add(u); items.push({ url: u, title: '' }); }
        });
        const linksHtml = items.map(it => buildLinkCard(it.url, it.title)).filter(Boolean).join('');

        const imageLinks = Array.isArray(data.image_links) ? data.image_links : [];
        const galleryHtml = buildImageGallery(imageLinks, items);

        return `<div class="search-card">
            <div class="search-card-head">
                <span class="search-card-badge"><i class="fa-solid fa-magnifying-glass"></i> Web results${query ? ` for "${escapeHtml(query)}"` : ''}</span>
            </div>
            ${overviewHtml ? `<div class="search-overview">${overviewHtml}</div>` : ''}
            ${galleryHtml}
            ${linksHtml ? `<div class="search-links-heading"><i class="fa-solid fa-layer-group"></i> Sources <span class="search-links-count">${items.length}</span></div>
            <div class="search-links-grid">${linksHtml}</div>` : ''}
        </div>`;
    }

    function renderInto(el, rawText, ctx) {
        // Defense in depth: processPayload() already strips ~~{...}~~
        // control blocks out of live WS text, but renderInto() is also
        // called directly (e.g. from loadHistory() on stored rows) so
        // it can't assume its input already went through that filter.
        // Any blocks found here are just discarded, not re-dispatched —
        // by the time something is being rendered directly, there's no
        // live turn/trace context left to usefully route them into.
        const { clean } = extractInlineControlBlocks(rawText);
        rawText = clean;

        const searchData = tryDetectSearchPayload(rawText);
        if (searchData) {
            el.innerHTML = buildSearchResultsCard(searchData);
            wireCodeCanvasButtons(el);
            wireGallery(el);
            wireThinkBlocks(el);
            return;
        }

        const titleLinkItems = tryDetectTitleLinkItems(rawText);
        if (titleLinkItems && titleLinkItems.length >= 2) {
            el.innerHTML = buildTitleLinkCards(titleLinkItems);
            wireCodeCanvasButtons(el);
            return;
        }

        el.innerHTML = renderMarkup(rawText, ctx);
        wireCodeCanvasButtons(el);
        wireThinkBlocks(el);
        if (ctx && ctx.streaming) {
            el.insertAdjacentHTML('beforeend', '<span class="stream-caret"></span>');
        }
    }

    // ------------------------------------------------------------
    // Structured UI cards — for payloads sent through the SDK's
    // send_ui_json(), which arrive as a real object/array in
    // `ui_data` rather than something we had to sniff out of text.
    //
    // Renderer choice: use `ui_type` if the backend gave one, else
    // auto-detect from the shape of `ui_data` (the same look the old
    // tryDetectSearchPayload() used). Anything we don't recognize
    // still gets a readable generic card instead of being dropped or
    // dumped as raw JSON.
    // ------------------------------------------------------------
    function detectUiKind(uiType, data) {
        if (uiType === 'search' || uiType === 'search_results') return 'search';
        if (uiType === 'astro' || uiType === 'astrophysics' || uiType === 'space') return 'astro';
        if (uiType === 'github') return 'github';
        if (uiType === 'file') return 'file';
        if (data && typeof data === 'object' &&
            (Array.isArray(data.organic_results) || Array.isArray(data.ai_links))) {
            return 'search';
        }
        if (data && typeof data === 'object' && typeof data.kind === 'string' &&
            /^(repo|repo_search|issue_|pr_|actions_runs|commits|branches|releases|file|code_search|notifications)/.test(data.kind)) {
            return 'github';
        }
        // Auto-detect code_mcp.py's file payload shape even if a
        // future caller forgets to set ui_type explicitly.
        if (data && typeof data === 'object' && !Array.isArray(data) &&
            typeof data.filename === 'string' && typeof data.view_url === 'string') {
            return 'file';
        }
        // list_files()-shaped payload: {file_count, files:[{filename, display_name}]}
        if (data && typeof data === 'object' && !Array.isArray(data) &&
            Array.isArray(data.files) && typeof data.file_count !== 'undefined') {
            return 'file_list';
        }
        return 'generic';
    }

    // A single generated-file payload from code_mcp.py's
    // send_ui_json(): {filename, display_name, view_url, download_url}.
    // Reuses the exact same hina-file-card markup/behavior (icon,
    // View -> code-canvas modal, Download -> save-as) that link-based
    // file cards already get from buildHinaFileCardIfApplicable(), so
    // structured file payloads look and behave identically instead of
    // falling back to the generic key/value "Data" dump.
    function buildFileUiCard(data) {
        if (!data || typeof data !== 'object') return buildGenericUiCard(data);
        const rawViewUrl = typeof data.view_url === 'string' ? data.view_url : '';
        // code_mcp.py sends a server-relative path (e.g.
        // "/download/hina/files/xxx.html"). buildHinaFileCardIfApplicable()
        // runs everything through sanitizeUrl(), which does `new URL(x)`
        // with no base — that throws on relative paths and returns null,
        // which used to silently fall back to the generic card. Resolve
        // against location.origin first so absolute-URL-only sanitizeUrl
        // still accepts it.
        let viewUrl = rawViewUrl;
        if (rawViewUrl && !/^https?:\/\//i.test(rawViewUrl)) {
            try { viewUrl = new URL(rawViewUrl, window.location.origin).href; } catch (e) { viewUrl = rawViewUrl; }
        }
        const card = buildHinaFileCardIfApplicable(viewUrl, data.display_name);
        if (card) return card;
        // view_url didn't match the expected /download/hina/files/... shape —
        // still show something useful instead of silently dropping it.
        return buildGenericUiCard(data);
    }

    // A list of generated files, e.g. code_mcp.py's list_files():
    // {file_count, files: [{filename, display_name}, ...]}. Rendered
    // as a compact file grid using display_name only — the raw hashed
    // filename (an opaque storage key, not something a user should
    // ever see) never reaches the DOM.
    function buildFileListUiCard(data) {
        const files = Array.isArray(data.files) ? data.files : [];
        if (!files.length) return buildGenericUiCard(data);

        const rows = files.map(f => {
            const label = (f && typeof f.display_name === 'string' && f.display_name.trim())
                ? f.display_name.trim()
                : (f && typeof f.filename === 'string' ? f.filename : 'file');
            const ext = fileExtOf(label);
            const iconClass = FILE_EXT_ICON[ext] || 'fa-file-lines';
            return `<div class="hina-file-card hina-file-card-compact">
                <div class="hina-file-icon"><i class="fa-solid ${iconClass}"></i></div>
                <div class="hina-file-info">
                    <div class="hina-file-name">${escapeHtml(label)}</div>
                    <div class="hina-file-sub">${ext ? escapeHtml(ext.toUpperCase()) + ' file' : 'File'}</div>
                </div>
            </div>`;
        }).join('');

        return `<div class="ui-card">
            <div class="ui-card-head">
                <span class="ui-card-badge"><i class="fa-solid fa-folder-open"></i> ${files.length} file${files.length === 1 ? '' : 's'}</span>
            </div>
            <div class="ui-card-body hina-file-grid">${rows}</div>
        </div>`;
    }

    function isPlainObject(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }

    // Recursively turns an arbitrary JSON value into readable HTML:
    // - array of primitives  -> chip row
    // - array of objects     -> stacked mini key/value cards
    // - object                -> key/value grid, values recursed
    // - primitive              -> escaped text (URLs auto-linked)
    // Depth-capped so a deeply nested or huge payload degrades to a
    // compact inline JSON string instead of ballooning the DOM.
    function buildGenericValue(value, depth) {
        if (value === null || value === undefined) return '<span class="ui-null">—</span>';

        if (Array.isArray(value)) {
            if (!value.length) return '<span class="ui-null">—</span>';
            if (depth >= 3) return `<span class="ui-json-raw">${escapeHtml(JSON.stringify(value))}</span>`;
            const allPrimitive = value.every(v => !v || typeof v !== 'object');
            if (allPrimitive) {
                return `<div class="ui-chip-row">${value.map(v => `<span class="ui-chip">${escapeHtml(String(v))}</span>`).join('')}</div>`;
            }
            return `<div class="ui-array-list">${value.map(item =>
                `<div class="ui-array-item">${buildGenericValue(item, depth + 1)}</div>`
            ).join('')}</div>`;
        }

        if (isPlainObject(value)) {
            if (depth >= 3) return `<span class="ui-json-raw">${escapeHtml(JSON.stringify(value))}</span>`;
            const rows = Object.entries(value).map(([k, v]) => `
                <div class="ui-kv-row">
                    <div class="ui-kv-key">${escapeHtml(String(k).replace(/_/g, ' '))}</div>
                    <div class="ui-kv-value">${buildGenericValue(v, depth + 1)}</div>
                </div>`).join('');
            return `<div class="ui-kv-grid">${rows}</div>`;
        }

        if (typeof value === 'string' && looksLikeBareUrl(value)) {
            return buildInlineLinkChip(value);
        }
        if (typeof value === 'string') return linkifyEscaped(value);
        return escapeHtml(String(value));
    }

    function buildGenericUiCard(data) {
        return `<div class="ui-card">
            <div class="ui-card-head">
                <span class="ui-card-badge"><i class="fa-solid fa-shapes"></i> Data</span>
            </div>
            <div class="ui-card-body">${buildGenericValue(data, 0)}</div>
        </div>`;
    }

    // ------------------------------------------------------------
    // Structured media-array cards — the STANDARD shape any tool can
    // send through send_ui_json: a flat list of
    //   { "title": "...", "media_url": "...", "media_type": "image" }
    // media_type is one of "image" | "video" | "audio" | anything else
    // (treated as a generic downloadable file). Older tools that still
    // send "image_url" instead of "media_url" keep working — that key
    // is just treated as media_type: "image".
    // Renders with the same gallery-thumb button markup as
    // buildImageGallery() so the shared lightbox/wireGallery wiring
    // picks images up for free; video/audio/file items get their own
    // inline tile. `size` lets callers (like the astro card) ask for
    // bigger tiles.
    // ------------------------------------------------------------
    function tryDetectMediaArray(data) {
        if (!Array.isArray(data) || !data.length) return null;
        const items = [];
        for (const obj of data) {
            if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null;
            const rawUrl = obj.media_url || obj.image_url || obj.imageUrl || obj.url || obj.link || obj.href;
            if (typeof rawUrl !== 'string') return null;
            const safeUrl = sanitizeUrl(rawUrl);
            if (!safeUrl) return null;

            const title = obj.title || obj.name || obj.label || obj.caption || '';

            let mediaType = typeof obj.media_type === 'string' ? obj.media_type.trim().toLowerCase() : '';
            if (!mediaType) {
                if (obj.image_url || obj.imageUrl) mediaType = 'image';
                else if (/\.(mp4|webm|mov|m4v)(\?|$)/i.test(safeUrl)) mediaType = 'video';
                else if (/\.(mp3|wav|ogg|m4a|flac)(\?|$)/i.test(safeUrl)) mediaType = 'audio';
                else if (/\.(png|jpe?g|gif|webp|avif|svg)(\?|$)/i.test(safeUrl)) mediaType = 'image';
                else mediaType = 'file';
            }
            items.push({ title: String(title), url: safeUrl, mediaType });
        }
        return items;
    }

    // The page can be served over HTTPS (e.g. an ngrok tunnel) while a
    // resolved media URL (googlevideo, etc.) came back as http://. The
    // browser auto-upgrades the request, but that upgraded connection
    // can still fail for a URL that wasn't actually issued/signed for
    // https — which shows up as a player that's visible but completely
    // silent, with no error the user can see. Upgrading the scheme
    // ourselves when the page itself is https at least gives the
    // upgraded URL the best chance, and the onerror handlers below
    // surface it plainly instead of failing silently if it still can't
    // connect.
    function preferHttps(url) {
        if (typeof url !== 'string') return url;
        if (window.location.protocol === 'https:' && url.startsWith('http://')) {
            return 'https://' + url.slice('http://'.length);
        }
        return url;
    }

    function buildMediaGridCard(items, opts) {
        const big = !!(opts && opts.big);
        const sizeClass = big ? ' gallery-thumb-lg' : '';
        const gridSizeClass = big ? ' gallery-grid-lg' : '';
        // Autoplay only makes sense for a single explicit "play this"
        // action (e.g. music_mcp.py's play_music) — never for a gallery
        // of several search-result clips, where auto-starting every one
        // at once would be chaos.
        const singleTrack = items.length === 1;

        const cards = items.map(it => {
            if (it.mediaType === 'image') {
                return `<button type="button" class="gallery-thumb${sizeClass}"
                    data-full="${escapeHtml(it.url)}"
                    data-source=""
                    title="${escapeHtml(it.title || 'Open image')}">
                    <img src="${escapeHtml(it.url)}" alt="${escapeHtml(it.title || '')}" loading="lazy"
                         onerror="this.closest('.gallery-thumb').classList.add('link-media-broken')">
                    <span class="gallery-thumb-overlay">
                        <i class="fa-solid fa-up-right-and-down-left-from-center"></i>
                        ${it.title ? `<span class="gallery-thumb-host">${escapeHtml(it.title)}</span>` : ''}
                    </span>
                </button>`;
            }
            if (it.mediaType === 'video') {
                const src = preferHttps(it.url);
                return `<div class="gallery-thumb gallery-media-tile${sizeClass}" title="${escapeHtml(it.title || 'Video')}">
                    <video src="${escapeHtml(src)}" controls preload="metadata"${singleTrack ? ' autoplay' : ''}
                        onerror="this.closest('.gallery-media-tile').classList.add('link-media-broken'); this.insertAdjacentHTML('afterend', '<div style=&quot;opacity:.7;font-size:.85em;margin-top:4px;&quot;>Playback failed — the source link may be unreachable or not HTTPS-compatible.</div>')"></video>
                    ${it.title ? `<span class="gallery-thumb-overlay"><span class="gallery-thumb-host">${escapeHtml(it.title)}</span></span>` : ''}
                </div>`;
            }
            if (it.mediaType === 'audio') {
                const src = preferHttps(it.url);
                return `<div class="gallery-thumb gallery-media-tile gallery-audio-tile${sizeClass}" title="${escapeHtml(it.title || 'Audio')}">
                    <i class="fa-solid fa-music gallery-audio-icon"></i>
                    <div class="gallery-audio-title">${escapeHtml(it.title || 'Audio clip')}</div>
                    <audio src="${escapeHtml(src)}" controls preload="auto"${singleTrack ? ' autoplay' : ''}
                        onerror="this.closest('.gallery-audio-tile').classList.add('link-media-broken'); this.insertAdjacentHTML('afterend', '<div style=&quot;opacity:.7;font-size:.85em;margin-top:4px;&quot;>Playback failed — the source link may be unreachable or not HTTPS-compatible.</div>')"></audio>
                </div>`;
            }
            // generic file / unknown type
            return buildLinkCard(it.url, it.title || 'Open file');
        }).join('');

        const icon = items.every(it => it.mediaType === 'image') ? 'fa-images'
                   : items.every(it => it.mediaType === 'video') ? 'fa-film'
                   : items.every(it => it.mediaType === 'audio') ? 'fa-music'
                   : 'fa-shapes';

        return `<div class="search-links-heading"><i class="fa-solid ${icon}"></i> Media <span class="search-links-count">${items.length}</span></div>
        <div class="gallery-grid${gridSizeClass}">${cards}</div>`;
    }

    function buildAstroCard(data) {
        // A flat array of {title, media_url, media_type} (or the older
        // {title, image_url}) — the standard shape any tool sends
        // through send_ui_json for pictures/video/audio — renders as a
        // large media grid instead of falling through to the generic
        // key/value renderer, which is what used to happen to arrays
        // here (Array.isArray === true but typeof is still 'object',
        // so it hit the object branch below and spread as {0:.., 1:..}).
        const mediaItems = tryDetectMediaArray(data);
        if (mediaItems) {
            return `<div class="astro-card">
                <div class="astro-card-head">
                    <span class="astro-card-badge"><i class="fa-solid fa-meteor"></i> Astrophysics</span>
                </div>
                <div class="astro-body">${buildMediaGridCard(mediaItems, { big: true })}</div>
            </div>`;
        }
        return buildAstroCardRest(data);
    }

    function buildAstroCardRest(data) {
        // Accept either plain text/markdown (most likely, since the MCP
        // isn't returning a fixed schema yet) or a structured object --
        // whichever it hands back, render it through the same sanitized
        // paths as everything else, just inside the space-themed shell.
        let body;
        if (typeof data === 'string') {
            body = `<div class="astro-body">${renderMarkup(data)}</div>`;
        } else if (data && typeof data === 'object') {
            const title = typeof data.title === 'string' ? data.title : '';
            const text = typeof data.summary === 'string' ? data.summary
                       : typeof data.text === 'string' ? data.text : '';
            const rest = { ...data };
            delete rest.title; delete rest.summary; delete rest.text;
            const restKeys = Object.keys(rest);
            body = `
                ${title ? `<div class="astro-title">${escapeHtml(title)}</div>` : ''}
                ${text ? `<div class="astro-body">${renderMarkup(text)}</div>` : ''}
                ${restKeys.length ? `<div class="astro-meta">${buildGenericValue(rest, 0)}</div>` : ''}`;
        } else {
            body = `<div class="astro-body">${renderInline(escapeHtml(String(data ?? '')))}</div>`;
        }

        return `<div class="astro-card">
            <div class="astro-card-head">
                <span class="astro-card-badge"><i class="fa-solid fa-meteor"></i> Astrophysics</span>
            </div>
            ${body}
        </div>`;
    }

    function buildUiDataCard(uiType, data) {
        const kind = detectUiKind(uiType, data);
        if (kind === 'search') return buildSearchResultsCard(data);
        if (kind === 'astro') return buildAstroCard(data);
        if (kind === 'github') return buildGithubCard(data);
        if (kind === 'file') return buildFileUiCard(data);
        if (kind === 'file_list') return buildFileListUiCard(data);
        const mediaItems = tryDetectMediaArray(data);
        if (mediaItems) return buildMediaGridCard(mediaItems, { big: false });
        return buildGenericUiCard(data);
    }

    // ------------------------------------------------------------
    // GitHub MCP cards — github_mcp.py sends ui_type="github" with a
    // `kind` discriminator inside `data` (repo, issue_list, pr_detail,
    // actions_runs, ...). Everything here assumes the payload has
    // already been through the server-side `sanitize()` pass (bounded
    // strings/arrays, JSON-native types), but we still escape and
    // sanitizeUrl() everything client-side too — never trust a single
    // layer for output safety.
    // ------------------------------------------------------------
    function ghBadge(iconClass, label) {
        return `<span class="gh-card-badge"><i class="fa-brands ${iconClass}"></i> ${escapeHtml(label)}</span>`;
    }

    function ghShell(badgeHtml, bodyHtml) {
        return `<div class="gh-card">
            <div class="gh-card-head">${badgeHtml}</div>
            <div class="gh-card-body">${bodyHtml}</div>
        </div>`;
    }

    function ghLink(url, label) {
        const safe = sanitizeUrl(url);
        if (!safe) return escapeHtml(label || '');
        return `<a href="${escapeHtml(safe)}" target="_blank" rel="noopener" class="gh-link">${escapeHtml(label || safe)}</a>`;
    }

    function ghRelTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        const diffMs = Date.now() - d.getTime();
        const mins = Math.round(diffMs / 60000);
        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.round(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        const days = Math.round(hrs / 24);
        if (days < 30) return `${days}d ago`;
        return d.toLocaleDateString();
    }

    function ghStateChip(state) {
        const s = String(state || '').toLowerCase();
        const cls = s === 'open' ? 'gh-chip-open'
                  : s === 'closed' ? 'gh-chip-closed'
                  : s === 'merged' ? 'gh-chip-merged'
                  : 'gh-chip-neutral';
        return `<span class="gh-chip ${cls}">${escapeHtml(state || '')}</span>`;
    }

    function ghLabels(labels) {
        if (!Array.isArray(labels) || !labels.length) return '';
        return `<div class="gh-labels">${labels.map(l => `<span class="gh-label">${escapeHtml(String(l))}</span>`).join('')}</div>`;
    }

    function ghEmpty(msg) {
        return `<div class="gh-empty">${escapeHtml(msg)}</div>`;
    }

    function buildGithubCard(data) {
        if (!data || typeof data !== 'object') return ghShell(ghBadge('fa-github', 'GitHub'), ghEmpty('No data.'));
        const kind = data.kind || 'generic';

        switch (kind) {
            case 'error':
                return ghShell(
                    `<span class="gh-card-badge gh-card-badge-error"><i class="fa-solid fa-triangle-exclamation"></i> GitHub Error</span>`,
                    `<div class="gh-error-msg">${escapeHtml(data.message || 'Something went wrong.')}</div>
                     ${data.detail ? `<div class="gh-error-detail">${escapeHtml(data.detail)}</div>` : ''}`
                );

            case 'repo': {
                const langs = data.languages && typeof data.languages === 'object'
                    ? Object.keys(data.languages) : [];
                const stats = `
                    <div class="gh-stat-row">
                        <span class="gh-stat"><i class="fa-solid fa-star"></i> ${escapeHtml(String(data.stars ?? 0))}</span>
                        <span class="gh-stat"><i class="fa-solid fa-code-fork"></i> ${escapeHtml(String(data.forks ?? 0))}</span>
                        <span class="gh-stat"><i class="fa-solid fa-eye"></i> ${escapeHtml(String(data.watchers ?? 0))}</span>
                        <span class="gh-stat"><i class="fa-solid fa-circle-dot"></i> ${escapeHtml(String(data.open_issues ?? 0))} issues</span>
                        ${data.license ? `<span class="gh-stat"><i class="fa-solid fa-scale-balanced"></i> ${escapeHtml(data.license)}</span>` : ''}
                    </div>`;
                return ghShell(
                    ghBadge('fa-github', data.name || 'Repository'),
                    `<div class="gh-repo-title">${ghLink(data.url, data.name)}</div>
                     ${data.description ? `<div class="gh-repo-desc">${escapeHtml(data.description)}</div>` : ''}
                     ${stats}
                     ${langs.length ? `<div class="gh-chip-row">${langs.map(l => `<span class="gh-chip gh-chip-neutral">${escapeHtml(l)}</span>`).join('')}</div>` : ''}
                     ${Array.isArray(data.topics) && data.topics.length ? ghLabels(data.topics) : ''}
                     ${data.readme_snippet ? `<div class="gh-readme">${renderMarkup(data.readme_snippet)}</div>` : ''}`
                );
            }

            case 'repo_search': {
                const results = Array.isArray(data.results) ? data.results : [];
                if (!results.length) return ghShell(ghBadge('fa-github', 'Repo Search'), ghEmpty('No repositories found.'));
                const rows = results.map(r => `
                    <div class="gh-row">
                        <div class="gh-row-main">${ghLink(r.url, r.name)}</div>
                        ${r.description ? `<div class="gh-row-sub">${escapeHtml(r.description)}</div>` : ''}
                        <div class="gh-row-meta">
                            <span class="gh-stat"><i class="fa-solid fa-star"></i> ${escapeHtml(String(r.stars ?? 0))}</span>
                            ${r.language ? `<span class="gh-chip gh-chip-neutral">${escapeHtml(r.language)}</span>` : ''}
                        </div>
                    </div>`).join('');
                return ghShell(ghBadge('fa-github', `Repos matching "${data.query || ''}"`), rows);
            }

            case 'issue_list': {
                const issues = Array.isArray(data.issues) ? data.issues : [];
                if (!issues.length) return ghShell(ghBadge('fa-github', data.repo || 'Issues'), ghEmpty('No open issues.'));
                const rows = issues.map(i => `
                    <div class="gh-row">
                        <div class="gh-row-main">${ghLink(i.url, `#${i.number} ${i.title}`)}</div>
                        ${ghLabels(i.labels)}
                        <div class="gh-row-meta">
                            <span class="gh-row-author">@${escapeHtml(i.user || '')}</span>
                            <span><i class="fa-regular fa-comment"></i> ${escapeHtml(String(i.comments ?? 0))}</span>
                            <span>${ghRelTime(i.created_at)}</span>
                        </div>
                    </div>`).join('');
                return ghShell(ghBadge('fa-code-branch', `${data.repo || ''} · Issues`), rows);
            }

            case 'issue_detail': {
                const comments = Array.isArray(data.comments) ? data.comments : [];
                const commentsHtml = comments.length
                    ? `<div class="gh-comments">${comments.map(c => `
                        <div class="gh-comment">
                            <div class="gh-comment-head">@${escapeHtml(c.user || '')} <span>${ghRelTime(c.created_at)}</span></div>
                            <div class="gh-comment-body">${renderMarkup(c.body || '')}</div>
                        </div>`).join('')}</div>`
                    : '';
                return ghShell(
                    ghBadge('fa-github', `${data.repo || ''} #${data.number ?? ''}`),
                    `<div class="gh-repo-title">${ghLink(data.url, data.title)} ${ghStateChip(data.state)}</div>
                     <div class="gh-row-meta"><span class="gh-row-author">@${escapeHtml(data.user || '')}</span></div>
                     ${ghLabels(data.labels)}
                     ${data.body ? `<div class="gh-readme">${renderMarkup(data.body)}</div>` : ''}
                     ${commentsHtml}`
                );
            }

            case 'issue_result':
            case 'pr_result': {
                return ghShell(
                    ghBadge('fa-circle-check', 'GitHub'),
                    `<div class="gh-result-line">
                        <i class="fa-solid fa-circle-check gh-result-icon"></i>
                        <span>${escapeHtml(data.action || 'done')}${data.number ? ` — #${escapeHtml(String(data.number))}` : ''}${data.repo ? ` (${escapeHtml(data.repo)})` : ''}</span>
                     </div>
                     ${data.url ? `<div class="gh-row-meta">${ghLink(data.url, data.title || data.url)}</div>` : ''}
                     ${data.message ? `<div class="gh-row-sub">${escapeHtml(data.message)}</div>` : ''}`
                );
            }

            case 'pr_list': {
                const prs = Array.isArray(data.pull_requests) ? data.pull_requests : [];
                if (!prs.length) return ghShell(ghBadge('fa-code-pull-request', data.repo || 'Pull Requests'), ghEmpty('No open pull requests.'));
                const rows = prs.map(p => `
                    <div class="gh-row">
                        <div class="gh-row-main">${ghLink(p.url, `#${p.number} ${p.title}`)} ${p.draft ? '<span class="gh-chip gh-chip-neutral">draft</span>' : ''}</div>
                        <div class="gh-row-meta">
                            <span class="gh-row-author">@${escapeHtml(p.user || '')}</span>
                            <span><i class="fa-solid fa-code-branch"></i> ${escapeHtml(p.head || '')} → ${escapeHtml(p.base || '')}</span>
                            <span>${ghRelTime(p.created_at)}</span>
                        </div>
                    </div>`).join('');
                return ghShell(ghBadge('fa-code-pull-request', `${data.repo || ''} · Pull Requests`), rows);
            }

            case 'pr_detail': {
                const files = Array.isArray(data.changed_files) ? data.changed_files : [];
                const filesHtml = files.length
                    ? `<div class="gh-files">${files.map(f => `
                        <div class="gh-file">
                            <div class="gh-file-head">
                                <span class="gh-file-name">${escapeHtml(f.filename || '')}</span>
                                <span class="gh-file-stats"><span class="gh-add">+${escapeHtml(String(f.additions ?? 0))}</span> <span class="gh-del">-${escapeHtml(String(f.deletions ?? 0))}</span></span>
                            </div>
                            ${f.patch ? `<pre class="gh-patch">${escapeHtml(f.patch)}</pre>` : ''}
                        </div>`).join('')}</div>`
                    : '';
                return ghShell(
                    ghBadge('fa-code-pull-request', `${data.repo || ''} #${data.number ?? ''}`),
                    `<div class="gh-repo-title">${ghLink(data.url, data.title)}</div>
                     <div class="gh-row-meta">
                        <span class="gh-row-author">@${escapeHtml(data.user || '')}</span>
                        <span><i class="fa-solid fa-code-branch"></i> ${escapeHtml(data.head || '')} → ${escapeHtml(data.base || '')}</span>
                        <span class="gh-add">+${escapeHtml(String(data.additions ?? 0))}</span>
                        <span class="gh-del">-${escapeHtml(String(data.deletions ?? 0))}</span>
                     </div>
                     ${data.body ? `<div class="gh-readme">${renderMarkup(data.body)}</div>` : ''}
                     ${filesHtml}`
                );
            }

            case 'actions_runs': {
                const runs = Array.isArray(data.runs) ? data.runs : [];
                if (!runs.length) return ghShell(ghBadge('fa-circle-play', `${data.repo || ''} · Actions`), ghEmpty(`No workflow runs (status: ${data.status || 'any'}).`));
                const rows = runs.map(r => {
                    const ok = r.conclusion === 'success';
                    const bad = r.conclusion === 'failure';
                    const cls = ok ? 'gh-chip-open' : bad ? 'gh-chip-closed' : 'gh-chip-neutral';
                    return `<div class="gh-row">
                        <div class="gh-row-main">${ghLink(r.url, `${r.name || 'workflow'} #${r.run_number ?? ''}`)} <span class="gh-chip ${cls}">${escapeHtml(r.conclusion || r.status || '')}</span></div>
                        <div class="gh-row-meta">
                            <span><i class="fa-solid fa-code-branch"></i> ${escapeHtml(r.branch || '')}</span>
                            <span>${escapeHtml(r.event || '')}</span>
                            <span>${ghRelTime(r.created_at)}</span>
                        </div>
                    </div>`;
                }).join('');
                return ghShell(ghBadge('fa-circle-play', `${data.repo || ''} · Actions (${data.status || ''})`), rows);
            }

            case 'commits': {
                const commits = Array.isArray(data.commits) ? data.commits : [];
                if (!commits.length) return ghShell(ghBadge('fa-code-commit', data.repo || 'Commits'), ghEmpty('No commits found.'));
                const rows = commits.map(c => `
                    <div class="gh-row">
                        <div class="gh-row-main"><span class="gh-sha">${escapeHtml(c.sha || '')}</span> ${ghLink(c.url, c.message || '(no message)')}</div>
                        <div class="gh-row-meta"><span class="gh-row-author">@${escapeHtml(c.author || '')}</span><span>${ghRelTime(c.date)}</span></div>
                    </div>`).join('');
                return ghShell(ghBadge('fa-code-commit', `${data.repo || ''} · ${data.branch || 'commits'}`), rows);
            }

            case 'branches': {
                const branches = Array.isArray(data.branches) ? data.branches : [];
                if (!branches.length) return ghShell(ghBadge('fa-code-branch', data.repo || 'Branches'), ghEmpty('No branches found.'));
                const rows = branches.map(b => `
                    <div class="gh-row gh-row-compact">
                        <span class="gh-row-main">${escapeHtml(b.name || '')} ${b.is_default ? '<span class="gh-chip gh-chip-open">default</span>' : ''} ${b.protected ? '<span class="gh-chip gh-chip-neutral">protected</span>' : ''}</span>
                        <span class="gh-sha">${escapeHtml(b.sha || '')}</span>
                    </div>`).join('');
                return ghShell(ghBadge('fa-code-branch', `${data.repo || ''} · Branches`), rows);
            }

            case 'releases': {
                const releases = Array.isArray(data.releases) ? data.releases : [];
                if (!releases.length) return ghShell(ghBadge('fa-tag', data.repo || 'Releases'), ghEmpty('No releases found.'));
                const rows = releases.map(r => `
                    <div class="gh-row">
                        <div class="gh-row-main">${ghLink(r.url, r.name || r.tag)} ${r.prerelease ? '<span class="gh-chip gh-chip-neutral">pre-release</span>' : ''}</div>
                        <div class="gh-row-meta"><span class="gh-sha">${escapeHtml(r.tag || '')}</span><span>${ghRelTime(r.published_at)}</span></div>
                        ${r.notes ? `<div class="gh-row-sub">${escapeHtml(r.notes)}</div>` : ''}
                    </div>`).join('');
                return ghShell(ghBadge('fa-tag', `${data.repo || ''} · Releases`), rows);
            }

            case 'file': {
                if (data.is_dir) {
                    const entries = Array.isArray(data.entries) ? data.entries : [];
                    const rows = entries.map(e => `<div class="gh-row gh-row-compact">
                        <span class="gh-row-main"><i class="fa-solid ${e.type === 'dir' ? 'fa-folder' : 'fa-file'}"></i> ${escapeHtml(e.name || '')}</span>
                    </div>`).join('');
                    return ghShell(ghBadge('fa-folder-open', data.path || data.repo || 'Directory'), rows || ghEmpty('Empty directory.'));
                }
                const body = data.is_binary
                    ? ghEmpty(`Binary file (${escapeHtml(String(data.size ?? '?'))} bytes) — ${ghLink(data.url, 'view on GitHub')}`)
                    : `<pre class="gh-patch gh-file-content">${escapeHtml(data.content || '')}</pre>`;
                return ghShell(
                    ghBadge('fa-file-code', data.path || 'File'),
                    `<div class="gh-row-meta"><span>${escapeHtml(data.repo || '')}</span><span>${escapeHtml(data.ref || '')}</span>${data.url ? `<span>${ghLink(data.url, 'open')}</span>` : ''}</div>${body}`
                );
            }

            case 'code_search': {
                const results = Array.isArray(data.results) ? data.results : [];
                if (!results.length) return ghShell(ghBadge('fa-magnifying-glass', 'Code Search'), ghEmpty('No matches found.'));
                const rows = results.map(r => `<div class="gh-row gh-row-compact">
                    <span class="gh-row-main"><i class="fa-solid fa-file-code"></i> ${ghLink(r.url, r.path)}</span>
                    <span class="gh-sha">${escapeHtml(r.sha || '')}</span>
                </div>`).join('');
                return ghShell(ghBadge('fa-magnifying-glass', `"${data.query || ''}" in ${data.repo || ''}`), rows);
            }

            case 'notifications': {
                const notifs = Array.isArray(data.notifications) ? data.notifications : [];
                if (!notifs.length) return ghShell(ghBadge('fa-bell', 'Notifications'), ghEmpty('No notifications.'));
                const rows = notifs.map(n => `<div class="gh-row">
                    <div class="gh-row-main">${n.unread ? '<i class="fa-solid fa-circle gh-unread-dot"></i> ' : ''}${escapeHtml(n.title || '')}</div>
                    <div class="gh-row-meta"><span>${escapeHtml(n.repo || '')}</span><span class="gh-chip gh-chip-neutral">${escapeHtml(n.reason || '')}</span><span>${ghRelTime(n.updated_at)}</span></div>
                </div>`).join('');
                return ghShell(ghBadge('fa-bell', 'Notifications'), rows);
            }

            default:
                return ghShell(ghBadge('fa-github', 'GitHub'), buildGenericValue(data, 0));
        }
    }

    // ------------------------------------------------------------
    // Chat DOM
    // ------------------------------------------------------------
    function newTurn() {
        hideEmptyState();
        const el = document.createElement('div');
        el.className = 'turn';
        ui.chat.appendChild(el);
        return el;
    }

    function addUserBubble(turnEl, text, mcpTag, attachments) {
        const el = document.createElement('div');
        el.className = 'msg-user';

        let attachHtml = '';
        if (Array.isArray(attachments) && attachments.length) {
            attachHtml = `<div class="bubble-attachments">${attachments.map(a => {
                if (a.type === 'image') {
                    return `<img class="bubble-attachment-img" src="${a.url}" alt="${escapeHtml(a.original_name || 'image')}" onclick="window.open('${a.url}','_blank')">`;
                }
                return `<a class="bubble-attachment-file" href="${a.url}" target="_blank" rel="noopener">
                    <i class="fa-solid fa-file"></i><span>${escapeHtml(a.original_name || 'file')}</span>
                </a>`;
            }).join('')}</div>`;
        }

        const bubbleBody = text
            ? `${mcpTag ? `<span class="mcp-tag">@${escapeHtml(mcpTag)}</span>` : ''}${linkifyEscaped(text)}`
            : '';

        el.innerHTML = `<div class="bubble">${attachHtml}${bubbleBody}</div>`;
        turnEl.appendChild(el);
        scrollToBottom(true);
    }

    function addAgentBubble(turnEl, agent_name, icon, color) {
        // icon/color from the state payload used to pick a different
        // avatar glyph + hue per agent (a little "logo" per message).
        // Ignored on purpose now — every agent shares one calm,
        // consistent mark; `color` still tints the agent name label
        // faintly so turns stay easy to scan, nothing more.
        const el = document.createElement('div');
        el.className = 'msg-agent';
        el.style.setProperty('--agent-rgb', color);
        el.innerHTML = `
            <div class="agent-avatar hina-mark"><span class="hina-mark-core"></span></div>
            <div class="agent-body">
                <div class="agent-name">${escapeHtml(agent_name)}</div>
                <div class="agent-text"></div>
            </div>`;
        turnEl.appendChild(el);
        scrollToBottom();
        return el.querySelector('.agent-text');
    }

    // ------------------------------------------------------------
    // Reasoning trace — small, collapsible, inline per turn.
    // Replaces the old bottom terminal-style activity panel.
    // ------------------------------------------------------------
    // Rotating "still working" words for the trace label. Cycles the
    // whole time the trace is open and nothing final has landed yet,
    // so a long gap between tool steps (or before the first one)
    // reads as "still going" instead of "stuck". Purely cosmetic —
    // real progress (tool steps) is still added underneath via
    // addTraceStep() same as before; this only changes the idle label.
   const THINKING_WORDS = [
  // Short / Direct
  'Thinking', 'Reasoning', 'Processing', 'Synthesizing', 'Distilling', 'Crystallizing',
  
  // Logical / Analytical
  'Tracing the logic', 'Connecting the dots', 'Examining premises', 'Unraveling complexity',
  'Piecing it together', 'Untangling threads', 'Evaluating variables', 'Sifting through signals',
  
  // Explanatory / Progressional
  'Mulling it over', 'Weighing options', 'Digging deeper', 'Sketching an answer',
  'Finding the signal', 'Checking the angles', 'Formulating the view', 'Almost calibrated'
];

    function startTraceWordCycle(traceEl) {
        const labelEl = traceEl.querySelector('.trace-label');
        if (!labelEl) return;
        let i = 0;
        const tick = () => {
            if (!traceEl.isConnected || !traceEl.classList.contains('trace-live')) {
                clearInterval(traceEl._wordTimer);
                traceEl._wordTimer = null;
                return;
            }
            i = (i + 1) % THINKING_WORDS.length;
            labelEl.classList.add('trace-label-fade');
            requestAnimationFrame(() => {
                labelEl.textContent = THINKING_WORDS[i];
                requestAnimationFrame(() => labelEl.classList.remove('trace-label-fade'));
            });
        };
        traceEl._wordTimer = setInterval(tick, 8200);
    }

    function createTrace(turnEl) {
        const el = document.createElement('div');
        el.className = 'trace open trace-live';
        el.innerHTML = `
            <div class="trace-head" data-toggle>
                <span class="hina-weave trace-icon" aria-hidden="true"><i></i><i></i><i></i></span>
                <span class="trace-label">Thinking</span>
                <span class="thinking-dots"><span></span><span></span><span></span></span>
                <i class="fa-solid fa-chevron-down trace-chevron" style="margin-left:auto"></i>
            </div>
            <div class="trace-steps"></div>`;
        el.querySelector('[data-toggle]').addEventListener('click', () => el.classList.toggle('open'));
        turnEl.appendChild(el);
        startTraceWordCycle(el);
        return el;
    }

    function addTraceStep(traceEl, data) {
        const steps = traceEl.querySelector('.trace-steps');
        const msg = typeof data.msg === 'string' ? data.msg.trim() : '';

        // A step whose msg is a run of {title, image_url}-shaped JSON
        // objects (raw tool output, log wrapper and all) gets pulled
        // out into a proper card grid instead of dumping the mess —
        // grouped into a running grid the same way bare-URL steps are,
        // so several tool calls in a row read as one tidy gallery.
        const titleLinkItems = tryDetectTitleLinkItems(msg);
        if (titleLinkItems && titleLinkItems.length >= 1) {
            let group = steps.lastElementChild;
            if (!group || !group.classList.contains('trace-link-group') || !group.classList.contains('trace-media-group')) {
                group = document.createElement('div');
                group.className = 'trace-link-group trace-media-group';
                group.innerHTML = `<div class="trace-link-group-head">
                        <i class="fa-solid fa-images"></i>
                        <span>Results</span>
                        <span class="trace-link-group-count">0</span>
                    </div>
                    <div class="link-media-grid"></div>`;
                steps.appendChild(group);
            }
            const grid = group.querySelector('.link-media-grid');
            grid.insertAdjacentHTML('beforeend', buildTitleLinkCards(titleLinkItems).replace(/^[\s\S]*?<div class="link-media-grid">([\s\S]*)<\/div>$/, '$1'));
            group.querySelector('.trace-link-group-count').textContent = grid.children.length;
            steps.scrollTop = steps.scrollHeight;
            return;
        }

        // A step whose whole msg is just a bare URL (the classic
        // "Links" / "https://..." pattern) never gets its own plain
        // row — it's folded into a running card grid so ten links
        // in a row read as one tidy source list, not ten identical
        // "Links" labels stacked on top of each other.
        if (looksLikeBareUrl(msg)) {
            const card = buildLinkCard(msg, '');
            if (card) {
                let group = steps.lastElementChild;
                if (!group || !group.classList.contains('trace-link-group')) {
                    group = document.createElement('div');
                    group.className = 'trace-link-group';
                    group.innerHTML = `<div class="trace-link-group-head">
                            <i class="fa-solid fa-link"></i>
                            <span>Sources</span>
                            <span class="trace-link-group-count">0</span>
                        </div>
                        <div class="trace-link-group-grid"></div>`;
                    steps.appendChild(group);
                }
                const grid = group.querySelector('.trace-link-group-grid');
                grid.insertAdjacentHTML('beforeend', card);
                group.querySelector('.trace-link-group-count').textContent = grid.children.length;
                steps.scrollTop = steps.scrollHeight;
                return;
            }
        }

        const row = document.createElement('div');
        row.className = 'trace-step';
        row.innerHTML = `<i class="${data.icon}"></i>
            <span class="step-agent">${escapeHtml(data.agent_name)}</span>
            <span class="step-msg">${linkifyEscaped(msg || data.state)}</span>`;
        steps.appendChild(row);
        steps.scrollTop = steps.scrollHeight;
    }

    function finalizeTrace(traceEl, elapsedMs, stepCount) {
        if (!traceEl || !traceEl.isConnected) return;
        // Stop the rotating "still working" label — the real, final
        // label below replaces it for good.
        traceEl.classList.remove('trace-live');
        if (traceEl._wordTimer) { clearInterval(traceEl._wordTimer); traceEl._wordTimer = null; }

        const head = traceEl.querySelector('.trace-head');
        const iconEl = head.querySelector('.trace-icon');
        if (iconEl) iconEl.outerHTML = '<i class="fa-solid fa-check trace-icon"></i>';
        const dots = head.querySelector('.thinking-dots');
        if (dots) dots.remove();
        head.querySelector('.trace-label').textContent = stepCount
            ? `Worked for ${(elapsedMs / 1000).toFixed(1)}s · ${stepCount} step${stepCount === 1 ? '' : 's'}`
            : `Done in ${(elapsedMs / 1000).toFixed(1)}s`;

        // Collapse it, but keep it in the DOM — the trace is a record
        // of what happened during the turn, not just a loading spinner,
        // so it stays visible (collapsed, tap to expand) for the rest
        // of the session instead of being deleted a couple seconds
        // after finishing. It naturally clears on refresh/new chat.
        traceEl.classList.remove('open');
    }

    // ------------------------------------------------------------
    // Fake token streaming.
    //
    // The backend doesn't (necessarily) send per-token deltas over the
    // socket — data.text can arrive as one or a handful of large
    // chunks. Dropping each chunk straight into its own new bubble
    // caused two problems: (1) a <think>...</think> pair split across
    // chunks never matched as a whole, so it fell through to plain
    // markdown and showed up as literal "<think>" text; and (2) big
    // chunks just appeared instantly, with no sense of "typing".
    //
    // Fix: accumulate consecutive same-agent chunks for a turn into
    // one growing raw buffer, and reveal that buffer to the DOM a
    // little at a time on a self-paced timer, independent of how
    // chunky the network delivery actually is. This is deliberately
    // "fake" streaming — real streaming needs token-level deltas from
    // the backend — but it looks the same, and it's what most chat
    // products do client-side anyway once chunks need re-assembling.
    // ------------------------------------------------------------
    let activeStream = null; // { turnEl, textEl, agent_name, raw, revealed, timer, thinkMeta, done, streaming }

    function startStream(turnEl, agent_name, icon, color) {
        const textEl = addAgentBubble(turnEl, agent_name, icon, color);
        return { turnEl, textEl, agent_name, raw: '', revealed: 0, timer: null, thinkMeta: [], done: false, streaming: true };
    }

    function renderStreamFrame(stream) {
        const visible = stream.raw.slice(0, stream.revealed);
        stream.streaming = !stream.done || stream.revealed < stream.raw.length;
        renderInto(stream.textEl, visible, stream);
        const avatarEl = stream.textEl.closest('.msg-agent')?.querySelector('.hina-mark');
        if (avatarEl) avatarEl.classList.toggle('active', stream.streaming);
        scrollToBottom();
    }

    function tickStream(stream) {
        if (stream.revealed >= stream.raw.length) { stream.timer = null; return; }
        const remaining = stream.raw.length - stream.revealed;
        // Catch-up curve: big backlog (the network handed us a huge
        // chunk at once) reveals in bigger bites so we don't fall
        // further behind; a small backlog reveals a couple of
        // characters at a time with jittered timing for an organic,
        // per-token feel.
        let step;
        if (remaining > 500) step = 48;
        else if (remaining > 150) step = 16;
        else step = 2 + Math.floor(Math.random() * 3);
        stream.revealed = Math.min(stream.raw.length, stream.revealed + step);
        renderStreamFrame(stream);
        stream.timer = setTimeout(() => tickStream(stream), 18 + Math.random() * 16);
    }

    function appendToStream(stream, chunk) {
        stream.raw += chunk;
        if (!stream.timer) stream.timer = setTimeout(() => tickStream(stream), 0);
    }

    // Snaps whatever hasn't been revealed yet straight to visible —
    // used when a turn ends, the agent changes, or a new user message
    // starts, so nothing is ever left mid-reveal and orphaned.
    function finalizeStream(stream) {
        if (!stream) return;
        clearTimeout(stream.timer);
        stream.timer = null;
        stream.done = true;
        stream.revealed = stream.raw.length;
        renderStreamFrame(stream);
    }

    // ------------------------------------------------------------
    // Live payload handling
    // ------------------------------------------------------------
    let currentTurnEl = null;
    let currentTraceEl = null;
    let turnStartedAt = 0;
    let stepCount = 0;

    function ensureTurn() {
        if (!currentTurnEl) {
            currentTurnEl = newTurn();
            currentTraceEl = createTrace(currentTurnEl);
            turnStartedAt = Date.now();
            stepCount = 0;
        }
    }

    function processPayload(raw, depth) {
        depth = depth || 0;
        try {
            // The server also broadcasts small envelope messages purely
            // to drive the /live voice page: {type:'state', state:...}
            // for the mic indicator, and {type:'transcript', role, text}
            // for its own transcript panel. Neither is agent telemetry.
            // Previously these fell through to sanitizePayload(), which
            // defaulted agent_name to 'SYSTEM' and — since a bare state
            // ping is never done:true — opened a brand new "Thinking"
            // trace box with one orphaned "SYSTEM listening" step that
            // never got a matching done to close it. That's the trace
            // box that kept popping up after every turn and never went
            // away. Bail out here before any of that machinery runs.
            if (raw && (raw.type === 'state' || raw.type === 'transcript')) return;

            const data = sanitizePayload(raw);

            ui.stateLabel.textContent = data.done ? 'Idle' : data.state.replace('SYS_', '').replace(/_/g, ' ').toLowerCase();
            ui.statusDot.style.background = `rgb(${data.done ? COLOR_PALETTE.idle : data.color})`;
            ui.statusDot.classList.toggle('live', !data.done);

            if (!data.done) {
                ensureTurn();
                addTraceStep(currentTraceEl, data);
                stepCount++;
            }

            if (data.text) {
                // Pull any ~~{...}~~ control blocks out of the text
                // BEFORE it ever reaches the DOM. Extracted blocks are
                // re-dispatched through this same function (capped at a
                // shallow recursion depth so a malformed/adversarial
                // chain can't loop forever); whatever text is left over
                // is what actually gets shown to the user.
                const { clean, blocks } = extractInlineControlBlocks(data.text);

                if (blocks.length && depth < 3) {
                    blocks.forEach(block => processPayload(block, depth + 1));
                }

                if (clean) {
                    ensureTurn();
                    // Same bubble/stream continues as long as we're
                    // still in the same turn with the same agent —
                    // that's what lets a <think> opened in one chunk
                    // and closed in a later one match as a whole.
                    if (!activeStream || activeStream.turnEl !== currentTurnEl || activeStream.agent_name !== data.agent_name) {
                        finalizeStream(activeStream);
                        activeStream = startStream(currentTurnEl, data.agent_name, data.icon, data.color);
                    }
                    appendToStream(activeStream, clean);
                }
            }

            if (data.ui_data) {
                // music_player / music_control from music_mcp.py drive the
                // floating YouTube-widget player directly — they're
                // instructions, not cards to render through
                // buildUiDataCard's generic renderer.
                if (data.ui_type === 'music_player' && data.ui_data && typeof data.ui_data === 'object') {
                    playHinaMusic(data.ui_data.video_id, data.ui_data.title);
                } else if (data.ui_type === 'music_control' && data.ui_data && typeof data.ui_data === 'object') {
                    controlHinaMusic(data.ui_data.action);
                } else {
                    // Structured payload from send_ui_json() — already a
                    // real object, no text-sniffing or quote-repair needed.
                    ensureTurn();
                    finalizeStream(activeStream);
                    activeStream = null;
                    const el = addAgentBubble(currentTurnEl, data.agent_name, data.icon, data.color);
                    el.innerHTML = buildUiDataCard(data.ui_type, data.ui_data);
                    wireCodeCanvasButtons(el);
                    wireGallery(el);
                    wireThinkBlocks(el);
                    wireHinaFileCards(el);
                    scrollToBottom();
                }
            }

            if (data.is_voice) {
                ui.tokenEcho.textContent = '● voice';
                clearTimeout(ui._voiceTimeout);
                clearInterval(ui._voiceBurstInterval);
                ui._voiceTimeout = setTimeout(() => {
                    ui.tokenEcho.textContent = '';
                    clearInterval(ui._voiceBurstInterval);
                }, 1800);
            }

            if (data.done) {
                ui.tokenEcho.textContent = '';
                finalizeStream(activeStream);
                activeStream = null;
                if (currentTraceEl) finalizeTrace(currentTraceEl, Date.now() - turnStartedAt, stepCount);
                currentTurnEl = null;
                currentTraceEl = null;
            }
        } catch (err) {
            console.error('[processPayload] bad payload, skipping:', err, raw);
        }
    }


    // ------------------------------------------------------------
    // WebSocket
    // ------------------------------------------------------------
    let ws, wsReconnectTimer;
    function connectWS() {
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        ws = new WebSocket(`${proto}://${window.location.host}/ws`);
        ws.onopen = () => console.log('[WS] connected');
        ws.onmessage = (event) => {
            try {
                const raw = JSON.parse(event.data);
                // hin_voice_engine.py -> Node -> here: each synthesized
                // speech chunk arrives as {type:'voice_chunk', ...}.
                // This was never routed to voice-player.js — it has
                // handleChunk() ready and even sends the playback-done
                // ack back over this same `ws`, but nothing called it,
                // so every chunk fell into processPayload() as generic
                // agent data instead. The backend logs showed synthesis
                // completing every time ("Synthesis took: X.XXXs",
                // "Pipeline Flushed & Complete") because Piper really
                // was running and Node really was relaying — the audio
                // just never reached the browser's speakers. This is
                // why voice was silent everywhere (mobile and desktop
                // both go through this same code path) while music
                // (routed separately through the YouTube IFrame API)
                // played fine.
                if (raw && raw.type === 'voice_chunk') {
                    if (window.HinaVoicePlayer) window.HinaVoicePlayer.handleChunk(raw, ws);
                    return;
                }
                processPayload(raw);
            }
            catch (err) { console.error('[WS] bad message, skipping:', err, event.data); }
        };
        ws.onclose = () => {
            console.warn('[WS] disconnected, retrying in 2s');
            clearTimeout(wsReconnectTimer);
            wsReconnectTimer = setTimeout(connectWS, 2000);
        };
        ws.onerror = (err) => console.error('[WS] error', err);
    }

    // ------------------------------------------------------------
    // Session + history
    // ------------------------------------------------------------
    let sessionId = localStorage.getItem('hina_session_id');
    if (!sessionId) {
        sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
        localStorage.setItem('hina_session_id', sessionId);
    }

    // Stored agent rows can be either plain text, or a JSON-stringified
    // payload (the same shape processPayload() gets live off the
    // websocket: {agent_name, icon, color, text, ui_type, ui_data, ...}).
    // Unwrap it the same way processPayload() does before rendering,
    // instead of dumping the raw JSON string into the DOM.
    function unwrapStoredMessage(raw) {
        if (typeof raw !== 'string') return { text: '', ui_type: null, ui_data: null, agent_name: null, icon: null };
        const trimmed = raw.trim();
        if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            try {
                const parsed = JSON.parse(trimmed);
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) &&
                    ('text' in parsed || 'ui_data' in parsed || 'ui_type' in parsed || 'agent_name' in parsed)) {
                    const data = sanitizePayload(parsed);
                    return { text: data.text || '', ui_type: data.ui_type, ui_data: data.ui_data, agent_name: data.agent_name, icon: data.icon };
                }
            } catch (_) { /* not JSON, fall through to plain text */ }
        }
        return { text: raw, ui_type: null, ui_data: null, agent_name: null, icon: null };
    }

    // Rebuild the conversation from stored rows. History is all
    // *finished* work, so — matching "only show the trace while
    // actually working" — trace_step rows are skipped entirely on
    // reload rather than reconstructed into a fake collapsed trace.
    // Only the real content (user messages + final replies) reappears;
    // noise/'other' rows stay in the DB but are never rendered.
    async function loadHistory() {
        try {
            const res = await fetch(`/history?session_id=${encodeURIComponent(sessionId)}`);
            const data = await res.json();
            const rows = data.history || [];

            let turnEl = null;

            rows.forEach((row) => {
                if (row.kind === 'noise' || row.role === 'other') return;
                if (row.kind === 'trace_step' && !row.done) return; // done work, nothing to show

                if (row.kind === 'user_message' || row.role === 'user') {
                    turnEl = newTurn();
                    // server.js bakes a trailing "[image:name.jpg] [file:x.pdf]"
                    // note into row.message so the LLM has context that an
                    // attachment was present — strip it back out here since
                    // row.attachments now renders the real chip/img instead.
                    const cleanText = row.message.replace(/\s*\[(image|file):[^\]]*\]/gi, '').trim();
                    addUserBubble(turnEl, cleanText, null, row.attachments);
                    return;
                }

                if (!turnEl) turnEl = newTurn(); // defensive: stray agent row with no preceding user row

                const unwrapped = unwrapStoredMessage(row.message);
                const agentName = row.agent_name || unwrapped.agent_name || 'AGENT';
                const icon = row.icon || unwrapped.icon || 'fa-solid fa-sparkles';

                const el = addAgentBubble(turnEl, agentName, icon, COLOR_PALETTE.think);
                if (unwrapped.ui_data) {
                    el.innerHTML = buildUiDataCard(unwrapped.ui_type, unwrapped.ui_data);
                    wireCodeCanvasButtons(el);
                    wireGallery(el);
                    wireThinkBlocks(el);
                    wireHinaFileCards(el);
                } else {
                    renderInto(el, unwrapped.text);
                }
            });

            scrollToBottom(true);
        } catch (err) {
            console.error('[HISTORY] load failed:', err);
        }
    }

    loadHistory();
    connectWS();

    ui.clearBtn.addEventListener('click', () => {
        sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
        localStorage.setItem('hina_session_id', sessionId);
        ui.chat.innerHTML = `
            <div class="empty-state" id="empty-state">
                <div class="empty-orb"><i class="fa-solid fa-sparkles"></i></div>
                <h1>How can I help you today?</h1>
                <p>Ask anything, drop in a task, or bring an MCP tool in with <code>@</code>.</p>
            </div>`;
        ui.emptyState = document.getElementById('empty-state');
        currentTurnEl = null;
        currentTraceEl = null;
        if (activeStream) clearTimeout(activeStream.timer);
        activeStream = null;
    });

    // ------------------------------------------------------------
    // Attachments — drop, paste, or pick files/images into the
    // composer. Each file is uploaded to /upload the moment it's
    // added (saved server-side into data_files/ first), so by the
    // time the user hits send we already hold the exact saved
    // path/url/type for every attachment — nothing is sent as raw
    // bytes on the /agent/execute call itself.
    // ------------------------------------------------------------
    const attachBtn = document.getElementById('attach-btn');
    const fileInput = document.getElementById('file-input');
    const chipRow = document.getElementById('attach-chip-row');
    const dropOverlay = document.getElementById('drop-overlay');
    const composerForm = document.getElementById('input-form');

    // pending[id] = { id, file, localUrl, status: 'uploading'|'done'|'error', saved: {url,type,original_name,saved_name} }
    const pendingAttachments = new Map();
    let attachSeq = 0;

    function fileIconClass(name) {
        const ext = (name.split('.').pop() || '').toLowerCase();
        const map = {
            js: 'fa-solid fa-file-code', ts: 'fa-solid fa-file-code', jsx: 'fa-solid fa-file-code',
            tsx: 'fa-solid fa-file-code', py: 'fa-brands fa-python', html: 'fa-brands fa-html5',
            css: 'fa-brands fa-css3', json: 'fa-solid fa-file-code', md: 'fa-solid fa-file-lines',
            pdf: 'fa-solid fa-file-pdf', zip: 'fa-solid fa-file-zipper', csv: 'fa-solid fa-file-csv',
            xlsx: 'fa-solid fa-file-excel', doc: 'fa-solid fa-file-word', docx: 'fa-solid fa-file-word',
            txt: 'fa-solid fa-file-lines'
        };
        return map[ext] || 'fa-solid fa-file';
    }

    function renderChips() {
        const items = Array.from(pendingAttachments.values());
        if (!items.length) {
            chipRow.classList.add('hidden');
            chipRow.innerHTML = '';
            return;
        }
        chipRow.classList.remove('hidden');
        chipRow.innerHTML = items.map((it) => {
            const isImg = it.file.type.startsWith('image/');
            const thumb = isImg
                ? `<img class="attach-chip-thumb" src="${it.localUrl}" alt="">`
                : `<div class="attach-chip-icon"><i class="${fileIconClass(it.file.name)}"></i></div>`;
            return `<div class="attach-chip ${it.status === 'uploading' ? 'uploading' : ''}" data-id="${it.id}">
                ${thumb}
                <span class="attach-chip-name" title="${escapeHtml(it.file.name)}">${escapeHtml(it.file.name)}</span>
                <button type="button" class="attach-chip-remove" data-remove="${it.id}">&times;</button>
            </div>`;
        }).join('');
        chipRow.querySelectorAll('[data-remove]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const it = pendingAttachments.get(btn.dataset.remove);
                if (it && it.localUrl) URL.revokeObjectURL(it.localUrl);
                pendingAttachments.delete(btn.dataset.remove);
                renderChips();
            });
        });
    }

    async function uploadFile(id) {
        const it = pendingAttachments.get(id);
        if (!it) return;
        const fd = new FormData();
        fd.append('files', it.file);
        try {
            const res = await fetch('/upload', { method: 'POST', body: fd });
            if (!res.ok) throw new Error(`upload failed (${res.status})`);
            const data = await res.json();
            const saved = data.files && data.files[0];
            if (!saved) throw new Error('no file returned');
            const cur = pendingAttachments.get(id);
            if (!cur) return; // removed while uploading
            cur.status = 'done';
            cur.saved = saved;
            pendingAttachments.set(id, cur);
        } catch (err) {
            console.error('[UPLOAD ERR]', err);
            const cur = pendingAttachments.get(id);
            if (cur) { cur.status = 'error'; pendingAttachments.set(id, cur); }
        } finally {
            renderChips();
        }
    }

    function addFiles(fileList) {
        const files = Array.from(fileList || []);
        if (!files.length) return;
        files.forEach((file) => {
            const id = `att-${Date.now()}-${attachSeq++}`;
            const localUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : null;
            pendingAttachments.set(id, { id, file, localUrl, status: 'uploading', saved: null });
            uploadFile(id);
        });
        renderChips();
        refreshSendState();
    }

    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
        addFiles(fileInput.files);
        fileInput.value = '';
    });

    // Paste files/images directly into the textarea
    document.getElementById('prompt-input').addEventListener('paste', (e) => {
        const items = (e.clipboardData && e.clipboardData.files) || [];
        if (items.length) {
            addFiles(items);
        }
    });

    // Drag & drop anywhere over the composer
    let dragDepth = 0;
    composerForm.addEventListener('dragenter', (e) => {
        e.preventDefault();
        dragDepth++;
        dropOverlay.classList.remove('hidden');
    });
    composerForm.addEventListener('dragover', (e) => e.preventDefault());
    composerForm.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) dropOverlay.classList.add('hidden');
    });
    composerForm.addEventListener('drop', (e) => {
        e.preventDefault();
        dragDepth = 0;
        dropOverlay.classList.add('hidden');
        if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
    });

    function clearAttachments() {
        pendingAttachments.forEach((it) => { if (it.localUrl) URL.revokeObjectURL(it.localUrl); });
        pendingAttachments.clear();
        renderChips();
    }

    // ------------------------------------------------------------
    // Composer: auto-resizing textarea, Enter to send, @ for MCP
    // ------------------------------------------------------------
    function autoResize() {
        // Empty field -> drop back to the fixed single-line CSS height
        // instead of measuring scrollHeight. Measuring scrollHeight on
        // an empty textarea can pick up the *wrapped placeholder's*
        // rendered height on some mobile browsers, which is what made
        // the composer balloon to a multi-line box before anything
        // was typed.
        if (!ui.input.value) {
            ui.input.style.height = '';
            ui.input.style.overflowY = 'hidden';
            return;
        }
        ui.input.style.height = 'auto';
        const cap = parseFloat(getComputedStyle(ui.input).maxHeight) || 180;
        const next = Math.min(ui.input.scrollHeight, cap);
        ui.input.style.height = next + 'px';
        ui.input.style.overflowY = next >= cap ? 'auto' : 'hidden';
    }
    function refreshSendState() {
        const hasText = ui.input.value.trim().length > 0;
        const hasAttachments = pendingAttachments.size > 0;
        ui.sendBtn.disabled = !hasText && !hasAttachments;
    }
    ui.input.addEventListener('input', () => { autoResize(); refreshSendState(); });

    // On narrow phones the full desktop placeholder ("Message HINA…
    // (type @ to bring in a tool, drop or paste a file)") wraps to
    // several lines inside the composer and looks broken even once
    // it's clipped to one line. Swap in a shorter placeholder there,
    // and keep it in sync across rotation / resize.
    const narrowPlaceholderMq = window.matchMedia('(max-width: 640px)');
    function syncComposerPlaceholder() {
        ui.input.placeholder = narrowPlaceholderMq.matches
            ? 'Message HINA…'
            : 'Message HINA… (type @ to bring in a tool, drop or paste a file)';
    }
    syncComposerPlaceholder();
    if (narrowPlaceholderMq.addEventListener) {
        narrowPlaceholderMq.addEventListener('change', syncComposerPlaceholder);
    }
    // Re-baseline the composer height on load and on viewport changes
    // (rotation, keyboard open/close) so it can never get stuck tall.
    autoResize();
    window.addEventListener('resize', autoResize);

    ui.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && mcpDropdown.classList.contains('hidden')) {
            e.preventDefault();
            document.getElementById('input-form').requestSubmit();
        }
    });

    // ------------------------------------------------------------
    // Optional voice input (Web Speech API, graceful no-op if
    // the browser doesn't support it)
    // ------------------------------------------------------------
    // ------------------------------------------------------------
    // Mic button — launches the full-page hands-free voice
    // experience at /live (see live.html / live.js / live.css).
    // Session id travels via localStorage so /live picks up the
    // exact same conversation, and anything said there shows back
    // up here through the normal /history load on return.
    // ------------------------------------------------------------
    const micBtn = document.getElementById('mic-btn');
    micBtn.title = 'Voice mode';
    micBtn.addEventListener('click', () => {
        window.location.href = '/live';
    });

    // ------------------------------------------------------------
    // Voice reply toggle — advanced on/off switch next to the mic
    // button. State is cached locally (localStorage, for instant
    // paint on load) and persisted server-side via /voice/toggle,
    // which writes it to voice_state.json. /voice/status (and the
    // companion voice_status.py script) read that same file, so
    // the switch, the server, and any external script all agree
    // on a single value: 1 = on, 0 = off.
    // ------------------------------------------------------------
    const VOICE_CACHE_KEY = 'hina_voice_enabled';
    const voiceToggleBtn = document.getElementById('voice-toggle-btn');

    function setVoiceToggleUI(enabled) {
        voiceToggleBtn.setAttribute('aria-checked', enabled ? 'true' : 'false');
        voiceToggleBtn.title = enabled ? 'Voice replies: on' : 'Voice replies: off';
    }

    // 1) Paint instantly from cache so there's no flash of the
    //    wrong state while we wait on the network.
    const cachedVoice = localStorage.getItem(VOICE_CACHE_KEY);
    if (cachedVoice !== null) setVoiceToggleUI(cachedVoice === '1');

    // 2) Confirm against the server, which is the source of truth
    //    (covers first load, other devices/tabs, cache cleared).
    fetch('/voice/status')
        .then(r => r.json())
        .then(({ voice_enabled }) => {
            localStorage.setItem(VOICE_CACHE_KEY, voice_enabled ? '1' : '0');
            setVoiceToggleUI(voice_enabled);
        })
        .catch(err => console.error('[VOICE] failed to load /voice/status:', err));

    voiceToggleBtn.addEventListener('click', () => {
        const next = voiceToggleBtn.getAttribute('aria-checked') !== 'true';

        // Optimistic UI + cache update immediately.
        setVoiceToggleUI(next);
        localStorage.setItem(VOICE_CACHE_KEY, next ? '1' : '0');
        voiceToggleBtn.classList.add('syncing');

        fetch('/voice/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: next })
        })
            .then(r => { if (!r.ok) throw new Error(`toggle failed: ${r.status}`); return r.json(); })
            .then(({ voice_enabled }) => {
                // Reconcile with whatever the server actually saved.
                localStorage.setItem(VOICE_CACHE_KEY, voice_enabled ? '1' : '0');
                setVoiceToggleUI(voice_enabled);
            })
            .catch(err => {
                console.error('[VOICE] toggle sync failed, reverting:', err);
                // Roll back optimistic update on failure.
                const prev = !next;
                setVoiceToggleUI(prev);
                localStorage.setItem(VOICE_CACHE_KEY, prev ? '1' : '0');
            })
            .finally(() => voiceToggleBtn.classList.remove('syncing'));
    });

    // ------------------------------------------------------------
    // @ mention: pick an MCP server from /mcp/list
    // ------------------------------------------------------------
    let mcpServers = [];
    let selectedMcpServer = null;

    const MCP_FALLBACK = [
        { name: 'github', label: 'GitHub', icon: 'fa-brands fa-github', description: '(fallback — /mcp/list unreachable)' },
        { name: 'web_search', label: 'Web Search', icon: 'fa-solid fa-magnifying-glass', description: '(fallback — /mcp/list unreachable)' }
    ];

    fetch('/mcp/list')
        .then(r => { if (!r.ok) throw new Error(`/mcp/list returned ${r.status}`); return r.json(); })
        .then((list) => { mcpServers = Array.isArray(list) && list.length ? list : MCP_FALLBACK; })
        .catch((err) => { console.error('[MCP] failed to load /mcp/list, using fallback:', err); mcpServers = MCP_FALLBACK; });

    const mcpDropdown = document.getElementById('mcp-dropdown');
    const mcpPill = document.getElementById('mcp-pill');
    const mcpPillIcon = document.getElementById('mcp-pill-icon');
    const mcpPillLabel = document.getElementById('mcp-pill-label');
    const mcpPillRemove = document.getElementById('mcp-pill-remove');

    function showMcpDropdown(filterText) {
        if (!mcpServers.length) { mcpDropdown.classList.add('hidden'); return; }
        const matches = mcpServers.filter(s =>
            s.name.toLowerCase().includes(filterText.toLowerCase()) ||
            s.label.toLowerCase().includes(filterText.toLowerCase())
        );
        if (!matches.length) { mcpDropdown.classList.add('hidden'); return; }

        mcpDropdown.innerHTML = matches.map(s => `
            <div class="mcp-option" data-name="${s.name}" data-label="${s.label}" data-icon="${s.icon}">
                <i class="${s.icon}"></i>
                <div>
                    <div class="mcp-option-label">${s.label}</div>
                    <div class="mcp-option-desc">${s.description || ''}</div>
                </div>
            </div>
        `).join('');
        mcpDropdown.classList.remove('hidden');
        mcpDropdown.querySelectorAll('.mcp-option').forEach((opt) => {
            opt.addEventListener('click', () => selectMcpServer(opt.dataset.name, opt.dataset.label, opt.dataset.icon));
        });
    }

    function selectMcpServer(name, label, icon) {
        selectedMcpServer = name;
        mcpPillIcon.className = icon;
        mcpPillLabel.textContent = label;
        mcpPill.classList.remove('hidden');
        mcpDropdown.classList.add('hidden');
        const val = ui.input.value;
        const at = val.lastIndexOf('@');
        if (at !== -1) ui.input.value = val.slice(0, at);
        ui.input.focus();
        refreshSendState();
    }

    mcpPillRemove.addEventListener('click', () => {
        selectedMcpServer = null;
        mcpPill.classList.add('hidden');
    });

    ui.input.addEventListener('input', () => {
        const val = ui.input.value;
        const at = val.lastIndexOf('@');
        if (at !== -1 && !val.slice(at).includes(' ')) showMcpDropdown(val.slice(at + 1));
        else mcpDropdown.classList.add('hidden');
    });

    document.addEventListener('click', (e) => {
        if (!mcpDropdown.contains(e.target) && e.target !== ui.input) mcpDropdown.classList.add('hidden');
    });

    // ------------------------------------------------------------
    // Submit
    // ------------------------------------------------------------
    document.getElementById('input-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const prompt = ui.input.value.trim();
        const hasAttachments = pendingAttachments.size > 0;
        if (!prompt && !hasAttachments) return;

        // If any attachment is still mid-upload, wait for it — we
        // never want to dispatch before every file has a confirmed
        // saved path on disk.
        if (hasAttachments) {
            ui.sendBtn.disabled = true;
            const stillUploading = () => Array.from(pendingAttachments.values()).some(it => it.status === 'uploading');
            while (stillUploading()) {
                await new Promise(r => setTimeout(r, 150));
            }
        }

        const attachments = Array.from(pendingAttachments.values())
            .filter(it => it.status === 'done' && it.saved)
            .map(it => it.saved);

        finalizeStream(activeStream);
        activeStream = null;

        const turnEl = newTurn();
        currentTurnEl = turnEl;
        addUserBubble(turnEl, prompt, selectedMcpServer, attachments);
        currentTraceEl = createTrace(turnEl);
        turnStartedAt = Date.now();
        stepCount = 0;

        ui.input.value = '';
        autoResize();
        clearAttachments();
        refreshSendState();

        const dispatchServer = selectedMcpServer;
        selectedMcpServer = null;
        mcpPill.classList.add('hidden');

        fetch('/agent/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt,
                session_id: sessionId,
                mcp_server: dispatchServer,
                attachments: attachments.map(a => ({ path: a.path, saved_name: a.saved_name, type: a.type, original_name: a.original_name }))
            })
        }).catch((err) => {
            console.error('Dispatch failed:', err);
            if (currentTraceEl) finalizeTrace(currentTraceEl, Date.now() - turnStartedAt, stepCount);
            const errEl = document.createElement('div');
            errEl.className = 'msg-agent';
            errEl.style.setProperty('--agent-rgb', COLOR_PALETTE.error);
            errEl.innerHTML = `<div class="agent-avatar hina-mark"><span class="hina-mark-core"></span></div>
                <div class="agent-body"><div class="agent-name">system</div>
                <div class="agent-text"><p>Couldn't reach the node controller. Check that the backend is running.</p></div></div>`;
            turnEl.appendChild(errEl);
            currentTurnEl = null; currentTraceEl = null;
            scrollToBottom(true);
        });
    });
});