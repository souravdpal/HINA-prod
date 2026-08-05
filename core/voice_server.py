#!/usr/bin/env python3
"""
Persistent Kokoro TTS voice server for HINA.

WHY THIS FILE EXISTS
---------------------
server.js spawns hina_brain.py fresh for every single turn (that's
fine — it's cheap). The problem was that hin_voice_engine.py used to
load the Kokoro ONNX model *inside* that same short-lived process, so
every single reply paid full model-load-from-disk cost before a word
could be spoken. That was the "very very slow" bottleneck.

This script is spawned ONCE by server.js at startup — the exact same
pattern server.js already uses for stt_server.py — keeps the Kokoro
model warm in memory for the life of the Node process, and exposes a
tiny local HTTP API:

    GET  /health           -> {"ready": bool}
    POST /speak             body: {"text": "..."} (JSON)
                             blocks until every chunk has been
                             synthesized AND pushed to Node's
                             /internal/voice_chunk route, then
                             responds. Same blocking contract the old
                             in-process run_hina_voice() had.

hin_voice_engine.py (imported by hina_brain.py) is now just a thin
HTTP client that POSTs text here — see that file's docstring. Nothing
in hina_brain.py needed to change.

Run standalone for testing:
    python3 voice_server.py 8766
"""

import sys
import os
import re
import io
import json
import wave
import queue
import threading
import time
import numpy as np
import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

KOKORO_MODEL_PATH = os.path.join(
    CURRENT_DIR, os.environ.get("HINA_KOKORO_MODEL", "kokoro-v1.0.onnx")
)
KOKORO_VOICES_PATH = os.path.join(
    CURRENT_DIR, os.environ.get("HINA_KOKORO_VOICES", "voices-v1.0.bin")
)

VOICE_MAP = {
    "en": os.environ.get("HINA_VOICE_EN", "af_heart"),
    "hi": os.environ.get("HINA_VOICE_HI", "hf_alpha"),
}
KOKORO_LANG_MAP = {"en": "en-us", "hi": "hi"}
TTS_SPEED = float(os.environ.get("HINA_TTS_SPEED", "1.15"))
TARGET_RMS = float(os.environ.get("HINA_TTS_TARGET_RMS", "0.15"))

NODE_VOICE_PUSH_URL = os.environ.get(
    "HINA_VOICE_PUSH_URL", "http://127.0.0.1:3000/internal/voice_chunk"
)

# Thread-safe queues for the synthesis pipeline (same producer/consumer
# design as before — the only difference is these are now resident for
# the whole server lifetime instead of one-shot per process).
text_queue = queue.Queue()
audio_queue = queue.Queue()

# Only one utterance should be actively synthesizing/pushing at a time
# — HINA is a single-user voice assistant, and overlapping turns would
# just produce garbled interleaved audio in the browser anyway. This
# also protects the queue.join() calls below, which are scoped to
# "the whole queue is empty", not to a single caller's items.
_speak_lock = threading.Lock()

# ------------------------------------------------------------------
# Kokoro model — loaded once, in the background, right at startup.
# ------------------------------------------------------------------
_kokoro = None
_kokoro_lock = threading.Lock()
MODEL_READY = False


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        with _kokoro_lock:
            if _kokoro is None:
                from kokoro_onnx import Kokoro
                print(f"[voice_server] Loading Kokoro model from {KOKORO_MODEL_PATH} ...")
                _kokoro = Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
                print("[voice_server] Kokoro model loaded.")
    return _kokoro


def _load_model_background():
    global MODEL_READY
    try:
        t0 = time.time()
        _get_kokoro()
        MODEL_READY = True
        print(f"[voice_server] Ready. Model load took {time.time() - t0:.2f}s "
              f"(this happens ONCE for the life of this process, not per turn).")
    except Exception as e:
        print(f"[voice_server] FAILED to load Kokoro model: {e}")


# ------------------------------------------------------------------
# Language detection — whole-text / per-segment, NOT first-word guessing
# ------------------------------------------------------------------
_DEVANAGARI_RE = re.compile(r'[\u0900-\u097F]')
_LATIN_RE = re.compile(r'[A-Za-z]')


