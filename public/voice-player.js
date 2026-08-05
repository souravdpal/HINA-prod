// voice-player.js
//
// ============================================================
// Plays HINA's spoken replies on THIS device — mobile, laptop,
// whatever browser is actually connected — instead of on the
// machine that happens to be running the Python backend.
//
// Piper still synthesizes audio server-side, exactly as before
// (hin_voice_engine.py). The only thing that changed is WHERE the
// audio comes out: each synthesized chunk is POSTed from Python to
// Node, which relays it here over the existing /ws socket as a
// base64 WAV blob ({type:'voice_chunk', seq, final, audio, mime}).
//
// This module decodes and plays chunks strictly in order (seq 0,
// 1, 2, ...), and once the chunk marked final:true has actually
// finished playing on THIS device's speakers, it sends
// {type:'voice_playback_done'} back over the same socket. That is
// the real signal the server uses to flip state back to
// 'listening' and re-arm the mic — replacing the old "guess how
// long the text would take to speak" timer, which had no idea
// what device was actually playing or how long it really took.
//
// Both live.js (full-page voice mode) and app.js (normal chat with
// the voice-reply toggle on) share this one player.
// ============================================================

(function () {
    let audioCtx = null;
    let queue = [];
    let playing = false;
    let turnHasFinalPending = false;

    function ctx() {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        // Browsers suspend AudioContext until a user gesture; the mic
        // button tap that starts a voice turn counts, but resume()
        // defensively in case autoplay policy still has it suspended.
        if (audioCtx.state === 'suspended') {
            audioCtx.resume().catch(() => {});
        }
        return audioCtx;
    }

    function base64ToArrayBuffer(b64) {
        const binary = atob(b64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return bytes.buffer;
    }

    function sendAck(ws) {
        try {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'voice_playback_done' }));
            } else {
                console.warn('[voice-player] socket not open, could not send playback-done ack');
            }
        } catch (err) {
            console.error('[voice-player] failed to send playback-done ack:', err);
        }
    }

    async function playOne(item) {
        if (!item.audio) return; // final-marker-only chunk (nothing was synthesized)
        const arrBuf = base64ToArrayBuffer(item.audio);
        const audioBuffer = await ctx().decodeAudioData(arrBuf);
        await new Promise((resolve, reject) => {
            const src = ctx().createBufferSource();
            src.buffer = audioBuffer;
            src.connect(ctx().destination);
            src.onended = resolve;
            try { src.start(); } catch (err) { reject(err); }
        });
    }

    async function drainQueue(ws) {
        if (playing) return; // a drain loop is already running
        playing = true;
        try {
            while (queue.length) {
                const item = queue.shift();
                try {
                    await playOne(item);
                } catch (err) {
                    console.error(`[voice-player] chunk ${item.seq} failed to play:`, err);
                }
                if (item.final) {
                    turnHasFinalPending = false;
                    sendAck(ws);
                }
            }
        } finally {
            playing = false;
        }
    }

    window.HinaVoicePlayer = {
        // Call this from your /ws onmessage handler whenever
        // data.type === 'voice_chunk'. Pass the live `ws` instance
        // along so the done-ack goes back over the same connection.
        handleChunk(data, ws) {
            queue.push({ audio: data.audio || null, final: !!data.final, seq: data.seq });
            if (data.final) turnHasFinalPending = true;
            drainQueue(ws);
        },

        // Optional: call if you need to hard-stop mid-reply (e.g. user
        // taps mute while HINA is still speaking).
        stopAndClear() {
            queue = [];
            turnHasFinalPending = false;
        }
    };
})();