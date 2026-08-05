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
// Orb — small ambient status mark in the header, not a feature
// on its own anymore. Calm by default, livens up with state.
// ============================================================
class HinaOrb {
    constructor() {
        this.canvas = document.getElementById('hina-orb');
        this.ctx = this.canvas.getContext('2d', { alpha: true });
        this.cfg = { radius: 15, rings: 3, speed: 0.0015, targetSpeed: 0.0015, amp: 0.8, targetAmp: 0.8, time: 0, rgb: COLOR_PALETTE.idle };
        this.animate = this.animate.bind(this);
        requestAnimationFrame(this.animate);
    }
    setColor(rgb) { this.cfg.rgb = rgb; }
    setState(stateStr) {
        switch (stateStr) {
            case 'idle':   this.cfg.targetSpeed = 0.0015; this.cfg.targetAmp = 0.8; break;
            case 'action': this.cfg.targetSpeed = 0.01;   this.cfg.targetAmp = 3.2; break;
            default:       this.cfg.targetSpeed = 0.006;  this.cfg.targetAmp = 2.2; break;
        }
    }
    voiceBurst() { this.cfg.targetSpeed = 0.018; this.cfg.targetAmp = 4 + Math.random() * 2; }
    animate() {
        const c = this.canvas, ctx = this.ctx;
        ctx.clearRect(0, 0, c.width, c.height);
        const cx = c.width / 2, cy = c.height / 2;
        this.cfg.speed += (this.cfg.targetSpeed - this.cfg.speed) * 0.06;
        this.cfg.amp += (this.cfg.targetAmp - this.cfg.amp) * 0.1;
        this.cfg.time += this.cfg.speed;
        for (let r = 0; r < this.cfg.rings; r++) {
            ctx.beginPath();
            const radius = this.cfg.radius - r * 3.4;
            for (let i = 0; i <= 60; i++) {
                const a = (i / 60) * Math.PI * 2;
                const phase = this.cfg.time * (r + 1.4);
                const noise = Math.sin(a * 4 + phase) * Math.cos(a * 3 - phase) * this.cfg.amp;
                const d = radius + noise;
                const x = cx + Math.cos(a) * d, y = cy + Math.sin(a) * d;
                i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.strokeStyle = `rgba(${this.cfg.rgb}, ${0.85 - r * 0.22})`;
            ctx.lineWidth = 1.2;
            ctx.stroke();
        }
        requestAnimationFrame(this.animate);
    }
}

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
    const orb = new HinaOrb();

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
            const videoEmbed = buildVideoEmbedIfApplicable(trimmedUrl);
            out += videoEmbed || buildInlineLinkChip(trimmedUrl);
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