def _char_lang(ch: str):
    if _DEVANAGARI_RE.match(ch):
        return "hi"
    if _LATIN_RE.match(ch):
        return "en"
    return None


def split_by_script(text: str, min_run_letters: int = 4):
    """Splits `text` into [(segment_text, lang), ...] runs based on the
    script used across the WHOLE string, not the first word. Short
    runs are merged into their neighbour to avoid flapping on a
    single stray character."""
    if not text:
        return []

    tagged = [(ch, _char_lang(ch)) for ch in text]

    last = None
    filled = []
    for ch, lang in tagged:
        if lang is None:
            lang = last
        filled.append([ch, lang])
        if lang is not None:
            last = lang

    nxt = None
    for item in reversed(filled):
        if item[1] is None:
            item[1] = nxt
        else:
            nxt = item[1]

    for item in filled:
        if item[1] is None:
            item[1] = "en"

    runs = []
    cur_lang = filled[0][1]
    cur_chars = [filled[0][0]]
    for ch, lang in filled[1:]:
        if lang == cur_lang:
            cur_chars.append(ch)
        else:
            runs.append((''.join(cur_chars), cur_lang))
            cur_lang = lang
            cur_chars = [ch]
    runs.append((''.join(cur_chars), cur_lang))

    merged = []
    for seg_text, lang in runs:
        letter_count = len(_DEVANAGARI_RE.findall(seg_text)) + len(_LATIN_RE.findall(seg_text))
        if merged and letter_count < min_run_letters:
            prev_text, prev_lang = merged[-1]
            merged[-1] = (prev_text + seg_text, prev_lang)
        else:
            merged.append((seg_text, lang))

    final = []
    for seg_text, lang in merged:
        if final and final[-1][1] == lang:
            final[-1] = (final[-1][0] + seg_text, lang)
        else:
            final.append((seg_text, lang))

    return [(t.strip(), l) for t, l in final if t.strip()]


def detect_language(text: str) -> str:
    devanagari_count = len(_DEVANAGARI_RE.findall(text))
    latin_count = len(_LATIN_RE.findall(text))
    if devanagari_count == 0 and latin_count == 0:
        return "en"
    return "hi" if devanagari_count > latin_count else "en"


# ------------------------------------------------------------------
# Smart, language-aware text chunking
# ------------------------------------------------------------------
MIN_CHUNK_CHARS = 40


def chunk_text_for_tts(text: str, max_chars: int = 420) -> list:
    """Splits by language segment first, then groups sentences up to
    max_chars per segment, then merges any leftover tiny fragment
    (stray list marker, abbreviation, etc.) into a same-language
    neighbour so Kokoro never gets a one-token chunk on its own —
    that's what causes noticeably unstable pitch/volume between
    chunks ("doesn't sound like one voice")."""
    raw_chunks = []
    for segment_text, lang in split_by_script(text):
        sentences = [
            s.strip()
            for s in re.split(r'(?<=[.!?\u0964\u0965\n])\s+', segment_text)
            if s.strip()
        ]
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) <= max_chars:
                current = f"{current} {sentence}".strip()
            else:
                if current:
                    raw_chunks.append((current, lang))
                current = sentence
        if current:
            raw_chunks.append((current, lang))

    if not raw_chunks:
        return raw_chunks

    merged = [raw_chunks[0]]
    for chunk_text_, lang in raw_chunks[1:]:
        prev_text, prev_lang = merged[-1]
        if len(chunk_text_) < MIN_CHUNK_CHARS and lang == prev_lang and len(prev_text) + len(chunk_text_) <= max_chars * 1.5:
            merged[-1] = (f"{prev_text} {chunk_text_}".strip(), prev_lang)
        else:
            merged.append((chunk_text_, lang))

    if len(merged) > 1 and len(merged[0][0]) < MIN_CHUNK_CHARS and merged[0][1] == merged[1][1]:
        first_text, first_lang = merged[0]
        second_text, _ = merged[1]
        merged[1] = (f"{first_text} {second_text}".strip(), first_lang)
        merged.pop(0)

    return merged


