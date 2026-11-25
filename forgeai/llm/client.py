"""Thin, metered, cached chat client for any OpenAI-compatible endpoint.

Design notes
------------
* One transport interface (``ChatTransport``) so tests inject a fake and the
  pipeline never knows whether it is talking to Ollama, Groq or a mock.
* Every call is metered per pipeline stage (tokens, latency, cache hits). The
  meter feeds the run manifest and budget enforcement.
* Responses are cached on disk keyed by a hash of everything that affects the
  output. With temperature 0 + a fixed seed this makes re-runs reproducible and
  cheap, and lets ``--resume`` skip work after a crash or rate limit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from forgeai.config import Settings, get_settings

log = logging.getLogger(__name__)

Message = dict[str, str]


class BudgetExceeded(RuntimeError):
    """Raised before a call that would start once the token budget is spent."""


class LLMUnavailable(RuntimeError):
    """Raised when the endpoint cannot be reached after all transport retries."""


class QuotaExhausted(LLMUnavailable):
    """This model cannot serve now (daily quota spent, long cool-down, or unknown name)."""

    def __init__(self, message: str, retry_after: float = 3600.0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Completion:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatTransport(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        seed: int,
    ) -> Completion: ...


# --------------------------------------------------------------------------- #
# Metering
# --------------------------------------------------------------------------- #
@dataclass
class StageUsage:
    calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class UsageMeter:
    stages: dict[str, StageUsage] = field(default_factory=dict)

    def record(self, stage: str, c: Completion, seconds: float, cached: bool) -> None:
        s = self.stages.setdefault(stage or "unscoped", StageUsage())
        s.calls += 1
        s.cache_hits += int(cached)
        s.prompt_tokens += c.prompt_tokens
        s.completion_tokens += c.completion_tokens
        s.seconds += seconds

    @property
    def total_tokens(self) -> int:
        return sum(s.total_tokens for s in self.stages.values())

    def as_dict(self) -> dict[str, Any]:
        out = {k: vars(v) | {"total_tokens": v.total_tokens} for k, v in self.stages.items()}
        out["_total"] = {
            "calls": sum(s.calls for s in self.stages.values()),
            "cache_hits": sum(s.cache_hits for s in self.stages.values()),
            "total_tokens": self.total_tokens,
            "seconds": round(sum(s.seconds for s in self.stages.values()), 2),
        }
        return out


# --------------------------------------------------------------------------- #
# Real transport
# --------------------------------------------------------------------------- #
class OpenAICompatTransport:
    """Talks to Ollama / Groq / vLLM / LM Studio through the OpenAI SDK."""

    def __init__(self, settings: Settings):
        from openai import OpenAI  # local import keeps tests dependency-light

        self._client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.request_timeout_s,
            max_retries=0,  # retries are handled (and logged) by LLMClient
        )
        self._json_mode_supported = True

    def complete(self, *, model, messages, temperature, max_tokens, json_mode, seed) -> Completion:
        kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
        )
        if "gpt-oss" in model:
            # Reasoning models spend hidden tokens thinking; keep it short and leave headroom for the answer.
            kwargs["extra_body"] = {"reasoning_effort": "low"}
            kwargs["max_tokens"] = max(max_tokens, 1500)
        if json_mode and self._json_mode_supported:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # some servers reject response_format/seed
            recovered = _recover_native_tool_call(exc)
            if recovered is not None:
                return Completion(text=recovered)
            msg = str(exc).lower()
            if json_mode and ("response_format" in msg or "json" in msg) and self._json_mode_supported:
                log.warning("Endpoint rejected JSON mode; falling back to prompt-only JSON.")
                self._json_mode_supported = False
                kwargs.pop("response_format", None)
                resp = self._client.chat.completions.create(**kwargs)
            else:
                raise
        usage = getattr(resp, "usage", None)
        return Completion(
            text=resp.choices[0].message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


def _recover_native_tool_call(exc: Exception) -> str | None:
    """Some open models (gpt-oss) emit a native function call although we ask for JSON; the server
    rejects it but returns the attempted call. Translate it into the agent's own tool step."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict) or body.get("code") != "tool_use_failed":
        return None
    try:
        call = json.loads(body.get("failed_generation", ""))
        name = str(call["name"]).split(".")[-1]
        args = call.get("arguments") or {}
        args = json.loads(args) if isinstance(args, str) else args
        if "action" in args:  # the model wrapped our own answer object in a fake function call
            return json.dumps(args)
        return json.dumps({"action": "tool", "tool": name, "args": args})
    except (ValueError, KeyError, TypeError):
        return None


# Only the provider's own wording: matching loose phrases like "per day" would fire on document text.
_UNAVAILABLE = re.compile(
    r"(tokens|requests) per day|model_not_found|The model `[^`]+` does not exist|model_decommissioned", re.I
)


def _rate_limit_wait(exc: Exception) -> float | None:
    """Seconds the server asks us to wait ('try again in 2m3.5s' / '850ms'), if it says so."""
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)(ms|s))?", str(exc))
    if not m or not any(m.groups()):
        return None
    seconds = float(m.group(3) or 0) / (1000 if m.group(4) == "ms" else 1)
    return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + seconds + 1.0


