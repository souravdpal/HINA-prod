"""
ollama_struct.py
-----------------
Reliable structured JSON generation from local Ollama models.

Highlights over a naive "ask for JSON and regex it out" approach:

  * Uses Ollama's native `format=<json schema>` structured-output support
    when available, so the model is constrained at decode time instead of
    hoping it behaves. Falls back to prompt-only JSON mode for older
    Ollama servers / models that don't honor `format`.
  * Schema can be given three ways: a plain example dict (types inferred),
    a `pydantic.BaseModel` subclass, or a raw JSON-schema dict.
  * Nested dicts/lists, `Optional[...]` fields (via `None` in the example),
    and empty lists (`typing.Any` element type) are all handled.
  * Self-correcting retries: on a parse/validation failure the exact error
    is fed back to the model on the next attempt instead of just
    silently re-asking the same question.
  * Clean dataclass-style result (`StructuredResult`) with the validated
    object, the raw text, attempt count, and elapsed time -- useful for
    logging/observability instead of a bare dict.
  * Works as a library function or a small CLI (`python ollama_struct.py`).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Union

import ollama
from pydantic import BaseModel, ValidationError, create_model

logger = logging.getLogger("ollama_struct")

JsonSchema = Dict[str, Any]
SchemaLike = Union[JsonSchema, Type[BaseModel], Dict[str, Any]]


# ============================================================
# Schema building
# ============================================================

def _infer_type(value: Any) -> Any:
    """Infer a Python/typing annotation from an example value."""
    if value is None:
        return Optional[Any]
    if isinstance(value, bool):
        return bool
    if isinstance(value, dict):
        return _model_from_example(value)
    if isinstance(value, list):
        if not value:
            return List[Any]
        return List[_infer_type(value[0])]  # type: ignore[valid-type]
    if isinstance(value, (int, float, str)):
        return type(value)
    return Any


def _model_from_example(example: Dict[str, Any], name: str = "DynamicModel") -> Type[BaseModel]:
    """
    Build a Pydantic model from an example dict. A `None` value marks the
    field optional (defaults to None); everything else is required.
    """
    fields: Dict[str, Any] = {}
    for key, val in example.items():
        annotation = _infer_type(val)
        if val is None:
            fields[key] = (Optional[annotation], None)
        else:
            fields[key] = (annotation, ...)
    return create_model(name, **fields)  # type: ignore[call-overload]


def _resolve_model(schema: SchemaLike) -> Type[BaseModel]:
    """Normalize any supported schema input into a concrete Pydantic model."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    if isinstance(schema, dict):
        return _model_from_example(schema)
    raise TypeError(
        f"schema must be a dict example or a BaseModel subclass, got {type(schema)!r}"
    )


# ============================================================
# JSON extraction helpers (fallback path)
# ============================================================

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json_text(content: str) -> str:
    """
    Pull the most likely JSON object out of a model response, tolerating
    ```json fenced blocks, leading/trailing prose, and stray whitespace.
    """
    content = content.strip()

    fence_match = _FENCE_RE.search(content)
    if fence_match:
        content = fence_match.group(1).strip()

    obj_match = _JSON_OBJECT_RE.search(content)
    if not obj_match:
        raise ValueError("No JSON object found in the model response.")
    return obj_match.group(0)


# ============================================================
# Result type
# ============================================================

@dataclass
class StructuredResult:
    data: Dict[str, Any]
    model: BaseModel
    raw_text: str
    attempts: int
    elapsed_s: float
    used_native_format: bool
    errors: List[str] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __repr__(self) -> str:  # concise, useful in logs/REPL
        return f"StructuredResult(attempts={self.attempts}, elapsed_s={self.elapsed_s:.2f}, data={self.data!r})"


# ============================================================
# Core API
# ============================================================

