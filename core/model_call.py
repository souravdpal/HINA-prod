"""
ai_registry.py — Multi-Provider Tiered AI Model Registry & Caller
===================================================================

A single-file orchestration layer across FOUR providers:

    groq        (env keys: api1, api2, api3, api4, api5)
    gemini      (env keys: gem1, gem2)                -> google-genai SDK
    github      (env key : tk)                        -> GitHub Models (PAT)
    sambanova   (env keys: nova1, nova2)               -> OpenAI-compatible REST

Instead of registering models "by provider", every provider is broken into
three TIERS:

    PRO    -> heaviest / smartest models available on that provider
    MID    -> balanced models (good default for code)
    LOW    -> fast/cheap models (chit-chat, MCP/JSON formatting, throwaway calls)

Every model entry knows its own provider (stored as the dict key one level
up), so once the router picks a model it already knows which provider/client
to dispatch to and in which request format.

Modes
-----
    Mode.COMPLEX      -> PRO tier only (hardest reasoning tasks)
    Mode.CODE /
    Mode.CODE_FILES   -> MID tier first, falls back to PRO
    Mode.AGENT         -> MID tier first, falls back to PRO
    Mode.SUMMARIZER    -> LOW tier first, falls back to MID
    Mode.HUMAN          -> LOW tier only  (fast, human chat-style replies)
    Mode.COMMAND        -> LOW tier only  (MCP/tool JSON formatting, groq/flash-lite style)

Failover priority (IMPORTANT, per spec)
----------------------------------------
    1) Change MODEL first (walk the tier's model list, possibly across
       providers) before ever touching API keys.
    2) Only once EVERY model in the candidate list has been tried and
       failed/rate-limited do we rotate to the next API key (for providers
       that have more than one key) and run the whole candidate list again.

SambaNova note
--------------
SambaNova has **no access to production-tier models** on this account, so
its PRO tier is intentionally left empty. It only contributes MID/LOW
candidates.

Usage
-----
    from ai_registry import AICaller, Mode, Format

    ai = AICaller()

    result = ai.call(
        prompt="You are a senior engineer.",
        query="Design a distributed rate limiter.",
        mode=Mode.COMPLEX,
    )
    print(result.text, result.provider, result.model_used)

Requires: `requests` (always), `google-genai` (only if you actually hit a
gemini candidate — imported lazily so the rest of the module works without it).
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
import dataclasses
from enum import Enum
from typing import Any, Optional, Union

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    def load_dotenv(*a, **k):
        return False

logger = logging.getLogger("ai_registry")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[ai_registry] %(levelname)s: %(message)s"))
    logger.addHandler(_h)
logger.setLevel(os.environ.get("AI_CALL_LOG_LEVEL", "INFO"))

# Silence the very chatty underlying libraries (httpx, google-genai, urllib3)
# unless the caller explicitly asks for debug output. These are what were
# printing the "HTTP Request: ... 500" lines you were seeing.
if os.environ.get("AI_CALL_LOG_LEVEL", "INFO").upper() != "DEBUG":
    for _noisy in ("httpx", "httpcore", "google_genai", "google.genai", "urllib3"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class Mode(str, Enum):
    COMPLEX = "complex"          # heavy pro-only reasoning
    SUMMARIZER = "summarizer"
    CODE = "code"
    CODE_FILES = "code_files"
    AGENT = "agent"
    HUMAN = "human"
    COMMAND = "command"          # mcp / tool / json formatting chatter


class Format(str, Enum):
    TEXT = "text"
    JSON = "json"


class Tier(str, Enum):
    PRO = "pro"
    MID = "mid"
    LOW = "low"


# Which tiers get tried, and in what order, per mode.
MODE_TIER_ORDER: dict[Mode, list[Tier]] = {
    Mode.COMPLEX:    [Tier.PRO],
    Mode.CODE:        [Tier.MID, Tier.PRO],
    Mode.CODE_FILES:  [Tier.MID, Tier.PRO],
    Mode.AGENT:        [Tier.MID, Tier.PRO],
    Mode.SUMMARIZER:   [Tier.LOW, Tier.MID],
    Mode.HUMAN:         [Tier.LOW],
    Mode.COMMAND:       [Tier.LOW],
}

# Order providers are tried in, for a given tier (first = highest priority).
PROVIDER_ORDER: list[str] = ["groq", "gemini", "github", "sambanova"]


# --------------------------------------------------------------------------- #
# Model spec + the tiered registry
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class ModelSpec:
    id: str
    provider: str
    tier: Tier
    supports_json_mode: bool = False
    good_for_code: bool = False
    notes: str = ""


class ModelRegistry:
    """
    PROVIDERS[provider_name][tier] -> list[str] of model ids (best first).
    MODELS[model_id] -> ModelSpec (flattened lookup so picking a model id
    always tells you the provider + tier too).
    """

    PROVIDERS: dict[str, dict[Tier, list[str]]] = {
        "groq": {
            Tier.PRO: [
                "llama-3.3-70b-versatile",
                "openai/gpt-oss-120b",
            ],
            Tier.MID: [
                "meta-llama/llama-4-scout-17b-16e-instruct",
                "qwen/qwen3-32b",
            ],
            Tier.LOW: [
                "llama-3.1-8b-instant",
                "openai/gpt-oss-20b",
            ],
        },
        "gemini": {
            Tier.PRO: [
                "gemini-3.0-pro",
            ],
            Tier.MID: [
                "gemini-3.5-flash",
            ],
            Tier.LOW: [
                "gemini-3.5-flash-lite",
            ],
        },
        "github": {
            Tier.PRO: [
                "openai/gpt-4.1",
                "openai/o1",
            ],
            Tier.MID: [
                "meta/Meta-Llama-3.1-70B-Instruct",
                "mistral-ai/Mistral-Large-2411",
            ],
            Tier.LOW: [
                "openai/gpt-4o-mini",
                "microsoft/Phi-4-mini-instruct",
            ],
        },
        "sambanova": {
            Tier.PRO: [],  # NOTE: account has no production-model access on SambaNova
            Tier.MID: [
                "DeepSeek-V3.1",
                "DeepSeek-V3.2",
                "MiniMax-M2.7",
            ],
            Tier.LOW: [
                "Meta-Llama-3.3-70B-Instruct",
                "gpt-oss-120b",
                "gemma-4-31B-it",
            ],
        },
    }

    MODELS: dict[str, ModelSpec] = {}

    @classmethod
    def _build(cls):
        if cls.MODELS:
            return
        json_native = {
            "llama-3.3-70b-versatile", "openai/gpt-oss-120b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "llama-3.1-8b-instant", "openai/gpt-oss-20b",
            "openai/gpt-4.1", "openai/o1", "openai/gpt-4o-mini",
        }
        for provider, tiers in cls.PROVIDERS.items():
            for tier, ids in tiers.items():
                for mid in ids:
                    cls.MODELS[mid] = ModelSpec(
                        id=mid,
                        provider=provider,
                        tier=tier,
                        supports_json_mode=mid in json_native,
                        good_for_code=tier in (Tier.MID, Tier.PRO),
                    )

    @classmethod
    def candidates(cls, mode: Mode) -> list[ModelSpec]:
        """Flattened, priority-ordered candidate list for a mode:
        tier order (per mode) outer loop, provider order inner loop."""
        cls._build()
        out: list[ModelSpec] = []
        for tier in MODE_TIER_ORDER.get(mode, [Tier.LOW]):
            for provider in PROVIDER_ORDER:
                for mid in cls.PROVIDERS.get(provider, {}).get(tier, []):
                    out.append(cls.MODELS[mid])
        return out


# --------------------------------------------------------------------------- #
# Cooldown tracker
# --------------------------------------------------------------------------- #

class CooldownTracker:
    def __init__(self):
        self._until: dict[str, float] = {}

    def mark(self, model_id: str, seconds: float):
        self._until[model_id] = time.time() + max(seconds, 0.5)
        logger.warning(f"Cooling down '{model_id}' for {seconds:.1f}s")

    def is_cooling(self, model_id: str) -> bool:
        exp = self._until.get(model_id)
        return exp is not None and time.time() < exp

    def parse_retry_after(self, headers: dict) -> float:
        ra = headers.get("retry-after")
        if ra:
            try:
                return float(ra)
            except ValueError:
                pass
        for key in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            v = headers.get(key)
            if v:
                secs = self._parse_duration(v)
                if secs is not None:
                    return secs
        return 5.0

    @staticmethod
    def _parse_duration(s: str) -> Optional[float]:
        m = re.match(r"(?:(\d+)m)?([\d.]+)s", s.strip())
        if not m:
            return None
        minutes = float(m.group(1)) if m.group(1) else 0.0
        seconds = float(m.group(2))
        return minutes * 60 + seconds


# --------------------------------------------------------------------------- #
# JSON sanitization
# --------------------------------------------------------------------------- #

class JSONSanitizer:
    FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

    @classmethod
    def extract_and_parse(cls, raw: str) -> Optional[Any]:
        for c in cls._candidates(raw):
            parsed = cls._try_parse(c)
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _candidates(cls, raw: str) -> list[str]:
        raw = raw.strip()
        out = [raw]
        for m in cls.FENCE_RE.finditer(raw):
            out.append(m.group(1).strip())
        span = cls._largest_bracket_span(raw)
        if span:
            out.append(span)
        return out

    @staticmethod
    def _largest_bracket_span(raw: str) -> Optional[str]:
        best = None
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = raw.find(open_c)
            if start == -1:
                continue
            depth = 0
            end = None
            in_str = False
            escape = False
            for i in range(start, len(raw)):
                ch = raw[i]
                if in_str:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == open_c:
                    depth += 1
                elif ch == close_c:
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end is not None:
                candidate = raw[start:end + 1]
                if best is None or len(candidate) > len(best):
                    best = candidate
        return best

    @classmethod
    def _try_parse(cls, s: str) -> Optional[Any]:
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        repaired = cls._repair(s)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _repair(s: str) -> str:
        s = s.strip()
        s = re.sub(r",\s*([}\]])", r"\1", s)
        if s.count('"') < s.count("'"):
            s = re.sub(r"(?<![\\])'", '"', s)
        last_curly = s.rfind("}")
        last_square = s.rfind("]")
        last = max(last_curly, last_square)
        if last != -1:
            s = s[: last + 1]
        s = re.sub(r"//.*?$", "", s, flags=re.MULTILINE)
        s = re.sub(r"(?m)^\s*#.*$", "", s)
        s = re.sub(r"\bNaN\b", "null", s)
        s = re.sub(r"\b-?Infinity\b", "null", s)
        return s


# --------------------------------------------------------------------------- #
# Code-files block parsing (for MCP-style file writing)
# --------------------------------------------------------------------------- #

CODE_FILE_START = "--------start of code------"
CODE_FILE_END = "-----end of code------"
FILE_HEADER_RE = re.compile(r"^#{1,3}\s*FILE:\s*(.+?)\s*$", re.MULTILINE)


def build_code_files_instruction() -> str:
    return (
        "\n\nWhen you produce code, you MUST wrap ALL files between the exact "
        f"markers `{CODE_FILE_START}` and `{CODE_FILE_END}` (each on its own "
        "line, verbatim, no markdown fences around them). Inside that block, "
        "start every file with a line `### FILE: <relative/path/filename.ext>` "
        "followed by the raw file content (no backtick fences). Multiple files "
        "are allowed, each with its own `### FILE:` header. No explanation "
        "inside the block — only marker lines, headers, and raw code."
    )


def parse_code_files(text: str) -> Optional[dict[str, str]]:
    start = text.find(CODE_FILE_START)
    end = text.find(CODE_FILE_END)
    if start == -1 or end == -1 or end <= start:
        return None
    block = text[start + len(CODE_FILE_START): end]
    headers = list(FILE_HEADER_RE.finditer(block))
    if not headers:
        return None
    files: dict[str, str] = {}
    for i, h in enumerate(headers):
        fname = h.group(1).strip()
        content_start = h.end()
        content_end = headers[i + 1].start() if i + 1 < len(headers) else len(block)
        files[fname] = block[content_start:content_end].strip("\n")
    return files


# --------------------------------------------------------------------------- #
# Mode -> system prompt shaping
# --------------------------------------------------------------------------- #

def shape_system_prompt(base_prompt: str, mode: Mode) -> str:
    addenda = {
        Mode.COMPLEX: (
            "\n\nMode: COMPLEX. This is a hard reasoning task — think it through "
            "carefully, check your own logic, and prefer correctness over speed."
        ),
        Mode.SUMMARIZER: (
            "\n\nMode: SUMMARIZER. Be concise and information-dense. No filler, "
            "no restating the question, no meta-commentary."
        ),
        Mode.CODE: (
            "\n\nMode: CODE. Return code in a single fenced block. Give a short "
            "explanation only if it materially helps; otherwise just the code."
        ),
        Mode.CODE_FILES: build_code_files_instruction(),
        Mode.AGENT: (
            "\n\nMode: AGENT. You are one agent in a multi-agent pipeline. "
            "Assume your output may be consumed by another agent or automated "
            "system. Be structured and unambiguous. State assumptions explicitly."
        ),
        Mode.HUMAN: (
            "\n\nMode: HUMAN. Write for a person reading in a chat UI: warm, "
            "natural, and to the point."
        ),
        Mode.COMMAND: (
            "\n\nMode: COMMAND. You are formatting output for an MCP/tool "
            "pipeline. Be fast, terse, and exact — output only what's asked."
        ),
    }
    return base_prompt + addenda.get(mode, "")


def build_injections_block(
    memory: Optional[Union[str, list, dict]] = None,
    agent_injection: Optional[Union[str, dict]] = None,
    retry_injection: Optional[dict] = None,
) -> str:
    parts = []
    if memory:
        mem_str = memory if isinstance(memory, str) else json.dumps(memory, ensure_ascii=False, indent=2)
        parts.append(f"### MEMORY (prior context you should use)\n{mem_str}")
    if agent_injection:
        agent_str = agent_injection if isinstance(agent_injection, str) else json.dumps(agent_injection, ensure_ascii=False, indent=2)
        parts.append(f"### UPSTREAM AGENT OUTPUT\n{agent_str}")
    if retry_injection:
        prev_code = retry_injection.get("previous_code")
        error = retry_injection.get("error", "")
        prev_str = json.dumps(prev_code, ensure_ascii=False, indent=2) if isinstance(prev_code, dict) else str(prev_code or "")
        parts.append(
            "### RETRY — PREVIOUS ATTEMPT FAILED\n"
            f"--- previous code ---\n{prev_str}\n\n--- execution error ---\n{error}\n"
        )
    return "\n\n".join(parts)


def _json_instruction(schema_hint: Optional[Union[dict, str]]) -> str:
    hint = ""
    if schema_hint:
        hint_str = schema_hint if isinstance(schema_hint, str) else json.dumps(schema_hint, indent=2)
        hint = (
            f"\nSchema/shape to follow (the values below are placeholders "
            f"showing type/shape ONLY -- never copy them literally):\n{hint_str}\n\n"
            "RULES:\n"
            "  1. Every value must come from the actual USER QUERY or the "
            "provided data -- never reuse the placeholder text shown above.\n"
            "  2. If a field's placeholder mentions 'query', copy the user's "
            "query into it verbatim -- do not summarize, translate, or replace it.\n"
            "  3. If a field's placeholder says a value must be one of a fixed "
            "set (e.g. 'must be EXACTLY one of: [...]'), use one of those exact "
            "strings and nothing else.\n"
            "  4. Only use values that actually appear in any data provided "
            "above -- never invent a name, id, or field value that isn't in it.\n"
            "  5. If nothing provided actually matches the query, say so using "
            "whatever the schema's 'none' value is (e.g. 'NONE') rather than "
            "guessing a plausible-looking answer.\n"
        )
    return (
        "\n\nOutput format: JSON ONLY. Respond with a single valid JSON value "
        "(object or array). No markdown fences, no prose, no comments, no "
        f"trailing commas.{hint}"
    )


# --------------------------------------------------------------------------- #
# API key pools (.env driven)
# --------------------------------------------------------------------------- #

class KeyPool:
    """Round-robin key rotator reading numbered env vars, e.g. api1..api5."""

    def __init__(self, prefix: str, count: int = 5, extra_first: Optional[str] = None):
        keys = []
        if extra_first:
            keys.append(extra_first)
        for i in range(1, count + 1):
            v = os.environ.get(f"{prefix}{i}")
            if v:
                keys.append(v)
        self.keys = keys
        self.idx = 0

    def current(self) -> Optional[str]:
        return self.keys[self.idx] if self.keys else None

    def rotate(self):
        if self.keys:
            self.idx = (self.idx + 1) % len(self.keys)

    def __len__(self):
        return len(self.keys)


class SingleKey:
    """Wraps a single env-var token (e.g. `tk` for GitHub PAT) with the same
    interface as KeyPool so provider callers don't need to special-case it."""

    def __init__(self, env_name: str):
        v = os.environ.get(env_name)
        self.keys = [v] if v else []
        self.idx = 0

    def current(self) -> Optional[str]:
        return self.keys[0] if self.keys else None

    def rotate(self):
        pass  # nothing to rotate — single token

    def __len__(self):
        return len(self.keys)


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class AIResult:
    ok: bool
    text: str = ""
    data: Any = None
    code_files: Optional[dict[str, str]] = None
    model_used: Optional[str] = None
    provider: Optional[str] = None
    tier: Optional[str] = None
    attempts: list[dict] = dataclasses.field(default_factory=list)
    error: Optional[str] = None
    raw_response: Optional[dict] = None


