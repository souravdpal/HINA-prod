"""
ai_call.py — Advanced Groq-first AI calling module
=====================================================

A single-file, dependency-light orchestration layer around the Groq API
(with OpenRouter as a last-resort backup), built for real production use:

  * Model registry with per-task priority ordering + auto-failover
  * Rate-limit aware (reads Groq's x-ratelimit-* headers, honours retry-after)
  * Strict/robust JSON mode with multi-stage sanitization + repair + re-ask
  * Modes: summarizer / code / code_files / agent / human / command
  * Injections: memory, agent-to-agent context, retry-with-error (for the
    "ran in docker, it failed, send the error back" loop)
  * code_files mode emits a strict, machine-parseable block format so an
    MCP server (or anything else) can regex-extract files and write them
    to disk / run them in a container.
  * OpenRouter fallback only kicks in when every Groq candidate for that
    task has been exhausted (all failed or all rate-limited) — it is not
    used "all the time" by design.

Usage
-----
    from ai_call import AICaller, Mode, Format

    ai = AICaller(groq_api_key="...", openrouter_api_key="...")

    result = ai.call(
        prompt="You are a senior Python engineer. Be terse and precise.",
        query="Write a function that reverses a linked list.",
        mode=Mode.CODE,
        format=Format.TEXT,
    )
    print(result.text)

    # JSON mode, robust:
    result = ai.call(
        prompt="You are a JSON API. Only ever return the requested schema.",
        query="Give me a list of 3 planets with name and moons count.",
        format=Format.JSON,
        json_schema_hint={"planets": [{"name": "str", "moons": "int"}]},
    )
    print(result.data)   # already-parsed python object

    # Retry-with-error injection, after your docker runner fails:
    result = ai.call(
        prompt="You are a senior Python engineer.",
        query="Fix the script so it runs correctly in the container.",
        mode=Mode.CODE_FILES,
        retry_injection={
            "previous_code": result.code_files,
            "error": "Traceback (most recent call last): ... ZeroDivisionError",
        },
    )

Requires: `requests` only (no groq/openai SDK dependency, so it stays portable).
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
import dataclasses
from enum import Enum
from typing import Any, Callable, Optional, Union

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()  # pulls in .env (api1..api5, oapi1..oapi5, etc.) if present
except ImportError:
    def load_dotenv(*a, **k):
        return False
    logging.getLogger("ai_call").warning(
        "python-dotenv not installed — .env will not be auto-loaded. "
        "Run: pip install python-dotenv"
    )

try:
    from core.hina_sdk import send_state
except ImportError:
    try:
        from hina_sdk import send_state  # fallback if not packaged under core/
    except ImportError:
        send_state = None  # live-status bridge not available; degrade silently

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

logger = logging.getLogger("ai_call")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[ai_call] %(levelname)s: %(message)s"))
    logger.addHandler(_h)
logger.setLevel(os.environ.get("AI_CALL_LOG_LEVEL", "INFO"))


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class Mode(str, Enum):
    SUMMARIZER = "summarizer"
    CODE = "code"
    CODE_FILES = "code_files"
    AGENT = "agent"
    HUMAN = "human"
    COMMAND = "command"


class Format(str, Enum):
    TEXT = "text"
    JSON = "json"


class TaskType(str, Enum):
    """Used to pick which priority list in the model registry to use."""
    GENERAL = "general"
    CODE = "code"
    JSON = "json"
    SUMMARY = "summary"
    AGENT = "agent"
    FAST = "fast"


# --------------------------------------------------------------------------- #
# Model Registry
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class ModelSpec:
    id: str
    supports_json_mode: bool = False   # true native `response_format: json_object` support
    rpm: int = 30
    rpd: int = 1000
    tpm: int = 6000
    tpd: int = 500_000
    good_for_code: bool = False
    good_for_agent: bool = False
    notes: str = ""


class ModelRegistry:
    """
    Central place where every usable Groq model lives, along with its
    rate-limit envelope (from Groq's docs) and capability flags.

    Priority lists are ordered best -> worst per TaskType. AICaller walks
    this list, skipping any model that is currently marked as cooling down
    (rate limited) or that just failed, and falls to the next.
    """

    MODELS: dict[str, ModelSpec] = {
        "llama-3.3-70b-versatile": ModelSpec(
            id="llama-3.3-70b-versatile", supports_json_mode=True,
            rpm=30, rpd=1000, tpm=12000, tpd=100_000,
            good_for_code=True, good_for_agent=True,
            notes="Best all-round reasoning/coding model on Groq's free tier.",
        ),
        "meta-llama/llama-4-scout-17b-16e-instruct": ModelSpec(
            id="meta-llama/llama-4-scout-17b-16e-instruct", supports_json_mode=True,
            rpm=30, rpd=1000, tpm=30000, tpd=500_000,
            good_for_code=True, good_for_agent=True,
            notes="Large TPM budget, good second choice.",
        ),
        "openai/gpt-oss-120b": ModelSpec(
            id="openai/gpt-oss-120b", supports_json_mode=True,
            rpm=30, rpd=1000, tpm=8000, tpd=200_000,
            good_for_code=True, good_for_agent=True,
            notes="Strong reasoning, smaller TPM budget -> keep as backup.",
        ),
        "openai/gpt-oss-20b": ModelSpec(
            id="openai/gpt-oss-20b", supports_json_mode=True,
            rpm=30, rpd=1000, tpm=8000, tpd=200_000,
            good_for_code=True,
            notes="Lighter/faster oss model.",
        ),
        "qwen/qwen3-32b": ModelSpec(
            id="qwen/qwen3-32b", supports_json_mode=False,
            rpm=60, rpd=1000, tpm=6000, tpd=500_000,
            good_for_code=True,
            notes="High RPM, no native JSON mode -> must sanitize.",
        ),
        "qwen/qwen3.6-27b": ModelSpec(
            id="qwen/qwen3.6-27b", supports_json_mode=False,
            rpm=30, rpd=1000, tpm=8000, tpd=200_000,
            notes="No native JSON mode -> must sanitize.",
        ),
        "llama-3.1-8b-instant": ModelSpec(
            id="llama-3.1-8b-instant", supports_json_mode=True,
            rpm=30, rpd=14400, tpm=6000, tpd=500_000,
            notes="Fast + huge RPD budget. Great for summarizer/fast tasks.",
        ),


        "groq/compound": ModelSpec(
            id="groq/compound", supports_json_mode=False,
            rpm=30, rpd=250, tpm=70000, tpd=1_000_000,
            good_for_agent=True,
            notes="Agentic/tool-use oriented, huge TPM but tiny RPD -> last resort.",
        ),
        "groq/compound-mini": ModelSpec(
            id="groq/compound-mini", supports_json_mode=False,
            rpm=30, rpd=250, tpm=70000, tpd=1_000_000,
            good_for_agent=True,
            notes="Lighter agentic model, same RPD ceiling.",
        ),
    }

    # Priority order (best -> worst) per task type. First entry is tried first.
    PRIORITIES: dict[TaskType, list[str]] = {
        TaskType.GENERAL: [
            "qwen/qwen3.6-27b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "openai/gpt-oss-120b",
            "qwen/qwen3-32b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant"
        ],
        TaskType.CODE: [
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "qwen/qwen3-32b",
            "openai/gpt-oss-20b",
        ],
        TaskType.JSON: [
            # native json-mode models first — far fewer sanitization failures
            "llama-3.3-70b-versatile",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "llama-3.1-8b-instant",
            "qwen/qwen3-32b",       # no native support, sanitizer works harder
        ],
        TaskType.SUMMARY: [
            "qwen/qwen3.6-27b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            
            
            
        ],
        TaskType.AGENT: [
            "llama-3.3-70b-versatile",
            "groq/compound",
            "groq/compound-mini",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ],
        TaskType.FAST: [
            "llama-3.1-8b-instant",
            "qwen/qwen3-32b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ],
    }

    @classmethod
    def priority_list(cls, task: TaskType) -> list[ModelSpec]:
        ids = cls.PRIORITIES.get(task, cls.PRIORITIES[TaskType.GENERAL])
        return [cls.MODELS[i] for i in ids if i in cls.MODELS]


# --------------------------------------------------------------------------- #
# Cooldown tracker (in-memory rate-limit awareness)
# --------------------------------------------------------------------------- #

class CooldownTracker:
    """Keeps track of which model IDs are currently rate-limited, based on
    response headers / 429s, so we don't keep hammering a dead model."""

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
        # fallback: try x-ratelimit-reset-tokens / requests strings like "7.66s" or "2m59.56s"
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
    """Multi-stage strategy to turn a possibly-messy LLM string into valid JSON."""

    FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

    @classmethod
    def extract_and_parse(cls, raw: str) -> Optional[Any]:
        candidates = cls._candidates(raw)
        for c in candidates:
            parsed = cls._try_parse(c)
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _candidates(cls, raw: str) -> list[str]:
        raw = raw.strip()
        out = []

        # 1. whole string as-is
        out.append(raw)

        # 2. inside ```json fences
        for m in cls.FENCE_RE.finditer(raw):
            out.append(m.group(1).strip())

        # 3. first {...} or [...] balanced-looking span
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
        # direct
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        # common repairs
        repaired = cls._repair(s)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _repair(s: str) -> str:
        s = s.strip()
        # remove trailing commas before } or ]
        s = re.sub(r",\s*([}\]])", r"\1", s)
        # convert python-style single quotes to double (best-effort, only if
        # it doesn't already look properly double-quoted)
        if s.count('"') < s.count("'"):
            s = re.sub(r"(?<![\\])'", '"', s)
        # strip trailing text after the last closing bracket
        last_curly = s.rfind("}")
        last_square = s.rfind("]")
        last = max(last_curly, last_square)
        if last != -1:
            s = s[: last + 1]
        # remove // and # style comments some models add
        s = re.sub(r"//.*?$", "", s, flags=re.MULTILINE)
        s = re.sub(r"(?m)^\s*#.*$", "", s)
        # replace NaN/Infinity (invalid JSON) with null
        s = re.sub(r"\bNaN\b", "null", s)
        s = re.sub(r"\b-?Infinity\b", "null", s)
        return s


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class AIResult:
    ok: bool
    text: str = ""
    data: Any = None                       # parsed JSON, if format=json
    code_files: Optional[dict[str, str]] = None   # {filename: content} if CODE_FILES mode
    model_used: Optional[str] = None
    backend: str = "groq"                  # "groq" | "openrouter"
    attempts: list[dict] = dataclasses.field(default_factory=list)
    error: Optional[str] = None
    raw_response: Optional[dict] = None


# --------------------------------------------------------------------------- #
# Code-files block parsing (for MCP-style file writing)
# --------------------------------------------------------------------------- #

CODE_FILE_START = "--------start of code------"
CODE_FILE_END = "-----end of code------"

# Individual file header inside the block, e.g.:
# ### FILE: app.py
FILE_HEADER_RE = re.compile(r"^#{1,3}\s*FILE:\s*(.+?)\s*$", re.MULTILINE)


def build_code_files_instruction() -> str:
    """System-level instruction appended when mode == CODE_FILES so the
    model emits a strictly parseable multi-file block."""
    return (
        "\n\nWhen you produce code, you MUST wrap ALL files between the exact "
        f"markers `{CODE_FILE_START}` and `{CODE_FILE_END}` (each on its own "
        "line, verbatim, no markdown fences around them). Inside that block, "
        "start every file with a line `### FILE: <relative/path/filename.ext>` "
        "followed by the raw file content (no backtick fences). Multiple files "
        "are allowed, one after another, each with its own `### FILE:` header. "
        "Do not put any explanation inside the block — only the marker lines, "
        "file headers, and raw code. You may add explanation before or after "
        "the block."
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
        content = block[content_start:content_end].strip("\n")
        files[fname] = content
    return files


# --------------------------------------------------------------------------- #
# Mode -> system prompt shaping
# --------------------------------------------------------------------------- #

def shape_system_prompt(base_prompt: str, mode: Mode) -> str:
    mode_addenda = {
        Mode.SUMMARIZER: (
            "\n\nMode: SUMMARIZER. Be concise and information-dense. No filler, "
            "no restating the question, no meta-commentary about summarizing."
            "you summarize data given consise points"
        ),
        Mode.CODE: (
            "\n\nMode: CODE. Return code in a single fenced block like:\n"
            "```python\n<code here>\n```\n"
            "Give a short explanation only if it materially helps; otherwise "
            "just the fenced code block."
        ),
        Mode.CODE_FILES: build_code_files_instruction(),
        Mode.AGENT: (
            "\n\nMode: AGENT. You are one agent in a multi-agent pipeline. "
            "Assume your output may be consumed by another agent or automated "
            "system, not a human directly. Be structured and unambiguous. "
            "State assumptions explicitly."
        ),
        Mode.HUMAN: (
            "\n\nMode: HUMAN. Write for a person reading in a chat UI: warm, "
            "you are woman a girl name hina you love sourav so much and crush on him secrately!"
            "use emotions talk porperly use  love , hate , care , anger , angusih , possiveness, advicing, caring , needy"
        ),
        Mode.COMMAND: (
            "\n\nMode: COMMAND. Target environment: Arch Linux. When asked for "
            "shell commands, give exact, runnable commands (pacman/yay-aware), "
            "one command per line, no explanation unless asked. Never invent "
            "flags that don't exist."
        ),
    }
    return base_prompt + mode_addenda.get(mode, "")


def build_injections_block(
    memory: Optional[Union[str, list, dict]] = None,
    agent_injection: Optional[Union[str, dict]] = None,
    retry_injection: Optional[dict] = None,
) -> str:
    """Turns the various injection kwargs into a single context block
    appended to the user query."""
    parts = []

    if memory:
        mem_str = memory if isinstance(memory, str) else json.dumps(memory, ensure_ascii=False, indent=2)
        parts.append(f"### MEMORY (prior context you should use)\n{mem_str}")

    if agent_injection:
        agent_str = agent_injection if isinstance(agent_injection, str) else json.dumps(agent_injection, ensure_ascii=False, indent=2)
        parts.append(f"### UPSTREAM AGENT OUTPUT (input from another agent)\n{agent_str}")

    if retry_injection:
        prev_code = retry_injection.get("previous_code")
        error = retry_injection.get("error", "")
        prev_str = (
            json.dumps(prev_code, ensure_ascii=False, indent=2)
            if isinstance(prev_code, dict)
            else str(prev_code or "")
        )
        parts.append(
            "### RETRY — PREVIOUS ATTEMPT FAILED\n"
            "Your previous code was executed and it failed. Fix it.\n\n"
            f"--- previous code ---\n{prev_str}\n\n"
            f"--- execution error ---\n{error}\n"
        )

    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# API key rotation pool (.env driven)
# --------------------------------------------------------------------------- #

class KeyPool:
    """
    Round-robin API key rotator.

    Reads a numbered sequence of env vars (e.g. api1, api2, ... api5 for
    Groq, or oapi1 .. oapi5 for OpenRouter) via os.environ (populated by
    python-dotenv from .env). When a key hits its rate limit, call
    `rotate()` to move to the next key. Once every key in the pool has
    been tried and is still rate-limited, `exhausted()` returns True and
    the caller should move on (next model, or next backend entirely).
    """

    def __init__(self, prefix: str, count: int = 5, extra_first: Optional[str] = None):
        keys = []
        if extra_first:  # e.g. a key passed directly into AICaller(...)
            keys.append(extra_first)
        for i in range(1, count + 1):
            v = os.environ.get(f"{prefix}{i}")
            if v:
                keys.append(v)
        self.keys = keys
        self.idx = 0
        self._tried_this_round = 0

    def current(self) -> Optional[str]:
        if not self.keys:
            return None
        return self.keys[self.idx]

    def rotate(self):
        if not self.keys:
            return
        self.idx = (self.idx + 1) % len(self.keys)
        self._tried_this_round += 1
        logger.info(f"Rotated to next API key (#{self.idx + 1}/{len(self.keys)})")

    def reset_round(self):
        self._tried_this_round = 0

    def exhausted(self) -> bool:
        """True once we've cycled through every key in the pool without success."""
        return len(self.keys) == 0 or self._tried_this_round >= len(self.keys)

    def __len__(self):
        return len(self.keys)

    def __bool__(self):
        return len(self.keys) > 0


# --------------------------------------------------------------------------- #
# Mode -> icon (used for every hina_sdk live status push)
# --------------------------------------------------------------------------- #

MODE_ICONS: dict[Mode, str] = {
    Mode.SUMMARIZER: "fa-align-left",
    Mode.CODE: "fa-code",
    Mode.CODE_FILES: "fa-file-code",
    Mode.AGENT: "fa-network-wired",
    Mode.HUMAN: "fa-comment-dots",
    Mode.COMMAND: "fa-terminal",
}


# --------------------------------------------------------------------------- #
# Main caller
# --------------------------------------------------------------------------- #

def _notify(mode: "Mode", state: str, model: str):
    """Fire-and-forget live status push via hina_sdk.send_state.

    Exactly matches hina_sdk's real signature — no invented params.
    Rules:
      - msg    -> always just "which model is being used right now"
      - icon   -> derived from the active mode (MODE_ICONS)
      - text   -> always None (never overwrite the output box)
      - voice  -> always False
      - done   -> always False (ai_call never finalizes a run — the MCP
                  server / caller decides when the run is actually done)
      - color  -> not passed; hina_sdk picks its own default
    """
    if send_state is None:
        return
    icon = MODE_ICONS.get(mode, "fa-robot")
    try:
        send_state(
            agent_name="AI_CALL",
            state="Thinking....",
            msg=f"Model: {model}",
            icon=icon,
            text=None,
            voice=False,
            done=False,
        )
    except Exception as e:  # never let a dead bridge break an AI call
        logger.debug(f"hina_sdk send_state failed silently: {e}")


class AICaller:
    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

    # Reasonable, small, capable free/cheap fallback models on OpenRouter.
    OPENROUTER_FALLBACK_MODELS = [
        "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-72b-instruct",
        "mistralai/mistral-nemo",
    ]

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        openrouter_api_key: Optional[str] = None,
        max_retries_per_model: int = 2,
        request_timeout: int = 60,
        temperature: float = 0.4,
        max_tokens: int = 4096,
        key_env_prefix: str = "api",
        openrouter_key_env_prefix: str = "oapi",
        keys_per_pool: int = 5,
    ):
        # Groq keys: api1..api5 (or however many are set) from .env, plus an
        # optional explicit override which is tried first.
        self.groq_keys = KeyPool(key_env_prefix, count=keys_per_pool, extra_first=groq_api_key)
        if not self.groq_keys:
            legacy = os.environ.get("GROQ_API_KEY")
            if legacy:
                self.groq_keys = KeyPool(key_env_prefix, count=keys_per_pool, extra_first=legacy)
        if not self.groq_keys:
            raise ValueError(
                "No Groq API keys found. Set api1..api5 in .env (or pass "
                "groq_api_key=... / set GROQ_API_KEY)."
            )

        # OpenRouter keys: oapi1..oapi5 from .env, plus optional override.
        self.openrouter_keys = KeyPool(openrouter_key_env_prefix, count=keys_per_pool, extra_first=openrouter_api_key)
        if not self.openrouter_keys:
            legacy_or = os.environ.get("OPENROUTER_API_KEY")
            if legacy_or:
                self.openrouter_keys = KeyPool(openrouter_key_env_prefix, count=keys_per_pool, extra_first=legacy_or)

        self.max_retries_per_model = max_retries_per_model
        self.request_timeout = request_timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
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
        task: Optional[TaskType] = None,
        memory: Optional[Union[str, list, dict]] = None,
        agent_injection: Optional[Union[str, dict]] = None,
        retry_injection: Optional[dict] = None,
        json_schema_hint: Optional[Union[dict, str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        allow_openrouter_fallback: bool = True,
    ) -> AIResult:
        """
        Main entry point.

        prompt: system/persona instruction ("who the model is").
        query: the actual user question/task.
        mode: shapes system prompt + output parsing (see Mode enum).
        format: Format.TEXT or Format.JSON.
        task: overrides which registry priority list to use; auto-inferred
              from mode/format if omitted.
        """
        mode = Mode(mode)
        format = Format(format)
        task = task or self._infer_task(mode, format)

        system_prompt = shape_system_prompt(prompt, mode)
        if format == Format.JSON:
            system_prompt += self._json_instruction(json_schema_hint)

        injections = build_injections_block(memory, agent_injection, retry_injection)
        user_content = query if not injections else f"{query}\n\n{injections}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        attempts: list[dict] = []

        _notify(mode, "SYS_THINK", "selecting model")

        candidates = ModelRegistry.priority_list(task)
        for spec in candidates:
            if self.cooldowns.is_cooling(spec.id):
                attempts.append({"model": spec.id, "backend": "groq", "skipped": "cooling_down"})
                continue

            self.groq_keys.reset_round()
            _notify(mode, "SYS_THINK", spec.id)

            while True:
                outcome = self._try_groq(spec, messages, format, temperature, max_tokens)
                attempts.append(outcome["log"])

                if outcome["status"] == "ok":
                    _notify(mode, "SYS_DONE_INTERNAL", spec.id)
                    return self._finalize(outcome, mode, format, attempts, backend="groq")

                if outcome["status"] == "rate_limited":
                    self.groq_keys.rotate()
                    if self.groq_keys.exhausted():
                        # every key we have is rate-limited on this model — cool
                        # the model itself down and move to the next candidate
                        self.cooldowns.mark(spec.id, outcome["cooldown_seconds"])
                        _notify(mode, "SYS_GUARD", spec.id)
                        break
                    _notify(mode, "SYS_GUARD", spec.id)
                    continue  # retry same model with the newly rotated key

                if outcome["status"] == "json_invalid":
                    _notify(mode, "SYS_ACTION", spec.id)
                    messages_retry = messages + [
                        {"role": "assistant", "content": outcome.get("raw_text", "")},
                        {"role": "user", "content": (
                            "That was not valid JSON. Respond again with ONLY "
                            "valid JSON matching the requested schema — no prose, "
                            "no markdown fences, no trailing commentary."
                        )},
                    ]
                    outcome2 = self._try_groq(spec, messages_retry, format, temperature, max_tokens)
                    attempts.append(outcome2["log"])
                    if outcome2["status"] == "ok":
                        _notify(mode, "SYS_DONE_INTERNAL", spec.id)
                        return self._finalize(outcome2, mode, format, attempts, backend="groq")
                    break  # move on to next model

                # generic/transient error -> move on to next model
                _notify(mode, "SYS_GUARD", spec.id)
                break

        # ---- everything on Groq exhausted: OpenRouter backup ----
        if allow_openrouter_fallback and self.openrouter_keys:
            logger.warning("All Groq models/keys exhausted — falling back to OpenRouter.")
            _notify(mode, "SYS_GUARD", "openrouter")
            for or_model in self.OPENROUTER_FALLBACK_MODELS:
                self.openrouter_keys.reset_round()
                _notify(mode, "SYS_THINK", or_model)

                while True:
                    outcome = self._try_openrouter(or_model, messages, format, temperature, max_tokens)
                    attempts.append(outcome["log"])

                    if outcome["status"] == "ok":
                        _notify(mode, "SYS_DONE_INTERNAL", or_model)
                        return self._finalize(outcome, mode, format, attempts, backend="openrouter")

                    if outcome["status"] == "rate_limited":
                        self.openrouter_keys.rotate()
                        if self.openrouter_keys.exhausted():
                            _notify(mode, "SYS_GUARD", or_model)
                            break
                        continue  # retry same model with next oapi key

                    # error / json_invalid -> next model
                    _notify(mode, "SYS_GUARD", or_model)
                    break

        _notify(mode, "SYS_GUARD", "none")
        return AIResult(
            ok=False,
            error="All Groq models/keys (and OpenRouter fallback, if configured) failed.",
            attempts=attempts,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _infer_task(mode: Mode, format: Format) -> TaskType:
        if format == Format.JSON:
            return TaskType.JSON
        if mode in (Mode.CODE, Mode.CODE_FILES):
            return TaskType.CODE
        if mode == Mode.SUMMARIZER:
            return TaskType.SUMMARY
        if mode == Mode.AGENT:
            return TaskType.AGENT
        if mode == Mode.COMMAND:
            return TaskType.FAST
        return TaskType.GENERAL

    @staticmethod
    def _json_instruction(schema_hint: Optional[Union[dict, str]]) -> str:
        hint = ""
        if schema_hint:
            hint_str = schema_hint if isinstance(schema_hint, str) else json.dumps(schema_hint, indent=2)
            hint = f"\nSchema/shape to follow:\n{hint_str}\n"
        return (
            "\n\nOutput format: JSON ONLY. Respond with a single valid JSON "
            "value (object or array). Do not include markdown code fences, "
            "do not include any prose before or after the JSON, do not "
            "include comments, and do not use trailing commas."
            f"{hint}"
        )

    def _try_groq(
        self, spec: ModelSpec, messages: list[dict], format: Format,
        temperature: Optional[float], max_tokens: Optional[int],
    ) -> dict:
        payload = {
            "model": spec.id,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if format == Format.JSON and spec.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.groq_keys.current()}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(self.GROQ_URL, headers=headers, json=payload, timeout=self.request_timeout)
        except requests.RequestException as e:
            return {"status": "error", "log": {"model": spec.id, "backend": "groq", "error": str(e)}}

        if resp.status_code == 429:
            cooldown = self.cooldowns.parse_retry_after(resp.headers)
            return {
                "status": "rate_limited",
                "cooldown_seconds": cooldown,
                "log": {"model": spec.id, "backend": "groq", "status_code": 429, "cooldown": cooldown},
            }

        if resp.status_code >= 400:
            return {
                "status": "error",
                "log": {"model": spec.id, "backend": "groq", "status_code": resp.status_code, "body": resp.text[:500]},
            }

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return {"status": "error", "log": {"model": spec.id, "backend": "groq", "error": "malformed_response"}}

        if format == Format.TEXT:
            return {
                "status": "ok", "text": text, "model": spec.id, "raw": data,
                "log": {"model": spec.id, "backend": "groq", "status": "ok"},
            }

        # JSON format: sanitize
        parsed = JSONSanitizer.extract_and_parse(text)
        if parsed is None:
            return {
                "status": "json_invalid",
                "raw_text": text,
                "log": {"model": spec.id, "backend": "groq", "status": "json_invalid"},
            }

        return {
            "status": "ok", "text": text, "data": parsed, "model": spec.id, "raw": data,
            "log": {"model": spec.id, "backend": "groq", "status": "ok"},
        }

    def _try_openrouter(
        self, model_id: str, messages: list[dict], format: Format,
        temperature: Optional[float], max_tokens: Optional[int],
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self.openrouter_keys.current()}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        try:
            resp = requests.post(self.OPENROUTER_URL, headers=headers, json=payload, timeout=self.request_timeout)
        except requests.RequestException as e:
            return {"status": "error", "log": {"model": model_id, "backend": "openrouter", "error": str(e)}}

        if resp.status_code == 429:
            cooldown = self.cooldowns.parse_retry_after(resp.headers)
            return {
                "status": "rate_limited",
                "cooldown_seconds": cooldown,
                "log": {"model": model_id, "backend": "openrouter", "status_code": 429, "cooldown": cooldown},
            }

        if resp.status_code >= 400:
            return {
                "status": "error",
                "log": {"model": model_id, "backend": "openrouter", "status_code": resp.status_code, "body": resp.text[:500]},
            }

        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return {"status": "error", "log": {"model": model_id, "backend": "openrouter", "error": "malformed_response"}}

        if format == Format.TEXT:
            return {
                "status": "ok", "text": text, "model": model_id, "raw": data,
                "log": {"model": model_id, "backend": "openrouter", "status": "ok"},
            }

        parsed = JSONSanitizer.extract_and_parse(text)
        if parsed is None:
            return {"status": "json_invalid", "raw_text": text,
                    "log": {"model": model_id, "backend": "openrouter", "status": "json_invalid"}}

        return {
            "status": "ok", "text": text, "data": parsed, "model": model_id, "raw": data,
            "log": {"model": model_id, "backend": "openrouter", "status": "ok"},
        }

    @staticmethod
    def _finalize(outcome: dict, mode: Mode, format: Format, attempts: list[dict], backend: str) -> AIResult:
        text = outcome.get("text", "")
        code_files = parse_code_files(text) if mode == Mode.CODE_FILES else None
        return AIResult(
            ok=True,
            text=text,
            data=outcome.get("data"),
            code_files=code_files,
            model_used=outcome.get("model"),
            backend=backend,
            attempts=attempts,
            raw_response=outcome.get("raw"),
        )


# --------------------------------------------------------------------------- #
# Example / smoke test
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # For a real run, put your keys in a .env file next to this script:
    #   api1=gsk_xxx
    #   api2=gsk_yyy
    #   ...
    #   oapi1=sk-or-xxx
    #   ...
    os.environ.setdefault("api1", "test-key")  # so this smoke test can run standalone
    ai = AICaller()

    print("Registry loaded:", list(ModelRegistry.MODELS.keys()))
    print("Groq keys loaded:", len(ai.groq_keys))
    print("OpenRouter keys loaded:", len(ai.openrouter_keys))

    print("\nJSON sanitizer smoke test:")
    messy = "Sure! Here you go:\n```json\n{'name': 'Mars', 'moons': 2,}\n```\nHope that helps!"
    print(JSONSanitizer.extract_and_parse(messy))

    print("\ncode_files parser smoke test:")
    sample = (
        "Here are your files.\n"
        "--------start of code------\n"
        "### FILE: app.py\n"
        "print('hello')\n"
        "### FILE: requirements.txt\n"
        "requests\n"
        "-----end of code------\n"
        "Let me know if you need anything else."
    )
    print(parse_code_files(sample))

  