def _is_transient(exc: Exception) -> bool:
    name = type(exc).__name__
    transient = {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "ConnectError",
        "ReadTimeout",
        "TimeoutError",
        "ConnectionError",
    }
    return name in transient or "rate limit" in str(exc).lower()


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: ChatTransport | None = None,
        meter: UsageMeter | None = None,
        use_cache: bool | None = None,
    ):
        self.settings = settings or get_settings()
        self.transport = transport or OpenAICompatTransport(self.settings)
        self.meter = meter or UsageMeter()
        self.substitutions: dict[str, int] = {}  # "wanted -> used": calls answered by a stand-in model
        self._exhausted: dict[str, float] = {}  # model -> time before which it is not tried again
        self._local: ChatTransport | None = None
        self._injected = transport is not None
        self._cache = None
        if self.settings.use_cache if use_cache is None else use_cache:
            import diskcache

            self._cache = diskcache.Cache(str(self.settings.cache_dir / "llm"))

    # -- public ------------------------------------------------------------
    def chat(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1500,
        json_mode: bool = False,
        stage: str = "",
    ) -> str:
        wanted = model or self.settings.gen_model
        last: QuotaExhausted | None = None
        for candidate in self._chain(wanted):
            key = self._key(candidate, messages, temperature, max_tokens, json_mode)
            if self._cache is not None and key in self._cache:
                cached: Completion = self._cache[key]
                self.meter.record(stage, Completion(cached.text), 0.0, cached=True)
                self._note_substitution(wanted, candidate)
                return cached.text
            if self._exhausted.get(candidate, 0) > time.time():
                continue
            self._check_budget()
            try:
                completion, seconds = self._call_with_retries(candidate, messages, temperature, max_tokens, json_mode)
            except QuotaExhausted as exc:
                last = exc
                self._exhausted[candidate] = time.time() + exc.retry_after
                log.warning("model %s unavailable; trying the next fallback", candidate)
                continue
            self.meter.record(stage, completion, seconds, cached=False)
            self._note_substitution(wanted, candidate)
            if self._cache is not None and completion.text.strip():  # never cache empty replies
                self._cache[key] = completion
            return completion.text
        raise last or QuotaExhausted(f"RateLimitError: every model in the chain for {wanted} is cooling down")

    # -- internals ---------------------------------------------------------
    def _chain(self, wanted: str) -> list[str]:
        extra = [m.strip() for m in self.settings.fallback_models.split(",") if m.strip()]
        return [wanted, *[m for m in extra if m != wanted]]

    def _note_substitution(self, wanted: str, used: str) -> None:
        if used != wanted:
            k = f"{wanted} -> {used}"
            self.substitutions[k] = self.substitutions.get(k, 0) + 1

    def _transport_for(self, model: str) -> tuple[ChatTransport, str]:
        if not model.endswith("@local"):
            return self.transport, model
        name = model[: -len("@local")]
        if self._injected:
            return self.transport, name
        if self._local is None:
            local = self.settings.model_copy(
                update={
                    "llm_base_url": self.settings.local_base_url,
                    "llm_api_key": "ollama",
                    "request_timeout_s": max(self.settings.request_timeout_s, 600.0),
                }
            )
            self._local = OpenAICompatTransport(local)
        return self._local, name

    def _key(self, model, messages, temperature, max_tokens, json_mode) -> str:
        payload = json.dumps(
            [model, messages, temperature, max_tokens, json_mode, self.settings.seed],
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _check_budget(self) -> None:
        budget = self.settings.token_budget
        if budget and self.meter.total_tokens >= budget:
            raise BudgetExceeded(f"Token budget {budget} spent ({self.meter.total_tokens} used).")

    def _call_with_retries(self, model, messages, temperature, max_tokens, json_mode):
        attempts = self.settings.transport_retries + 1
        last: Exception | None = None
        attempt, rate_waits = 0, 0
        while attempt < attempts:
            attempt += 1
            t0 = time.perf_counter()
            try:
                transport, name = self._transport_for(model)
                c = transport.complete(
                    model=name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    seed=self.settings.seed,
                )
                return c, time.perf_counter() - t0
            except Exception as exc:  # noqa: BLE001 - classified below
                last = exc
                hint = _rate_limit_wait(exc)
                if _UNAVAILABLE.search(str(exc)) or (hint or 0) > 180:
                    raise QuotaExhausted(f"LLM model {model} unavailable: {exc!r}", retry_after=hint or 3600.0) from exc
                if hint is not None and hint <= 180 and rate_waits < 60:
                    # A per-minute quota is not a failure: wait as asked without spending a retry.
                    rate_waits += 1
                    attempt -= 1
                    log.warning("rate limited; waiting %.0fs as requested", hint)
                    time.sleep(hint)
                    continue
                if not _is_transient(exc) or attempt >= attempts:
                    break
                wait = min(2**attempt, 20)
                log.warning("LLM call failed (%s), retry %d/%d in %ss", type(exc).__name__, attempt, attempts - 1, wait)
                time.sleep(wait)
        raise LLMUnavailable(f"LLM call failed after {attempts} attempt(s): {last!r}") from last