# --------------------------------------------------------------------------- #
# AICaller
# --------------------------------------------------------------------------- #

class AICaller:

    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    GITHUB_URL = "https://models.github.ai/inference/chat/completions"
    SAMBANOVA_URL = "https://api.sambanova.ai/v1/chat/completions"

    def __init__(
        self,
        temperature: float = 0.4,
        max_tokens: int = 4096,
        request_timeout: int = 60,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout

        self.keypools: dict[str, Any] = {
            "groq": KeyPool("api", count=5),
            "gemini": KeyPool("gem", count=2),
            "github": SingleKey("tk"),
            "sambanova": KeyPool("nova", count=2),
        }
        self.cooldowns = CooldownTracker()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def call(
        self,
        prompt: str,
        query: str,
        mode: Mode = Mode.HUMAN,
        format: Format = Format.TEXT,
        json_schema_hint: Optional[Union[dict, str]] = None,
        memory=None,
        agent_injection=None,
        retry_injection: Optional[dict] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AIResult:
        system_prompt = shape_system_prompt(prompt, mode)
        if format == Format.JSON:
            system_prompt += _json_instruction(json_schema_hint)

        injections = build_injections_block(memory, agent_injection, retry_injection)
        user_content = query + (("\n\n" + injections) if injections else "")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        candidates = ModelRegistry.candidates(mode)
        attempts: list[dict] = []

        # Pass 1: walk every candidate MODEL first (no key rotation yet).
        # Pass 2+: if everything failed, rotate each provider's key pool by
        # one step and re-walk the same candidate list. This encodes the
        # priority "change model before changing api key routes".
        max_key_passes = max((len(p) for p in self.keypools.values() if len(p) > 0), default=1)

        for key_pass in range(max_key_passes):
            if key_pass > 0:
                for pool in self.keypools.values():
                    pool.rotate()
                logger.info(f"All models exhausted — rotating API keys (pass {key_pass + 1})")

            for spec in candidates:
                if self.cooldowns.is_cooling(spec.id):
                    continue

                pool = self.keypools.get(spec.provider)
                if not pool or not pool.current():
                    continue  # no key configured for this provider — skip model

                outcome = self._dispatch(spec, messages, format,
                                          temperature, max_tokens)
                attempts.append(outcome["log"])

                if outcome["status"] == "ok":
                    return self._finalize(outcome, mode, spec, attempts)

                if outcome["status"] == "rate_limited":
                    self.cooldowns.mark(spec.id, outcome.get("cooldown_seconds", 5.0))
                    continue  # next MODEL, not next key — per priority rule

                if outcome["status"] == "json_invalid":
                    # one re-ask on the SAME model before giving up on it
                    retry_messages = messages + [
                        {"role": "assistant", "content": outcome.get("raw_text", "")},
                        {"role": "user", "content": "That was not valid JSON. Return ONLY valid JSON, nothing else."},
                    ]
                    retry_outcome = self._dispatch(spec, retry_messages, format,
                                                    temperature, max_tokens)
                    attempts.append(retry_outcome["log"])
                    if retry_outcome["status"] == "ok":
                        return self._finalize(retry_outcome, mode, spec, attempts)
                    continue  # next model

                # generic error -> next model
                continue

        return AIResult(
            ok=False,
            error="All provider/model/key combinations failed for this mode.",
            attempts=attempts,
        )

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #

    def _dispatch(self, spec: ModelSpec, messages, format, temperature, max_tokens) -> dict:
        if spec.provider == "groq":
            return self._call_openai_style(
                spec, messages, format, temperature, max_tokens,
                url=self.GROQ_URL, key=self.keypools["groq"].current(),
            )
        if spec.provider == "github":
            return self._call_openai_style(
                spec, messages, format, temperature, max_tokens,
                url=self.GITHUB_URL, key=self.keypools["github"].current(),
            )
        if spec.provider == "sambanova":
            return self._call_openai_style(
                spec, messages, format, temperature, max_tokens,
                url=self.SAMBANOVA_URL, key=self.keypools["sambanova"].current(),
            )
        if spec.provider == "gemini":
            return self._call_gemini(spec, messages, format, temperature, max_tokens)

        return {"status": "error", "log": {"model": spec.id, "provider": spec.provider, "error": "unknown_provider"}}

    def _call_openai_style(self, spec: ModelSpec, messages, format, temperature, max_tokens, *, url: str, key: str) -> dict:
        payload = {
            "model": spec.id,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if format == Format.JSON and spec.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.request_timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            # Network-level hiccup — treat like a server error, not fatal.
            return {
                "status": "server_error", "cooldown_seconds": 3.0,
                "log": {"model": spec.id, "provider": spec.provider, "error": f"{type(e).__name__}: {e}"},
            }
        except requests.RequestException as e:
            return {"status": "error", "log": {"model": spec.id, "provider": spec.provider, "error": str(e)}}

        if resp.status_code == 429:
            cooldown = self.cooldowns.parse_retry_after(resp.headers)
            return {
                "status": "rate_limited", "cooldown_seconds": cooldown,
                "log": {"model": spec.id, "provider": spec.provider, "status_code": 429, "cooldown": cooldown},
            }
        if resp.status_code in (500, 502, 503, 504):
            # Transient server-side failure — worth a short cooldown + retry,
            # but not a hard error (don't want to permanently blacklist a
            # perfectly good model just because it hiccuped once).
            return {
                "status": "server_error", "cooldown_seconds": 3.0,
                "log": {"model": spec.id, "provider": spec.provider, "status_code": resp.status_code, "body": resp.text[:300]},
            }
        if resp.status_code == 401 or resp.status_code == 403:
            return {
                "status": "auth_error",
                "log": {"model": spec.id, "provider": spec.provider, "status_code": resp.status_code, "body": resp.text[:300]},
            }
        if resp.status_code >= 400:
            return {
                "status": "error",
                "log": {"model": spec.id, "provider": spec.provider, "status_code": resp.status_code, "body": resp.text[:500]},
            }

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return {"status": "error", "log": {"model": spec.id, "provider": spec.provider, "error": "malformed_response"}}

        return self._format_outcome(spec, text, data, format)

    def _call_gemini(self, spec: ModelSpec, messages, format, temperature, max_tokens, _retry: int = 0) -> dict:
        try:
            from google import genai
        except ImportError:
            return {"status": "error", "log": {"model": spec.id, "provider": "gemini", "error": "google-genai not installed"}}

        key = self.keypools["gemini"].current()
        if not key:
            return {"status": "error", "log": {"model": spec.id, "provider": "gemini", "error": "no api key configured"}}

        system_msg = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user_msg = "\n".join(m["content"] for m in messages if m["role"] != "system")
        full_input = (system_msg + "\n\n" + user_msg).strip()

        try:
            client = genai.Client(api_key=key)
            interaction = client.interactions.create(model=spec.id, input=full_input)
            text = getattr(interaction, "output_text", None)
            if not text:
                return {"status": "error", "log": {"model": spec.id, "provider": "gemini", "error": "empty response"}}
        except Exception as e:
            msg = str(e)
            status_code = self._extract_status_code(e, msg)

            if status_code == 429 or "RESOURCE_EXHAUSTED" in msg.upper():
                return {
                    "status": "rate_limited", "cooldown_seconds": 5.0,
                    "log": {"model": spec.id, "provider": "gemini", "status_code": status_code, "error": msg[:300]},
                }
            if status_code in (401, 403) or "PERMISSION_DENIED" in msg.upper() or "API_KEY_INVALID" in msg.upper():
                return {
                    "status": "auth_error",
                    "log": {"model": spec.id, "provider": "gemini", "status_code": status_code, "error": msg[:300]},
                }
            if status_code in (500, 502, 503, 504) or "DEADLINE_EXCEEDED" in msg.upper() or "UNAVAILABLE" in msg.upper():
                # Transient — retry the SAME model once locally with a short
                # backoff before giving up on it (this is what was causing
                # the double "500 Internal Server Error" you saw: the SDK's
                # own retrying, uncaught). If it still fails, hand back
                # server_error so the caller moves on to the next model.
                if _retry < 1:
                    time.sleep(1.5)
                    return self._call_gemini(spec, messages, format, temperature, max_tokens, _retry=_retry + 1)
                return {
                    "status": "server_error", "cooldown_seconds": 3.0,
                    "log": {"model": spec.id, "provider": "gemini", "status_code": status_code, "error": msg[:300]},
                }
            return {"status": "error", "log": {"model": spec.id, "provider": "gemini", "error": msg[:300]}}

        return self._format_outcome(spec, text, {"raw": "gemini interaction"}, format)

    @staticmethod
    def _extract_status_code(exc: Exception, msg: str) -> Optional[int]:
        """Best-effort extraction of an HTTP status code from a google-genai
        exception, since different SDK versions expose this differently."""
        for attr in ("status_code", "code", "http_status"):
            v = getattr(exc, attr, None)
            if isinstance(v, int):
                return v
        m = re.search(r"\b([45]\d{2})\b", msg)
        if m:
            return int(m.group(1))
        return None

    def _format_outcome(self, spec: ModelSpec, text: str, raw: dict, format: Format) -> dict:
        if format == Format.TEXT:
            return {
                "status": "ok", "text": text, "model": spec.id, "provider": spec.provider, "raw": raw,
                "log": {"model": spec.id, "provider": spec.provider, "status": "ok"},
            }
        parsed = JSONSanitizer.extract_and_parse(text)
        if parsed is None:
            return {
                "status": "json_invalid", "raw_text": text,
                "log": {"model": spec.id, "provider": spec.provider, "status": "json_invalid"},
            }
        return {
            "status": "ok", "text": text, "data": parsed, "model": spec.id, "provider": spec.provider, "raw": raw,
            "log": {"model": spec.id, "provider": spec.provider, "status": "ok"},
        }

    @staticmethod
    def _finalize(outcome: dict, mode: Mode, spec: ModelSpec, attempts: list[dict]) -> AIResult:
        text = outcome.get("text", "")
        code_files = parse_code_files(text) if mode == Mode.CODE_FILES else None
        return AIResult(
            ok=True,
            text=text,
            data=outcome.get("data"),
            code_files=code_files,
            model_used=spec.id,
            provider=spec.provider,
            tier=spec.tier.value,
            attempts=attempts,
            raw_response=outcome.get("raw"),
        )


# --------------------------------------------------------------------------- #
# Smoke test
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    ModelRegistry._build()
    print("=== Registry ===")
    for provider, tiers in ModelRegistry.PROVIDERS.items():
        for tier, ids in tiers.items():
            print(f"{provider:10} {tier.value:4} -> {ids}")

    print("\n=== Mode -> candidate order (model ids only) ===")
    for mode in Mode:
        cand = ModelRegistry.candidates(mode)
        print(f"{mode.value:12}: {[f'{c.provider}:{c.id}' for c in cand]}")

    print("\n=== Key pools loaded (0 means missing env var) ===")
    ai = AICaller()
    for name, pool in ai.keypools.items():
        print(f"{name:10}: {len(pool)} key(s)")

    print("\nJSON sanitizer smoke test:")
    messy = "Sure! Here you go:\n```json\n{'name': 'Mars', 'moons': 2,}\n```\nHope that helps!"
    print(JSONSanitizer.extract_and_parse(messy))