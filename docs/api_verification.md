# API verification record (Deliverable 11)

> **Complete this file yourself on the day you build.** The manual requires that *you* verify every pattern
> against the current official OpenAI documentation. The entries below record what was checked against the
> installed SDK when this code was written; re-check them against platform.openai.com/docs before submitting.

| Item | What the code uses | Verified against | Date | Notes / discrepancies found |
|---|---|---|---|---|
| SDK | `openai==3.37.0`, `OpenAI(api_key, timeout, max_retries=0)` | installed SDK signature | 2026-10-25 | SDK-level retries disabled so our own backoff is visible |
| Endpoint | `client.chat.completions.create` | SDK signature | 2026-10-25 | A newer `responses` API also exists; Chat Completions is still present. Confirm it is not deprecated for your models. |
| Token limit param | `max_completion_tokens` | SDK signature | 2026-10-25 | `max_tokens` is the older name |
| Structured outputs | `response_format={"type":"json_schema","json_schema":{"name","schema","strict":True}}` | SDK signature | 2026-10-25 | Strict mode needs every property `required` + `additionalProperties:false`; we strip length/bound keywords (see `src/llm/strict_schema.py`) and enforce them in Pydantic instead |
| Tool calling | `tools=[{"type":"function","function":{name,description,parameters,strict}}]`, `parallel_tool_calls` | SDK signature | 2026-10-25 | Tool results returned as `{"role":"tool","tool_call_id",...}` |
| Refusals | `message.refusal` | SDK types | 2026-10-25 | Handled as `LLMError("refusal")` |
| Errors | `AuthenticationError`, `RateLimitError` (incl. `insufficient_quota`), `APITimeoutError`, `APIConnectionError`, `InternalServerError`, `BadRequestError` | SDK exceptions | 2026-10-25 | Some reasoning models reject `temperature`; client drops it once and logs `llm_param_adjust` |
| Rate-limit headers | `retry-after`, `retry-after-ms` | — | **TODO** | Confirm current header names in the docs |
| Model identifiers | defaults `gpt-4o`, `gpt-4o-mini` | **TODO** | **TODO** | Confirm availability; update `.env` if newer models are preferable |
| Pricing | `DEFAULT_PRICING` in `src/config.py` | **TODO** | **TODO** | Indicative only; update or set `MODEL_PRICING_JSON` |
