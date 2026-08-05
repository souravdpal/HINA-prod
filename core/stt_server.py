#!/usr/bin/env python3
"""
Persistent Whisper STT server for HINA.

WHY THIS FILE EXISTS
---------------------
server.js spawns this once per live-voice session (`spawnSttServer()`)
and talks to it over a tiny local HTTP handshake:

    GET  /health        -> {"ready": bool}
    POST /load           loads the Whisper model into memory (idempotent,
                          safe to call while already loaded/loading)
    POST /unload          frees the model from memory
    POST /transcribe      body: raw audio bytes (whatever MediaRecorder
                          produced in the browser — audio/webm;opus by
                          default), Content-Type header set to match.
                          -> {"text": "..."}

This file previously got overwritten with the old Piper TTS pipeline by
mistake (that logic now lives correctly in voice_server.py, which does
Kokoro TTS). This version does STT only, using faster-whisper, and
never touches TTS.

Run standalone for testing:
    python3 stt_server.py 8765
"""

import sys
import os
import io
import json
import time
import threading
import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
# "small" is a good speed/accuracy tradeoff for a live voice assistant
# on CPU; bump to "medium" if you have a GPU (compute_type below
# auto-picks fp16 on CUDA, int8 on CPU) and want noticeably better
# accuracy on Hindi/English code-switched speech, which is what HINA
# actually gets. Override with env vars, no code change needed.
MODEL_SIZE = os.environ.get("HINA_STT_MODEL", "small")
DEVICE = os.environ.get("HINA_STT_DEVICE", "auto")  # "auto" | "cpu" | "cuda"
COMPUTE_TYPE = os.environ.get("HINA_STT_COMPUTE", "")  # "" = auto-pick below
# Hina is bilingual (Hindi/English) — leave LANGUAGE unset so Whisper
# detects per-utterance instead of forcing one language and mangling
# the other.
LANGUAGE = os.environ.get("HINA_STT_LANGUAGE") or None
SAMPLE_RATE = 16000  # what Whisper expects

_model = None
_model_lock = threading.Lock()
_load_thread = None
MODEL_READY = False
MODEL_LOADING = False


def _pick_compute_type() -> str:
    if COMPUTE_TYPE:
        return COMPUTE_TYPE
    try:
        import torch  # optional; only used to probe for a GPU
        if torch.cuda.is_available():
            return "float16"
    except Exception:
        pass
    return "int8"


def _load_model():
    """Actually loads the model. Runs on a background thread so /load
    can return immediately and server.js's waitForSttReady() polls
    /health until this flips MODEL_READY."""
    global _model, MODEL_READY, MODEL_LOADING
    with _model_lock:
        if _model is not None:
            MODEL_READY = True
            MODEL_LOADING = False
            return
        MODEL_LOADING = True
        try:
            from faster_whisper import WhisperModel
            compute_type = _pick_compute_type()
            device = DEVICE
            t0 = time.time()
            print(f"[stt_server] Loading Whisper model '{MODEL_SIZE}' "
                  f"(device={device}, compute_type={compute_type}) ...")
            _model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute_type)
            MODEL_READY = True
            print(f"[stt_server] Ready. Model load took {time.time() - t0:.2f}s "
                  f"(this happens once per session, not per utterance).")
        except Exception as e:
            print(f"[stt_server] FAILED to load Whisper model: {e}")
            MODEL_READY = False
        finally:
            MODEL_LOADING = False


def ensure_loaded_async():
    global _load_thread
    if MODEL_READY or MODEL_LOADING:
        return
    _load_thread = threading.Thread(target=_load_model, daemon=True)
    _load_thread.start()


def unload_model():
    global _model, MODEL_READY
    with _model_lock:
        _model = None
        MODEL_READY = False
    print("[stt_server] Model unloaded, memory freed.")


