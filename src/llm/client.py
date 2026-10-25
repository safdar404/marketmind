"""The single place every OpenAI API call passes through.

Adds: request timeouts, bounded retries with exponential backoff + jitter, rate-limit handling
distinct from other failures (honours retry-after), budget ceiling enforcement, usage accounting,
and structured-output parsing with one validation-feedback retry and a typed fallback.

API surface used (verified Oct 2026 against the installed SDK, see docs/api_verification.md):
  client.chat.completions.create(model, messages, tools, tool_choice, parallel_tool_calls,
                                 response_format={"type": "json_schema", ...}, temperature, timeout)
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Callable, Type, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from src.config import Settings, scrub
from src.llm.strict_schema import to_strict
from src.llm.usage import UsageTracker

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """kind in {auth, rate_limit, quota, timeout, connection, server, context_length,
    bad_request, refusal, empty, budget}"""

    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


class BudgetExceeded(LLMError):
    def __init__(self, spent: float, ceiling: float):
        super().__init__("budget", f"cost ceiling reached: ${spent:.4f} >= ${ceiling:.2f}")


class LLMClient:
    def __init__(self, settings: Settings, usage: UsageTracker, log=None, sdk_client: Any = None):
        self.settings = settings
        self.usage = usage
        self.log = log
        # SDK-level retries disabled: retry policy lives here so it is visible and testable.
        self._client = sdk_client or OpenAI(api_key=settings.api_key, timeout=settings.request_timeout_s, max_retries=0)
        self._no_temperature: set[str] = set()  # models that reject a temperature parameter

    # ------------------------------------------------------------------ helpers
    def _event(self, kind: str, stage: str, level: str = "INFO", **data):
        if self.log:
            self.log.event(kind, stage=stage, level=level, **data)

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        base = min(30.0, 1.0 * (2 ** attempt))
        delay = base + random.uniform(0, base * 0.5)  # jitter avoids thundering herds
        if retry_after:
            delay = max(delay, retry_after)
        return delay

    @staticmethod
    def _retry_after(exc: Exception) -> float | None:
        resp = getattr(exc, "response", None)
        if resp is None:
            return None
        try:
            h = resp.headers.get("retry-after") or resp.headers.get("retry-after-ms")
            if h is None:
                return None
            v = float(h)
            return v / 1000 if resp.headers.get("retry-after-ms") else v
        except Exception:
            return None

    def check_budget(self) -> None:
        if self.usage.total_cost >= self.settings.budget_usd:
            raise BudgetExceeded(self.usage.total_cost, self.settings.budget_usd)

    # ------------------------------------------------------------------ core call
    def chat(self, stage: str, messages: list[dict], tools: list[dict] | None = None,
             response_format: dict | None = None, tool_choice: str | None = None,
             parallel_tool_calls: bool = True, max_completion_tokens: int = 4000):
        """Returns the assistant message object (SDK type). Raises LLMError on non-transient failure."""
        self.check_budget()
        model = self.settings.models[stage]
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_completion_tokens": max_completion_tokens}
        if model not in self._no_temperature:
            kwargs["temperature"] = float(self.settings.temperatures.get(stage, 0.0))
        if tools:
            kwargs["tools"] = tools
            kwargs["parallel_tool_calls"] = parallel_tool_calls
            if tool_choice:
                kwargs["tool_choice"] = tool_choice
        if response_format:
            kwargs["response_format"] = response_format

        attempt = 0
        while True:
            t0 = time.perf_counter()
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except openai.AuthenticationError as e:
                self._event("llm_error", stage, "ERROR", error_kind="auth", detail=scrub(str(e))[:300])
                raise LLMError("auth", "Authentication failed - check that the API key is valid and active.") from e
            except openai.PermissionDeniedError as e:
                raise LLMError("auth", f"Permission denied for model '{model}': {scrub(str(e))[:200]}") from e
            except openai.NotFoundError as e:
                raise LLMError("bad_request", f"Model '{model}' was not found. Check the model identifier.") from e
            except openai.RateLimitError as e:
                if "insufficient_quota" in str(e):
                    self._event("llm_error", stage, "ERROR", error_kind="quota")
                    raise LLMError("quota", "Account quota exhausted - check billing / spend limit.") from e
                ra = self._retry_after(e)
                if attempt >= self.settings.max_retries:
                    raise LLMError("rate_limit", f"Rate limited after {attempt} retries.") from e
                delay = self._backoff(attempt, ra)
                self._event("llm_retry", stage, "WARNING", reason="rate_limit", attempt=attempt + 1,
                            delay_s=round(delay, 2), retry_after=ra)
                time.sleep(delay)
                attempt += 1
            except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as e:
                kind = ("timeout" if isinstance(e, openai.APITimeoutError)
                        else "connection" if isinstance(e, openai.APIConnectionError) else "server")
                if attempt >= self.settings.max_retries:
                    self._event("llm_error", stage, "ERROR", error_kind=kind)
                    raise LLMError(kind, f"Transient {kind} error persisted after {attempt} retries.") from e
                delay = self._backoff(attempt, None)
                self._event("llm_retry", stage, "WARNING", reason=kind, attempt=attempt + 1, delay_s=round(delay, 2))
                time.sleep(delay)
                attempt += 1
            except openai.BadRequestError as e:
                msg = str(e).lower()
                if "context_length" in msg or "maximum context" in msg or "too many tokens" in msg:
                    self._event("llm_error", stage, "ERROR", error_kind="context_length")
                    raise LLMError("context_length", "Prompt exceeded the model's context window.") from e
                if "temperature" in msg and "temperature" in kwargs:
                    # Some reasoning models only accept the default temperature.
                    self._no_temperature.add(model)
                    kwargs.pop("temperature", None)
                    self._event("llm_param_adjust", stage, "WARNING", model=model, dropped="temperature")
                    continue
                self._event("llm_error", stage, "ERROR", error_kind="bad_request", detail=scrub(str(e))[:300])
                raise LLMError("bad_request", scrub(str(e))[:300]) from e

        latency = time.perf_counter() - t0
        u = getattr(resp, "usage", None)
        pt = getattr(u, "prompt_tokens", 0) or 0
        ct = getattr(u, "completion_tokens", 0) or 0
        rec = self.usage.record(stage, getattr(resp, "model", model) or model, pt, ct, latency)
        msg = resp.choices[0].message
        self._event("llm_call", stage, model=rec.model, prompt_tokens=pt, completion_tokens=ct,
                    cost_usd=rec.cost_usd, latency_s=rec.latency_s, run_cost_usd=self.usage.total_cost,
                    tool_calls=[tc.function.name for tc in (msg.tool_calls or [])],
                    finish_reason=resp.choices[0].finish_reason)
        if getattr(msg, "refusal", None):
            raise LLMError("refusal", f"Model refused: {msg.refusal[:200]}")
        if not (msg.content or msg.tool_calls):
            raise LLMError("empty", "Model returned an empty response.")
        return msg

    def text(self, stage: str, system: str, user: str) -> str:
        msg = self.chat(stage, [{"role": "system", "content": system}, {"role": "user", "content": user}])
        return msg.content or ""

    # ------------------------------------------------------------------ structured
    def structured(self, stage: str, messages: list[dict], model_cls: Type[T], name: str,
                   fallback: Callable[[], T] | None = None,
                   validator: Callable[[T], list[str]] | None = None) -> tuple[T | None, dict | None]:
        """Schema-constrained generation + independent validation.

        Attempt 1 -> on (JSON | schema | semantic) failure, feed the exact error back once ->
        on second failure return the typed fallback and a defect record. Terminates because
        attempts are bounded at 2.
        """
        schema = to_strict(model_cls.model_json_schema())
        rf = {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}
        msgs = list(messages)
        last_err = ""
        for attempt in range(2):
            msg = self.chat(stage, msgs, response_format=rf)
            raw = msg.content or ""
            try:
                obj = model_cls.model_validate_json(raw)
                problems = validator(obj) if validator else []
                if problems:
                    raise ValueError("semantic validation failed: " + "; ".join(problems[:8]))
                if attempt:
                    self._event("structured_recovered", stage, schema=name)
                return obj, None
            except (ValidationError, ValueError) as e:
                last_err = e.json() if isinstance(e, ValidationError) else str(e)
                self._event("structured_invalid", stage, "WARNING", schema=name, attempt=attempt + 1,
                            error=scrub(last_err)[:800])
                msgs = msgs + [
                    {"role": "assistant", "content": raw[:6000]},
                    {"role": "user", "content": "Your previous output failed validation with this error:\n"
                                                f"{last_err[:2000]}\nReturn a corrected object that fixes every listed problem."},
                ]
        defect = {"type": "structured_output_failure", "stage": stage, "schema": name, "error": last_err[:800]}
        self._event("structured_fallback", stage, "ERROR", schema=name, error=last_err[:800])
        return (fallback() if fallback else None), defect


def smoke_test(settings: Settings) -> dict:
    """One real API call: proves key, model and accounting work. Used by CLI and the UI."""
    usage = UsageTracker(settings, "smoke")
    client = LLMClient(settings, usage)
    out = client.text("request_analyser", "Reply with exactly: ok", "ping")
    rec = usage.records[-1]
    return {"reply": out.strip()[:40], "model": rec.model, "tokens": rec.prompt_tokens + rec.completion_tokens,
            "cost_usd": rec.cost_usd, "latency_s": rec.latency_s}


def json_dumps(o: Any) -> str:
    return json.dumps(o, default=str, ensure_ascii=False)