def Hina_Speak_Stream(text_block):
    if text_block.strip():
        chunks = chunk_text_for_tts(text_block.strip())
        total = len(chunks)
        # speak() holds _speak_lock for the whole utterance and
        # already waits (queue.join() x2) for the previous utterance
        # to fully drain before starting a new one, so it's safe to
        # reset the sequencer cursor here — there's no previous
        # utterance's chunks still in flight when this runs.
        with _pending_cv:
            _pending_results.clear()
            _next_expected_idx["v"] = 0
        for idx, (chunk, lang) in enumerate(chunks):
            text_queue.put((chunk, lang, idx, total))
        return total
    return 0

# ------------------------------------------------------------------
# <think> Block Stripper
# ------------------------------------------------------------------
def split_think_blocks(raw_text: str):
    blocks = []
    text = raw_text

    while True:
        lowered = text.lower()
        open_idx = lowered.find("<think>")
        if open_idx == -1:
            break
        close_idx = lowered.rfind("</think>")
        if close_idx == -1 or close_idx < open_idx + 7:
            break
        inner = text[open_idx + 7:close_idx]
        blocks.append({"inner": inner, "open": False})
        text = text[:open_idx] + text[close_idx + 8:]

    match = re.search(r"<think>([\s\S]*)$", text, flags=re.IGNORECASE)
    if match:
        blocks.append({"inner": match.group(1), "open": True})
        text = text[:match.start()]

    return text, blocks

# ------------------------------------------------------------------
# Leaked Meta-Reasoning Stripper
# ------------------------------------------------------------------
_META_REASONING_PATTERNS = [
    r"^(ok(ay)?|so|now)?[,.]?\s*(i (will|won't|need to|should|must|can)\b)",
    r"^(the (user|system) (prompt|instruction)|critical conflict|draft construction)",
    r"\bsystem prompt\b",
    r"\bv\d+\.\d+ (persona|constraints?)\b",
    r"^check against constraints",
    r"^\(?(too plain|better,?|mental)\b",
    r"^\d+\.\s*$",
]
_META_REASONING_RE = re.compile("|".join(_META_REASONING_PATTERNS), flags=re.IGNORECASE)

def strip_leaked_reasoning(text: str) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    kept = [s for s in sentences if not _META_REASONING_RE.search(s)]
    return " ".join(kept)


