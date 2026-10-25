"""Dispatcher: resolve -> parse -> validate -> authorise -> budget -> execute(timeout) -> catch ->
normalise -> provenance -> log. Everything the model emits is untrusted input (trust boundary 1).

A tool error is a message to the model, not an exception to the user.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import time
from typing import Any

from pydantic import ValidationError

from src.tools.impl.base import ToolContext, ToolError
from src.tools.impl.corpus import scan_injection
from src.tools.registry import REGISTRY

_EXECUTOR = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")


class Dispatcher:
    def __init__(self, ctx: ToolContext, registry: dict | None = None):
        self.ctx = ctx
        self.registry = registry or REGISTRY

    def _envelope(self, rid: str, name: str, stage: str, args: Any, ok: bool, data=None, error=None,
                  latency: float = 0.0, flags=None) -> dict:
        env = {"result_id": rid, "tool": name, "stage": stage, "ok": ok, "arguments": args,
               "data": data, "error": error, "latency_s": round(latency, 4), "injection_flags": flags or []}
        if ok:
            env["provenance"] = self._provenance(name, data)
        return env

    @staticmethod
    def _provenance(name: str, data: dict) -> dict:
        if name == "search_information":
            return {"source_kind": "search_result", "documents": [h["document_id"] for h in data.get("hits", [])]}
        if name == "retrieve_document":
            return {"source_kind": "retrieved_document", "documents": [data["document_id"]]}
        if name == "calculate_metric":
            return {"source_kind": "calculation", "formula": data["formula"]}
        return {"source_kind": "internal_state"}

    def _err(self, code: str, message: str, field: str | None = None, **extra) -> dict:
        e = {"code": code, "message": message}
        if field:
            e["field"] = field
        e.update(extra)
        return e

    def dispatch(self, stage: str, name: str, raw_args: str | dict | None) -> dict:
        st = self.ctx.state
        rid = st.next_result_id()
        t0 = time.perf_counter()
        parsed: Any = raw_args

        def finish(env: dict) -> dict:
            st.tool_history.append({k: v for k, v in env.items() if k != "data"} |
                                   {"data_preview": json.dumps(env.get("data"), default=str)[:600] if env.get("data") is not None else None})
            if env["ok"]:
                st.tool_results[rid] = env
            if self.ctx.log:
                self.ctx.log.event("tool_call", stage, "INFO" if env["ok"] else "WARNING", result_id=rid, tool=name,
                                   ok=env["ok"], arguments=env["arguments"], error=env["error"],
                                   latency_s=env["latency_s"], injection_flags=env["injection_flags"])
            return env

        # 1. resolve
        spec = self.registry.get(name)
        if spec is None:
            return finish(self._envelope(rid, name, stage, raw_args, False, error=self._err(
                "unknown_tool", f"No tool named '{name}'.", available_tools=sorted(self.registry))))
        # 2. parse
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError as e:
                return finish(self._envelope(rid, name, stage, raw_args[:300], False, error=self._err(
                    "malformed_arguments", f"Arguments are not valid JSON ({e.msg} at char {e.pos}). Re-issue the call with valid JSON.")))
        if not isinstance(parsed, dict):
            return finish(self._envelope(rid, name, stage, parsed, False, error=self._err(
                "malformed_arguments", "Arguments must be a JSON object.")))
        # 3. validate
        try:
            args = spec.args_model.model_validate(parsed)
        except ValidationError as e:
            first = e.errors()[0]
            fld = ".".join(str(x) for x in first["loc"]) or None
            return finish(self._envelope(rid, name, stage, parsed, False, error=self._err(
                "invalid_arguments", f"argument '{fld}': {first['msg']} (received {str(first.get('input'))[:80]!r})", fld,
                all_errors=[{"field": ".".join(map(str, x["loc"])), "msg": x["msg"]} for x in e.errors()[:6]])))
        # 4. authorise
        if stage not in spec.allowed_stages:
            if self.ctx.log:
                self.ctx.log.event("permission_blocked", stage, "WARNING", tool=name, permission=spec.permission)
            return finish(self._envelope(rid, name, stage, parsed, False, error=self._err(
                "permission_denied", f"'{name}' ({spec.permission}) may not be invoked from stage '{stage}'.")))
        # 5. budget
        used = st.tool_call_counts.get(name, 0)
        if used >= spec.budget:
            return finish(self._envelope(rid, name, stage, parsed, False, error=self._err(
                "budget_exhausted", f"'{name}' call budget ({spec.budget}) exhausted for this run.")))
        if spec.permission != "write" and st.tool_calls >= self.ctx.settings.max_tool_calls:
            return finish(self._envelope(rid, name, stage, parsed, False, error=self._err(
                "budget_exhausted", "run-level tool-call cap reached.")))
        st.tool_call_counts[name] = used + 1
        if spec.permission != "write":
            st.tool_calls += 1
        # 6. execute with timeout, 7. catch everything
        fault = self.ctx.settings.fault_injection.get(name)
        if fault and fault.startswith("error_first:"):  # fail only the first N calls (T-11)
            left = self.ctx.extra.setdefault(f"fault_left:{name}", int(fault.split(":")[1]))
            fault = "error" if left > 0 else None
            self.ctx.extra[f"fault_left:{name}"] = left - 1
        try:
            if fault == "error":
                raise RuntimeError("simulated upstream failure (fault injection)")
            fut = _EXECUTOR.submit(self._run, spec, args, fault)
            data = fut.result(timeout=spec.timeout_s if fault != "timeout" else 0.5)
        except cf.TimeoutError:
            return finish(self._envelope(rid, name, stage, parsed, False, latency=time.perf_counter() - t0,
                                         error=self._err("timeout", f"'{name}' timed out after {spec.timeout_s}s. "
                                                         "Retry once later, try another approach, or conclude the question is unanswerable.")))
        except ToolError as e:
            return finish(self._envelope(rid, name, stage, parsed, False, latency=time.perf_counter() - t0,
                                         error=self._err(e.code, e.message, e.field)))
        except Exception as e:  # never let a tool kill the loop
            return finish(self._envelope(rid, name, stage, parsed, False, latency=time.perf_counter() - t0,
                                         error=self._err("tool_exception", f"{name} failed: {type(e).__name__}: {str(e)[:200]}")))
        # 8. normalise + 9. provenance + injection scan on retrieved content (trust boundary 2)
        flags = []
        if name == "retrieve_document":
            flags = scan_injection(data.get("text", ""))
        elif name == "search_information":
            flags = [f for h in data.get("hits", []) for f in scan_injection(h.get("snippet", ""))]
        if flags:
            st.flags.append({"type": "content_injection", "result_id": rid, "tool": name, "lines": flags[:5]})
            if self.ctx.log:
                self.ctx.log.event("injection_flagged", stage, "WARNING", result_id=rid, lines=flags[:5])
        return finish(self._envelope(rid, name, stage, parsed, True, data=data,
                                     latency=time.perf_counter() - t0, flags=flags))

    def _run(self, spec, args, fault):
        if fault == "timeout":
            time.sleep(2.0)
        return spec.handler(args, self.ctx)
