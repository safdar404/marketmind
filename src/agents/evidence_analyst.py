"""Evidence Analyst: tool result -> zero or more saved evidence records (accept / flag / reject).

Thresholds (calibrated on the S1 corpus, see docs):
  reject  if supports_claim is false, or relevance < 2, or credibility 'unknown' for a fact claim
  flag    (accept with confidence=low and a note) if credibility is 'low' or the passage is promotional
  accept  otherwise; confidence = high if relevance==3 and credibility==high, else medium
Final credibility = min(model assessment, source-type ceiling) - the model can lower credibility, never raise it
above what the source type warrants.
"""
from __future__ import annotations

import json

from src.prompts import evidence_analyst as P
from src.schemas.evidence import AnalystOutput, ClaimType

_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
_CEILING = {"analyst_note": "high", "press": "medium", "review": "medium", "pricing_page": "high", "vendor_page": "medium"}


class EvidenceAnalyst:
    def __init__(self, client, dispatcher, state, log=None):
        self.client, self.dispatcher, self.state, self.log = client, dispatcher, state, log

    def _content(self, env: dict) -> str:
        d = env["data"]
        if env["tool"] == "retrieve_document":
            return (f"<retrieved_content result_id=\"{env['result_id']}\" document_id=\"{d['document_id']}\" "
                    f"title=\"{d['title']}\" source_type=\"{d['source_type']}\" date=\"{d['date']}\" trust=\"untrusted\">\n"
                    f"{d['text']}\n</retrieved_content>")
        if env["tool"] == "search_information":
            parts = [f"[hit document_id={h['document_id']} title=\"{h['title']}\" source_type={h['source_type']} "
                     f"date={h['date']}]\n{h['snippet']}" for h in d["hits"]]
            return f"<retrieved_content result_id=\"{env['result_id']}\" trust=\"untrusted\">\n" + "\n\n".join(parts) + "\n</retrieved_content>"
        return f"<retrieved_content result_id=\"{env['result_id']}\" kind=\"calculation\">\n{json.dumps(d)}\n</retrieved_content>"

    def _source_type(self, env: dict, hit_id: str | None) -> str:
        d = env["data"]
        if env["tool"] == "retrieve_document":
            return "promotional" if d.get("credibility_hint") == "promotional" else d["source_type"]
        if env["tool"] == "search_information":
            h = next((h for h in d["hits"] if h["document_id"] == hit_id), None) or (d["hits"][0] if d["hits"] else None)
            if h is None:
                return "unknown"
            doc = self.dispatcher.ctx.corpus.get(h["document_id"])
            return "promotional" if doc and doc.credibility_hint == "promotional" else h["source_type"]
        return "calculation"

    def process(self, question, env: dict) -> list[str]:
        if not env.get("ok") or env["tool"] not in ("search_information", "retrieve_document", "calculate_metric"):
            return []
        if env["tool"] == "search_information" and not env["data"]["hits"]:
            return []
        msgs = [{"role": "system", "content": P.SYSTEM},
                {"role": "user", "content": f"Sub-question {question.id}: {question.text}\n"
                                            f"Required evidence type: {question.evidence_type.value}\n\n{self._content(env)}"}]
        out, defect = self.client.structured("evidence_analyst", msgs, AnalystOutput, "analyst_output",
                                             fallback=lambda: AnalystOutput(candidates=[], injection_detected=False))
        if out.injection_detected:
            self.state.flags.append({"type": "content_injection_model", "result_id": env["result_id"]})
            if self.log:
                self.log.event("injection_flagged", "evidence_analyst", "WARNING", result_id=env["result_id"], by="model")
        saved = []
        for c in out.candidates:
            stype = self._source_type(env, c.hit_document_id)
            ceiling = "low" if stype == "promotional" else "high" if stype == "calculation" else _CEILING.get(stype, "medium")
            cred = min(c.credibility.value, ceiling, key=lambda x: _RANK[x])
            decision, reason = "accept", ""
            if not c.supports_claim:
                decision, reason = "reject", "quote does not support claim"
            elif c.relevance < 2:
                decision, reason = "reject", f"relevance {c.relevance} < 2"
            elif cred == "unknown" and c.claim_type == ClaimType.fact:
                decision, reason = "reject", "fact with unknown credibility"
            elif cred == "low" or c.promotional:
                decision, reason = "flag", "low credibility / promotional - attributed and confidence lowered"
            confidence = "low" if decision == "flag" else ("high" if c.relevance == 3 and cred == "high" else "medium")
            if decision == "reject":
                self._reject(question.id, env, c.claim, reason)
                continue
            args = {"question_id": question.id, "claim": c.claim, "claim_type": c.claim_type.value,
                    "source_ref": env["result_id"], "confidence": confidence, "credibility": cred,
                    "entity": c.entity, "attribute": c.attribute.value if c.attribute else None,
                    "quote": c.quote if env["tool"] != "calculate_metric" else "",
                    "hit_document_id": c.hit_document_id,
                    "analyst_notes": (f"[{decision}] relevance={c.relevance}; source_type={stype}; {reason} {c.notes}").strip()[:600]}
            res = self.dispatcher.dispatch("evidence_analyst", "save_research", args)
            if res["ok"]:
                saved.append(res["data"]["evidence_id"])
                if res["data"].get("uncertainty_record"):
                    saved.append(res["data"]["uncertainty_record"])
            else:
                self._reject(question.id, env, c.claim, f"save_research rejected: {res['error']['code']} - {res['error']['message']}")
        if self.log:
            self.log.event("evidence_processed", "evidence_analyst", question_id=question.id, result_id=env["result_id"],
                           candidates=len(out.candidates), saved=saved, defect=defect)
        return saved

    def _reject(self, qid, env, claim, reason):
        row = {"question_id": qid, "result_id": env["result_id"], "claim": claim, "reason": reason}
        self.state.rejections.append(row)
        if self.log:
            self.log.event("evidence_rejected", "evidence_analyst", **row)