    function renderMarkup(rawText) {
        rawText = autoFenceRawCode(rawText);
        const codeBlocks = [];
        let text = rawText.replace(/```(\w+)?\n?([\s\S]*?)```/g, (match, lang, code) => {
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

        for (const rawLine of lines) {
            const line = rawLine.replace(/\s+$/, '');

            if (!line.trim()) { flushPara(); flushList(); continue; }

            // Code-block marker line -- flush current block context and
            // drop it straight into the html stream as-is.
            if (/^\u0001CB\d+\u0001$/.test(line.trim())) {
                flushPara(); flushList();
                html += line.trim();
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

        return html || `<p>${renderInline(text)}</p>`;
    }

    function wireCodeCanvasButtons(root) {
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
        const lines = cleanOverviewLines(rawOverview);
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
        return html;
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

    function renderInto(el, rawText) {
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
            return;
        }
        el.innerHTML = renderMarkup(rawText);
        wireCodeCanvasButtons(el);
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
        if (data && typeof data === 'object' &&
            (Array.isArray(data.organic_results) || Array.isArray(data.ai_links))) {
            return 'search';
        }
        return 'generic';
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

    function buildAstroCard(data) {
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
        return buildGenericUiCard(data);
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
        const el = document.createElement('div');
        el.className = 'msg-agent';
        el.style.setProperty('--agent-rgb', color);
        el.innerHTML = `
            <div class="agent-avatar"><i class="${icon}"></i></div>
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
    function createTrace(turnEl) {
        const el = document.createElement('div');
        el.className = 'trace open';
        el.innerHTML = `
            <div class="trace-head" data-toggle>
                <i class="fa-solid fa-circle-notch fa-spin trace-icon"></i>
                <span class="trace-label">Thinking</span>
                <span class="thinking-dots"><span></span><span></span><span></span></span>
                <i class="fa-solid fa-chevron-down trace-chevron" style="margin-left:auto"></i>
            </div>
            <div class="trace-steps"></div>`;
        el.querySelector('[data-toggle]').addEventListener('click', () => el.classList.toggle('open'));
        turnEl.appendChild(el);
        return el;
    }

    function addTraceStep(traceEl, data) {
        const steps = traceEl.querySelector('.trace-steps');
        const msg = typeof data.msg === 'string' ? data.msg.trim() : '';

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
        row.innerHTML = `<i class="${data.icon}" style="color: rgb(${data.color})"></i>
            <span class="step-agent">${escapeHtml(data.agent_name)}</span>
            <span class="step-msg">${linkifyEscaped(msg || data.state)}</span>`;
        steps.appendChild(row);
        steps.scrollTop = steps.scrollHeight;
    }

    function finalizeTrace(traceEl, elapsedMs, stepCount) {
        const head = traceEl.querySelector('.trace-head');
        head.querySelector('.trace-icon').className = 'fa-solid fa-check trace-icon';
        head.querySelector('.trace-icon').style.color = `rgb(${COLOR_PALETTE.success})`;
        const dots = head.querySelector('.thinking-dots');
        if (dots) dots.remove();
        head.querySelector('.trace-label').textContent = stepCount
            ? `Worked for ${(elapsedMs / 1000).toFixed(1)}s · ${stepCount} step${stepCount === 1 ? '' : 's'}`
            : `Done in ${(elapsedMs / 1000).toFixed(1)}s`;
        traceEl.classList.remove('open');
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
            const data = sanitizePayload(raw);

            orb.setColor(data.color);
            orb.setState(data.done ? 'idle' : 'action');
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
                    const textEl = addAgentBubble(currentTurnEl, data.agent_name, data.icon, data.color);
                    renderInto(textEl, clean);
                    scrollToBottom();
                }
            }

            if (data.ui_data) {
                // Structured payload from send_ui_json() — already a
                // real object, no text-sniffing or quote-repair needed.
                ensureTurn();
                const el = addAgentBubble(currentTurnEl, data.agent_name, data.icon, data.color);
                el.innerHTML = buildUiDataCard(data.ui_type, data.ui_data);
                wireCodeCanvasButtons(el);
                wireGallery(el);
                scrollToBottom();
            }

            if (data.is_voice) {
                ui.tokenEcho.textContent = '● voice';
                clearTimeout(ui._voiceTimeout);
                clearInterval(ui._voiceBurstInterval);
                ui._voiceBurstInterval = setInterval(() => orb.voiceBurst(), 120);
                ui._voiceTimeout = setTimeout(() => {
                    ui.tokenEcho.textContent = '';
                    clearInterval(ui._voiceBurstInterval);
                }, 1800);
            }

            if (data.done) {
                ui.tokenEcho.textContent = '';
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
            try { processPayload(JSON.parse(event.data)); }
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

    async function loadHistory() {
        try {
            const res = await fetch(`/history?session_id=${encodeURIComponent(sessionId)}`);
            const data = await res.json();
            (data.history || []).forEach((row) => {
                const turnEl = newTurn();
                if (row.role === 'user') {
                    addUserBubble(turnEl, row.message);
                } else {
                    const textEl = addAgentBubble(turnEl, row.agent_name || 'AGENT', row.icon || 'fa-solid fa-sparkles', COLOR_PALETTE.think);
                    renderInto(textEl, row.message);
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
        ui.input.style.height = 'auto';
        ui.input.style.height = Math.min(ui.input.scrollHeight, 180) + 'px';
    }
    function refreshSendState() {
        const hasText = ui.input.value.trim().length > 0;
        const hasAttachments = pendingAttachments.size > 0;
        ui.sendBtn.disabled = !hasText && !hasAttachments;
    }
    ui.input.addEventListener('input', () => { autoResize(); refreshSendState(); });
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
    const micBtn = document.getElementById('mic-btn');
    const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognizer = null, recording = false;
    if (SpeechRecognitionImpl) {
        recognizer = new SpeechRecognitionImpl();
        recognizer.continuous = false;
        recognizer.interimResults = false;
        recognizer.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            ui.input.value = (ui.input.value ? ui.input.value + ' ' : '') + transcript;
            autoResize(); refreshSendState(); ui.input.focus();
        };
        recognizer.onend = () => { recording = false; micBtn.classList.remove('recording'); };
        micBtn.addEventListener('click', () => {
            if (recording) { recognizer.stop(); return; }
            recording = true;
            micBtn.classList.add('recording');
            recognizer.start();
        });
    } else {
        micBtn.title = 'Voice input not supported in this browser';
        micBtn.addEventListener('click', () => micBtn.classList.add('recording') || setTimeout(() => micBtn.classList.remove('recording'), 300));
    }

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

        const turnEl = newTurn();
        addUserBubble(turnEl, prompt, selectedMcpServer, attachments);
        currentTurnEl = turnEl;
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
            errEl.innerHTML = `<div class="agent-avatar"><i class="fa-solid fa-triangle-exclamation"></i></div>
                <div class="agent-body"><div class="agent-name">system</div>
                <div class="agent-text"><p>Couldn't reach the node controller. Check that the backend is running.</p></div></div>`;
            turnEl.appendChild(errEl);
            currentTurnEl = null; currentTraceEl = null;
            scrollToBottom(true);
        });
    });
});