def clean_for_tts(text: str) -> str:
    text, _blocks = split_think_blocks(text)

    # Must run BEFORE strip_leaked_reasoning, while real newlines still
    # exist, so these line-anchored regexes can see line starts.
    # Fixes chunks that "sound like different voices": leaving e.g.
    # "## 1. The Origins" for the sentence splitter let it split right
    # after "1." (it's followed by a period), producing an orphan
    # one-token TTS chunk with unstable prosody/volume.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", " ", text)
    text = re.sub(r"(?m)^\s{0,3}\d{1,3}[.)]\s+", " ", text)
    text = re.sub(r"(?m)^\s{0,3}[-*+]\s+", " ", text)

    text = strip_leaked_reasoning(text)

    text = re.sub(r"%[^%\n]{1,200}?%", " ", text)
    text = re.sub(r"```[\s\S]*?```", " this code ", text)
    text = re.sub(r"`[^`]*`", " this code ", text)
    text = re.sub(r"[*_#`\-+>\n]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ------------------------------------------------------------------
# Synthesis + loudness normalization
# ------------------------------------------------------------------
def _normalize_loudness(samples: np.ndarray, target_rms: float = TARGET_RMS) -> np.ndarray:
    """Kokoro's raw output volume varies noticeably between calls.
    Two back-to-back chunks at different volumes reads as "that's not
    the same voice" even when the speaker embedding never changed."""
    if samples.size == 0:
        return samples
    rms = float(np.sqrt(np.mean(np.square(samples))))
    if rms < 1e-6:
        return samples
    gain = min(target_rms / rms, 4.0)
    return np.clip(samples * gain, -1.0, 1.0)


# ------------------------------------------------------------------
# Parallel synthesis — this is what closes the "gaps that make her
# sound like she stopped talking" problem on long replies.
#
# Before: ONE worker synthesized chunks strictly one-at-a-time. Time
# until chunk N+1 is ready to play = sum of every chunk's synth time
# up to N+1, while the browser only has the playback DURATION of
# chunk N to cover that wait. The moment any chunk (longer sentence,
# a Devanagari run, CPU briefly busy) takes longer to synthesize than
# the previous chunk takes to *play*, audio starves mid-reply.
#
# After: several workers synthesize chunks concurrently (chunks are
# independent of each other, so this is safe), and a sequencer thread
# hands finished chunks to audio_queue strictly in original order
# (0,1,2,...) regardless of which worker finished first. This turns
# "sum of every chunk's synth time" into "max of overlapping synth
# times" for however many run in parallel — the actual fix.
NUM_SYNTH_WORKERS = int(os.environ.get("HINA_TTS_SYNTH_WORKERS", "3"))

_pending_results = {}                     # chunk_idx -> finished result
_pending_cv = threading.Condition()
_next_expected_idx = {"v": 0}             # reset per-utterance in Hina_Speak_Stream

# kokoro_onnx's create() goes through an espeak-ng-based phonemizer
# under the hood, and espeak-ng keeps global, NOT-thread-safe state.
# Calling kokoro.create() from more than one thread at the same time
# doesn't raise — it just hangs or corrupts state, which is exactly
# what produced the 180s timeout / broken pipe. So: multiple worker
# threads are fine (they can decode/prepare independently), but the
# actual call into kokoro must be serialized through this lock. This
# does mean the inference itself is still one-at-a-time — the win
# from the worker pool is that a chunk's queue/dispatch overhead no
# longer stalls behind the previous chunk's full round trip, not true
# parallel inference. If synthesis is still the bottleneck, the real
# fix is a faster/GPU Kokoro build, not more Python threads calling
# into the same non-thread-safe library.
_kokoro_infer_lock = threading.Lock()


def _synthesize_one(text_block, lang, chunk_idx, chunk_total):
    start_calc = time.time()
    try:
        kokoro = _get_kokoro()
        voice = VOICE_MAP.get(lang, VOICE_MAP["en"])
        kokoro_lang = KOKORO_LANG_MAP.get(lang, "en-us")

        with _kokoro_infer_lock:
            samples, sample_rate = kokoro.create(
                text_block, voice=voice, speed=TTS_SPEED, lang=kokoro_lang,
            )
        samples = np.asarray(samples, dtype=np.float32) if samples is not None else None

        if samples is None or len(samples) == 0:
            print(f"\n[TTS Error] Kokoro returned no audio for lang='{lang}'.")
            return (None, None, text_block, 0.0, chunk_idx, chunk_total)

        samples = _normalize_loudness(samples)
        calc_time = time.time() - start_calc
        return (samples, sample_rate, text_block, calc_time, chunk_idx, chunk_total)

    except Exception as e:
        print(f"\n[TTS Error] Kokoro synthesis failed (lang='{lang}'): {e}")
        return (None, None, text_block, 0.0, chunk_idx, chunk_total)


def tts_synthesis_worker():
    """One of NUM_SYNTH_WORKERS parallel workers. Pulls whatever chunk
    is next in text_queue and synthesizes it — multiple chunks are in
    flight across the pool at once. Results land in a shared buffer;
    result_sequencer_worker drains that buffer in strict order so
    playback/push order is unaffected by which worker finishes first."""
    while True:
        item = text_queue.get()
        text_block, lang, chunk_idx, chunk_total = item
        result = _synthesize_one(text_block, lang, chunk_idx, chunk_total)

        with _pending_cv:
            _pending_results[chunk_idx] = result
            _pending_cv.notify_all()

        text_queue.task_done()


def result_sequencer_worker():
    """Drains _pending_results strictly in chunk_idx order and forwards
    each result to audio_queue, one at a time — audio_playback_worker
    still sees a plain in-order stream even though synthesis behind it
    is now parallel and may finish out of order."""
    while True:
        with _pending_cv:
            while _next_expected_idx["v"] not in _pending_results:
                _pending_cv.wait()
            idx = _next_expected_idx["v"]
            result = _pending_results.pop(idx)
            _next_expected_idx["v"] += 1
        audio_queue.put(result)


def _pcm_float_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def push_chunk_to_browser(wav_bytes: bytes, seq: int, final: bool, _retries: int = 2):
    delay = 0.35
    for attempt in range(_retries + 1):
        try:
            resp = requests.post(
                NODE_VOICE_PUSH_URL,
                params={"seq": seq, "final": "1" if final else "0"},
                data=wav_bytes,
                headers={"Content-Type": "audio/wav"},
                timeout=10,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"node returned HTTP {resp.status_code}: {resp.text[:200]}")
            return
        except Exception as e:
            if attempt < _retries:
                print(f"\n[Voice Push Warning] chunk {seq} attempt {attempt + 1} failed ({e}); retrying...")
                time.sleep(delay)
                delay *= 2
            else:
                print(f"\n[Voice Push Error] Failed to deliver chunk {seq} after {_retries + 1} attempts: {e}")


def audio_playback_worker():
    while True:
        chunk = audio_queue.get()
        samples, sample_rate, original_text, calc_time, chunk_idx, chunk_total = chunk
        is_final = (chunk_idx + 1 == chunk_total)
        print(f"\n[Speaking -> browser] -> \"{original_text}\" (chunk {chunk_idx + 1}/{chunk_total})")
        print(f"            (Synthesis took: {calc_time:.3f}s)")

        if samples is not None and len(samples) > 0:
            wav_bytes = _pcm_float_to_wav_bytes(samples, sample_rate)
            push_start = time.time()
            push_chunk_to_browser(wav_bytes, seq=chunk_idx, final=is_final)
            print(f"            (Push to Node took: {time.time() - push_start:.3f}s)")
        elif is_final:
            push_chunk_to_browser(b"", seq=chunk_idx, final=True)

        audio_queue.task_done()


def _join_with_timeout(q: queue.Queue, timeout: float) -> bool:
    """queue.Queue.join() has no timeout param, so poll unfinished_tasks
    instead. Returns True if the queue actually drained, False if the
    deadline hit first — callers should still return normally either
    way (chunks that did finish were already pushed to the browser as
    they completed; this just stops one stuck chunk from hanging the
    whole /speak HTTP response for minutes)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if q.unfinished_tasks == 0:
            return True
        time.sleep(0.05)
    return q.unfinished_tasks == 0


def speak(text: str) -> int:
    """Cleans, chunks, synthesizes, and pushes `text` to the browser.
    Blocks until fully done (bounded — see _join_with_timeout) or a
    safety deadline is hit, whichever comes first. Returns the number
    of chunks spoken."""
    with _speak_lock:
        cleaned = clean_for_tts(text)
        if not cleaned:
            return 0
        dominant = detect_language(cleaned)
        print(f"[voice_server] whole-text dominant language: {dominant}")
        total = Hina_Speak_Stream(cleaned)

        # ~8s/chunk is a generous ceiling for Kokoro even on a slow CPU;
        # scales with how many chunks this reply actually has instead
        # of one fixed number, with a floor so short replies don't wait
        # needlessly long on a genuine failure.
        deadline = max(20.0, total * 8.0)
        if not _join_with_timeout(text_queue, deadline):
            print(f"\n[Voice Timeout] text_queue did not drain within {deadline:.0f}s — returning anyway.")
        if not _join_with_timeout(audio_queue, deadline):
            print(f"\n[Voice Timeout] audio_queue did not drain within {deadline:.0f}s — returning anyway.")
        return total


# ------------------------------------------------------------------
# HTTP API
# ------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[voice_server] {fmt % args}")

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
        if self.path != "/speak":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            text = payload.get("text", "")
        except Exception as e:
            self._send_json(400, {"error": f"bad request: {e}"})
            return

        try:
            n_chunks = speak(text)
            self._send_json(200, {"status": "ok", "chunks": n_chunks})
        except Exception as e:
            print(f"[voice_server] /speak failed: {e}")
            self._send_json(500, {"error": str(e)})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("HINA_VOICE_SERVER_PORT", "8766"))

    threading.Thread(target=_load_model_background, daemon=True).start()
    for _ in range(NUM_SYNTH_WORKERS):
        threading.Thread(target=tts_synthesis_worker, daemon=True).start()
    threading.Thread(target=result_sequencer_worker, daemon=True).start()
    threading.Thread(target=audio_playback_worker, daemon=True).start()
    print(f"[voice_server] {NUM_SYNTH_WORKERS} parallel synthesis workers running.")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[voice_server] Kokoro voice server listening on 127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()