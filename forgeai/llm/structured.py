"""Structured (JSON) generation that survives a small, imperfect model.

Pipeline for every structured call:

1. Ask for JSON (server JSON mode where supported) with a compact schema hint.
2. Extract the JSON object even if wrapped in prose or code fences.
3. Apply cheap, safe repairs (trailing commas, Python literals).
4. Validate with Pydantic.
5. On failure, send the validation error back and retry (``json_retries`` times).
6. If still invalid, return the caller-supplied deterministic fallback and mark
   the result ``used_fallback=True`` so it is visible in the run manifest.

Nothing downstream ever receives unvalidated LLM output.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from forgeai.llm.client import LLMClient, Message

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredGenerationError(RuntimeError):
    pass


@dataclass
class StructuredResult(Generic[T]):
    value: T
    attempts: int
    used_fallback: bool = False
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# JSON extraction + repair
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _balanced_spans(text: str):
    """Yield top-level {...} / [...] spans, respecting strings and escapes."""
    openers = {"{": "}", "[": "]"}
    i, n = 0, len(text)
    while i < n:
        if text[i] in openers:
            stack = [openers[text[i]]]
            j, in_str, esc = i + 1, False, False
            while j < n and stack:
                ch = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch in openers:
                    stack.append(openers[ch])
                elif ch == stack[-1]:
                    stack.pop()
                j += 1
            if not stack:
                yield text[i:j]
                i = j
                continue
        i += 1


def _repair(candidate: str) -> str:
    s = _TRAILING_COMMA.sub(r"\1", candidate)
    # Python literals outside of strings are a common small-model slip.
    s = re.sub(r"(?<![\"\w])True(?![\"\w])", "true", s)
    s = re.sub(r"(?<![\"\w])False(?![\"\w])", "false", s)
    s = re.sub(r"(?<![\"\w])None(?![\"\w])", "null", s)
    return s


def extract_json(text: str):
    """Return the first parseable JSON value in ``text``; raise ValueError if none."""
    if not text or not text.strip():
        raise ValueError("empty response")
    candidates: list[str] = []
    candidates += [m.strip() for m in _FENCE.findall(text)]
    candidates.append(text.strip())
    candidates += list(_balanced_spans(text))
    seen: set[str] = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        for attempt in (c, _repair(c)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue
    raise ValueError("no parseable JSON object found in response")


# --------------------------------------------------------------------------- #
# Schema hint
# --------------------------------------------------------------------------- #
def schema_hint(model: type[BaseModel]) -> str:
    """Compact JSON schema; small models follow a short schema better than prose."""
    schema = model.model_json_schema()
    return json.dumps(schema, separators=(",", ":"))


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for e in exc.errors()[:8]:
            loc = ".".join(str(x) for x in e["loc"]) or "<root>"
            parts.append(f"{loc}: {e['msg']}")
        return "; ".join(parts)
    return str(exc)[:500]


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def generate_structured(
    client: LLMClient,
    schema: type[T],
    messages: list[Message],
    *,
    model: str | None = None,
    stage: str = "",
    max_tokens: int = 2000,
    retries: int | None = None,
    fallback: T | Callable[[], T] | None = None,
    validator: Callable[[T], None] | None = None,
) -> StructuredResult[T]:
    """Call the LLM until it returns JSON valid against ``schema``.

    ``validator`` runs semantic checks after schema validation (e.g. "at most 5
    questions"); raise ``ValueError`` from it to trigger a repair retry.
    """
    retries = client.settings.json_retries if retries is None else retries
    sys_hint = {
        "role": "system",
        "content": (
            "Respond with ONE JSON object only. No prose, no markdown fences.\n"
            f"It must validate against this JSON schema:\n{schema_hint(schema)}"
        ),
    }
    convo: list[Message] = [sys_hint, *messages]
    errors: list[str] = []

    for attempt in range(1, retries + 2):
        raw = client.chat(convo, model=model, json_mode=True, max_tokens=max_tokens, stage=stage)
        try:
            data = extract_json(raw)
            value = schema.model_validate(data)
            if validator is not None:
                validator(value)
            return StructuredResult(value=value, attempts=attempt, errors=errors)
        except (ValueError, ValidationError) as exc:
            err = _format_error(exc)
            errors.append(f"attempt {attempt}: {err}")
            log.info("[%s] structured output invalid (attempt %d): %s", stage, attempt, err)
            convo = [
                *convo,
                {"role": "assistant", "content": raw[:4000]},
                {
                    "role": "user",
                    "content": (
                        f"That output was invalid: {err}\n"
                        "Return the corrected JSON object only, matching the schema exactly."
                    ),
                },
            ]

    if fallback is not None:
        value = fallback() if callable(fallback) else fallback
        log.warning("[%s] using deterministic fallback after %d failed attempts", stage, retries + 1)
        return StructuredResult(value=value, attempts=retries + 1, used_fallback=True, errors=errors)
    raise StructuredGenerationError(f"[{stage}] no valid output after {retries + 1} attempts: {errors[-1]}")
