"""Deterministic stand-in for the OpenAI SDK so the pipeline can be tested offline and for free.

It is a TEST DOUBLE only - never used in a real run. It answers by stage (inferred from the
response_format name / tools) with plausible, schema-valid objects derived from the actual
tool results it is shown, so all code paths (loop, evidence binding, QC, approval) execute for real.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace as NS


def _msg(content=None, tool_calls=None):
    return NS(content=content, tool_calls=tool_calls, refusal=None)


def _resp(message, model="gpt-4o-mini", pt=400, ct=120):
    return NS(choices=[NS(message=message, finish_reason="tool_calls" if message.tool_calls else "stop")],
              usage=NS(prompt_tokens=pt, completion_tokens=ct), model=model)


class _Completions:
    def __init__(self, parent):
        self.p = parent

    def create(self, **kw):
        self.p.calls.append(kw)
        if self.p.fail_next:
            exc = self.p.fail_next.pop(0)
            raise exc
        rf = kw.get("response_format")
        if rf:
            name = rf["json_schema"]["name"]
            return _resp(_msg(json.dumps(getattr(self.p, "_" + name)(kw["messages"]))), kw["model"])
        if kw.get("tools"):
            return _resp(self.p._research(kw["messages"]), kw["model"])
        return _resp(_msg("ok"), kw["model"], 10, 2)


class FakeOpenAI:
    def __init__(self, analyst_quotes_bad=False):
        self.calls: list = []
        self.fail_next: list = []
        self.analyst_quotes_bad = analyst_quotes_bad
        self.chat = NS(completions=_Completions(self))
        self._tc = 0

    # ---------------------------------------------------------------- stages
    def _scope(self, msgs):
        req = msgs[-1]["content"]
        simple = "per-seat pricing" in req
        return {"entity_type": "software vendors", "segment": "UNSPECIFIED (see ambiguities)",
                "geography": "UNSPECIFIED (see ambiguities)", "time_horizon": "2025-2026",
                "deliverable_type": "market intelligence brief", "complexity": "simple" if simple else "standard",
                "normalised_objective": "Profile vendors, pricing and market size for AI customer support software.",
                "named_entities": [],
                "ambiguities": [{"dimension": "geography", "issue": "Region not stated", "resolution": "clarify",
                                 "clarification_question": "Which geography?", "default_assumption": "Global"},
                                {"dimension": "segment", "issue": "Segment not stated", "resolution": "assume",
                                 "clarification_question": "SMB or enterprise?", "default_assumption": "All segments"}],
                "injection_suspected": "ignore" in req.lower()}

    def _research_plan(self, msgs):
        def q(i, t, et="pricing"):
            return {"id": i, "text": t, "evidence_type": et, "candidate_tools": ["search_information", "retrieve_document"],
                    "priority": "high", "done_when": "price or explicit gap per vendor"}
        if '"complexity": "simple"' in msgs[-1]["content"]:
            return {"objectives": [{"id": "O1", "title": "Published entry pricing", "sub_questions": [
                q("Q1.1", "Which vendors publish an entry-tier per-agent monthly price?")]}]}
        return {"objectives": [
            {"id": "O1", "title": "Vendor pricing", "sub_questions": [
                q("Q1.1", "What entry-tier per-agent monthly price does Converso publish?"),
                q("Q1.2", "What seat minimum applies to the Converso Pro plan?")]},
            {"id": "O2", "title": "Market size", "sub_questions": [
                q("Q2.1", "What was global AI customer service software spending in 2025?", "market_size"),
                q("Q2.2", "What market size did Meridian report for 2023 spending?", "market_size")]},
            {"id": "O3", "title": "Gaps and unknowns", "sub_questions": [
                q("Q3.1", "What enterprise price does Orbit CX publish for its platform?"),
                q("Q3.2", "Which documents describe Zentrix Helpdesk quantum routing features?", "product_capability")]}]}

    def _research(self, msgs):
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        q = re.search(r"Sub-question (\S+): (.+)", msgs[1]["content"])
        if not tool_msgs:
            self._tc += 1
            args = {"query": q.group(2)[:120], "source_type": "any", "max_results": 3, "recency_window": "any"}
            return _msg(None, [NS(id=f"call_{self._tc}", type="function",
                                  function=NS(name="search_information", arguments=json.dumps(args)))])
        saved = []
        for m in tool_msgs:
            saved += re.findall(r'"(E\d{3})"', m["content"])
        return _msg(f"ANSWERED: {saved}" if saved else "UNANSWERABLE: no source in the corpus addresses this")

    def _analyst_output(self, msgs):
        content = msgs[-1]["content"]
        qtext = content.split("\n")[0].lower()
        cands = []
        for hit in re.finditer(r"\[hit document_id=(\S+) title=\"([^\"]+)\" source_type=(\S+) date=(\S+)\]\n(.+)", content):
            doc, title, stype, _, snip = hit.groups()
            snip = snip.lstrip("…")
            sentence = re.split(r"(?<=[.])\s", snip)[0][:300]
            words = sentence.split()
            if len(words) < 5 or "zentrix" in qtext:
                continue
            ent, attr = None, None
            if "market" in title.lower() or "spending" in title.lower():
                ent, attr = "Market", "market_size"
            elif "converso" in doc and ("minimum" in sentence.lower()):
                ent, attr = "Converso", "seat_minimum"
            elif "converso" in doc:
                ent, attr = "Converso", "entry_price"
            elif "orbit" in doc:
                ent, attr = "Orbit CX", "pricing_model"
            quote = " ".join(words[:12]) if not self.analyst_quotes_bad else "this sentence was never in the source"
            cands.append({"claim": sentence, "claim_type": "fact", "entity": ent, "attribute": attr,
                          "hit_document_id": doc, "quote": quote, "supports_claim": True, "relevance": 3,
                          "credibility": "high", "promotional": "promo" in doc, "notes": "test double"})
            if len(cands) >= 2:
                break
        return {"candidates": cands, "injection_detected": "SYSTEM:" in content}

    def _synthesis(self, msgs):
        data = json.loads(msgs[-1]["content"].split("\n", 1)[1].split("\n\nThe quality checker")[0])
        ev = [e for e in data["evidence"]]
        facts = [e for e in ev if e["type"] == "fact"][:4]
        unc = [e for e in ev if e["type"] == "uncertainty"][:2]
        f = lambda e: {"id": "", "statement": e["claim"][:300], "claim_type": e["type"], "evidence_ids": [e["id"]],
                       "confidence": e["confidence"], "objective_id": None}
        used = {e["id"] for e in facts + unc}
        rest = [e for e in ev if e["id"] not in used]
        return {"market_overview": [f(e) for e in facts], "key_trends": [f(e) for e in unc] + [f(e) for e in rest[:6]],
                "competitor_narratives": [], "opportunities": [
                    {"id": "", "statement": "Based on the price spread, an SMB entry tier appears less contested.",
                     "claim_type": "inference", "evidence_ids": [facts[0]["id"]] if facts else [], "confidence": "medium", "objective_id": None}],
                "risks": [], "recommendations": [{"id": "", "statement": "Validate enterprise pricing directly with vendors.",
                                                  "claim_type": "recommendation", "motivated_by": ["F1"],
                                                  "evidence_ids": [], "confidence": "medium"}]}

    def _contradiction_check(self, msgs):
        return {"contradictions": []}

    def _executive_summary(self, msgs):
        items = json.loads(msgs[-1]["content"].split("\n", 1)[1])
        return {"bullets": [{"text": i["statement"][:200], "finding_ids": [i["id"]]} for i in items[:4]]
                + [{"text": "Invented claim not in the body", "finding_ids": ["F999"]}]}
