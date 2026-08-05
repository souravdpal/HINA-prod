"""
Thin HTTP client for HINA's persistent Kokoro voice server.

hina_brain.py is spawned fresh per turn by server.js (that's fine —
it's cheap). The problem was that this module used to load the Kokoro
ONNX model *inside* that same short-lived process, so every reply
paid full model-load-from-disk cost before a word could be spoken.

The actual TTS pipeline (language detection, chunking, Kokoro
synthesis, loudness normalization, pushing audio to Node) now lives in
core/voice_server.py — a separate process spawned ONCE by server.js at
startup and kept resident (same pattern server.js already uses for
stt_server.py). This module keeps the exact same public API
hina_brain.py already imports:

    from hin_voice_engine import run_hina_voice
    ...
    run_hina_voice(text=res.text)

so nothing in hina_brain.py needed to change — it just relays the
text over a local HTTP call instead of doing synthesis itself.
"""

import os
import requests

VOICE_SERVER_HOST = os.environ.get("HINA_VOICE_SERVER_HOST", "127.0.0.1")
VOICE_SERVER_PORT = int(os.environ.get("HINA_VOICE_SERVER_PORT", "8766"))
VOICE_SERVER_URL = f"http://{VOICE_SERVER_HOST}:{VOICE_SERVER_PORT}"

# Generous timeout: this call is expected to block for as long as the
# reply actually takes to speak — same blocking contract the old
# in-process version had (it blocked on text_queue.join() /
# audio_queue.join() until every chunk was pushed to the browser).
SPEAK_TIMEOUT_S = float(os.environ.get("HINA_VOICE_SPEAK_TIMEOUT", "180"))


def run_hina_voice(text: str):
    """
    Sends `text` to the resident Kokoro voice server (core/voice_server.py)
    and blocks until it has finished synthesizing and pushing every
    chunk to the browser.

    Fails soft on purpose: if the voice server is down or unreachable,
    this logs a warning and returns instead of raising, so a
    voice-layer problem never takes the rest of hina_brain.py's reply
    pipeline down with it (the text reply / send_state calls in
    hina_brain.py still run normally either way).
    """
    if not text or not text.strip():
        return

    try:
        resp = requests.post(
            f"{VOICE_SERVER_URL}/speak",
            json={"text": text},
            timeout=SPEAK_TIMEOUT_S,
        )
        if resp.status_code != 200:
            print(f"\n[Voice Error] voice_server returned HTTP {resp.status_code}: {resp.text[:200]}")
    except requests.exceptions.ConnectionError:
        print(
            f"\n[Voice Error] Could not reach the voice server at {VOICE_SERVER_URL}. "
            "Is core/voice_server.py running? server.js should spawn it once at "
            "startup (same as stt_server.py) — check the [voice_server] log lines."
        )
    except requests.exceptions.Timeout:
        print(f"\n[Voice Error] voice_server did not finish speaking within {SPEAK_TIMEOUT_S}s.")
    except Exception as e:
        print(f"\n[Voice Error] Failed to reach voice server: {e}")


def shutdown_hina_voice():
    """
    Kept for backward compatibility with any existing call sites /
    atexit hooks. There is no local model or worker thread to tear
    down in this per-turn process anymore — the resident
    voice_server.py process owns that lifecycle now — so this is
    intentionally a no-op.
    """
    pass