# ------------------------------------------------------------------
# Audio decode — raw bytes (webm/opus, ogg, wav, whatever the browser
# sent) straight to a mono float32 16kHz numpy array, via PyAV. No
# ffmpeg CLI subprocess needed; PyAV bundles its own ffmpeg libs, and
# decoding in-process (vs. spawning `ffmpeg` per utterance) is what
# keeps turn latency down.
# ------------------------------------------------------------------
def decode_audio_to_pcm(raw_bytes: bytes) -> np.ndarray:
    import av

    container = av.open(io.BytesIO(raw_bytes))
    try:
        stream = next(s for s in container.streams if s.type == "audio")
    except StopIteration:
        raise ValueError("no audio stream found in upload")

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

    pcm_chunks = []
    for frame in container.decode(stream):
        for resampled in resampler.resample(frame):
            arr = resampled.to_ndarray()
            pcm_chunks.append(arr.reshape(-1))

    # flush any buffered samples left in the resampler
    for resampled in resampler.resample(None):
        arr = resampled.to_ndarray()
        pcm_chunks.append(arr.reshape(-1))

    container.close()

    if not pcm_chunks:
        return np.zeros(0, dtype=np.float32)

    pcm_i16 = np.concatenate(pcm_chunks).astype(np.int16)
    return pcm_i16.astype(np.float32) / 32768.0


# ------------------------------------------------------------------
# Transcription
# ------------------------------------------------------------------
def transcribe(raw_bytes: bytes) -> str:
    if _model is None:
        raise RuntimeError("model not loaded — call /load first")

    audio = decode_audio_to_pcm(raw_bytes)
    if audio.size < SAMPLE_RATE * 0.15:  # <150ms — not worth sending to Whisper
        return ""

    segments, _info = _model.transcribe(
        audio,
        language=LANGUAGE,
        beam_size=1,          # greedy — fast, and plenty accurate for
                               # short conversational utterances; bump
                               # to 5 if you want more accuracy and can
                               # spend the extra latency
        vad_filter=True,      # trims leading/trailing/interior silence
                               # before it ever reaches the model —
                               # this is what kills the "long gaps of
                               # dead air get misheard/hallucinated"
                               # problem, not a bigger model
        vad_parameters=dict(min_silence_duration_ms=400),
        condition_on_previous_text=False,  # prevents Whisper's classic
                               # failure mode of repeating/hallucinating
                               # extra text once it drifts on one bad
                               # segment — each utterance here is a
                               # fresh independent turn anyway
        temperature=0.0,
    )

    text = " ".join(seg.text.strip() for seg in segments if seg.text and seg.text.strip())
    return text.strip()


# ------------------------------------------------------------------
# HTTP API
# ------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[stt_server] {fmt % args}")

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ready": MODEL_READY})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/load":
            ensure_loaded_async()
            self._send_json(200, {"status": "loading" if not MODEL_READY else "ready"})
            return

        if self.path == "/unload":
            unload_model()
            self._send_json(200, {"status": "unloaded"})
            return

        if self.path == "/transcribe":
            if not MODEL_READY:
                self._send_json(503, {"error": "model not ready"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b""
                if not raw:
                    self._send_json(400, {"error": "no audio received"})
                    return
            except Exception as e:
                self._send_json(400, {"error": f"bad request: {e}"})
                return

            try:
                t0 = time.time()
                text = transcribe(raw)
                print(f"[stt_server] transcribed in {time.time() - t0:.3f}s -> \"{text}\"")
                self._send_json(200, {"text": text})
            except Exception as e:
                print(f"[stt_server] /transcribe failed: {e}")
                self._send_json(500, {"error": str(e)})
            return

        self._send_json(404, {"error": "not found"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("HINA_STT_SERVER_PORT", "8765"))

    # Start loading immediately at spawn time too (in addition to
    # responding to POST /load) — server.js calls /load right after
    # spawning anyway, but this means a model already sitting in disk
    # cache doesn't cost anything extra either way.
    ensure_loaded_async()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[stt_server] Whisper STT server listening on 127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()