def generate_structured(
    model: str,
    query: str,
    schema: SchemaLike,
    *,
    system: Optional[str] = None,
    temperature: float = 0.0,
    max_retries: int = 2,
    use_native_format: bool = True,
    client: Optional["ollama.Client"] = None,
) -> StructuredResult:
    """
    Ask an Ollama model a question and get back JSON that validates
    against `schema`.

    Args:
        model: Ollama model name (e.g. "llama3.1", "qwen2.5", "mistral").
        query: The user's question or instruction.
        schema: One of:
            - an example dict, e.g. {"name": "Ann", "age": 30}
              (types inferred from the example values; use None for an
               optional field)
            - a `pydantic.BaseModel` subclass for full control
        system: Optional system prompt prepended to steer behavior.
        temperature: Sampling temperature. 0.0 is most deterministic.
        max_retries: Extra attempts after the first, each seeded with the
            previous attempt's error so the model can self-correct.
        use_native_format: Try Ollama's `format=<json schema>` structured
            output first (requires a reasonably recent Ollama server).
            Automatically falls back to prompt-based JSON mode if the
            server/model doesn't support it.
        client: Optional pre-configured `ollama.Client` (e.g. pointed at
            a remote host). Defaults to the module-level `ollama` client.

    Returns:
        StructuredResult with the validated data.

    Raises:
        ValueError: if no valid JSON matching the schema could be
            produced within `max_retries + 1` attempts.
    """
    ollama_client = client or ollama
    Model = _resolve_model(schema)
    json_schema = Model.model_json_schema()

    base_messages: List[Dict[str, str]] = []
    if system:
        base_messages.append({"role": "system", "content": system})

    prompt = _build_prompt(query, json_schema, native=use_native_format)
    base_messages.append({"role": "user", "content": prompt})

    started = time.monotonic()
    errors: List[str] = []
    native_worked = False

    for attempt in range(max_retries + 1):
        messages = list(base_messages)
        if errors:
            messages.append({
                "role": "user",
                "content": (
                    "Your previous response was invalid: "
                    f"{errors[-1]}\n"
                    "Reply again with ONLY a corrected JSON object, nothing else."
                ),
            })

        try:
            content, native_worked = _call_model(
                ollama_client, model, messages, json_schema, temperature, use_native_format
            )
            raw_json_text = content if native_worked else _extract_json_text(content)
            data = json.loads(raw_json_text)
            validated = Model(**data)

            return StructuredResult(
                data=validated.model_dump(),
                model=validated,
                raw_text=content,
                attempts=attempt + 1,
                elapsed_s=time.monotonic() - started,
                used_native_format=native_worked,
                errors=errors,
            )

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            err_msg = str(e)
            errors.append(err_msg)
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, max_retries + 1, err_msg)
            if attempt == max_retries:
                raise ValueError(
                    f"Failed to produce valid JSON after {max_retries + 1} attempts. "
                    f"Last error: {err_msg}"
                ) from e

    raise RuntimeError("Unexpected fallthrough in generate_structured retry loop.")


def _build_prompt(query: str, json_schema: JsonSchema, *, native: bool) -> str:
    if native:
        # The schema is passed separately via `format=`, so the prompt
        # just needs to state the task; the server enforces the shape.
        return query
    schema_text = json.dumps(json_schema, indent=2)
    return (
        "You are a JSON generator. Respond with ONLY a single JSON object "
        "that satisfies this JSON Schema, no prose, no markdown fences.\n\n"
        f"JSON SCHEMA:\n{schema_text}\n\n"
        f"USER QUERY:\n{query}\n\n"
        "OUTPUT (valid JSON only):"
    )


def _call_model(
    ollama_client,
    model: str,
    messages: List[Dict[str, str]],
    json_schema: JsonSchema,
    temperature: float,
    use_native_format: bool,
) -> tuple[str, bool]:
    """
    Try native structured output (`format=<schema>`) first; if the server
    rejects that kwarg (older Ollama) or the response isn't well-formed,
    fall back to plain JSON-mode prompting.

    Returns (content, used_native_format).
    """
    if use_native_format:
        try:
            response = ollama_client.chat(
                model=model,
                messages=messages,
                format=json_schema,
                options={"temperature": temperature},
            )
            return response["message"]["content"].strip(), True
        except TypeError:
            # Installed `ollama` package predates the `format=schema` kwarg.
            logger.info("Native structured output not supported by this ollama client; falling back.")
        except Exception as e:  # server-side rejection, unsupported model, etc.
            logger.info("Native structured output failed (%s); falling back to prompt mode.", e)

    response = ollama_client.chat(
        model=model,
        messages=messages,
        format="json",
        options={"temperature": temperature},
    )
    return response["message"]["content"].strip(), False


# ============================================================
# Convenience: define a schema once, reuse it as a typed model
# ============================================================

def structured_model(schema_example: Dict[str, Any], name: str = "DynamicModel") -> Type[BaseModel]:
    """Expose the example->Pydantic-model builder for reuse elsewhere."""
    return _model_from_example(schema_example, name=name)


# ------------------- EXAMPLE USAGE -------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # 1. Schema via example dict (None => optional field)
    schema = {
        "name": "John Doe",
        "age": 30,
        "is_student": False,
        "courses": ["Math", "Science"],
        "address": {
            "city": "New York",
            "zip": 10001,
        },
        "nickname": None,  # optional
    }

    question = "Provide a sample student profile with name, age, student status, courses, and address."

    try:
        result = generate_structured(
            model="llama3.1",  # change to an installed model
            query=question,
            schema=schema,
            temperature=0.1,
        )
        print(f"\u2705 Validated in {result.attempts} attempt(s), {result.elapsed_s:.2f}s, "
              f"native_format={result.used_native_format}")
        print(json.dumps(result.data, indent=2))
    except Exception as e:
        print("\u274c Error:", e)