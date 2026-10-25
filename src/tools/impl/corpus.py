"""Local curated corpus (Section 3.5 route (a)): reproducible, ground truth knowable.

Documents are Markdown files with a small front-matter block. Search is a self-implemented BM25
over document sections - no model is involved, so results are genuinely retrieved, never generated.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_TOKEN = re.compile(r"[a-z0-9$%.]+")
_STOP = set("the a an and or of to in for on with by is are was were be this that it as at from its their our your "
            "what which who how does do vendor vendors".split())

INJECTION_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"ignore (all |any )?(prior|previous|above|earlier) instructions",
        r"^\s*system\s*:", r"\bsystem prompt\b", r"you are now", r"disregard (the|your) (rules|instructions)",
        r"rate (this|our) (vendor|company|product) (the )?highest", r"omit (all )?competitors",
        r"do not (mention|include) (any )?(competitor|other vendors)", r"skip the approval",
    ]
]


def scan_injection(text: str) -> list[str]:
    hits = []
    for line in text.splitlines():
        for pat in INJECTION_PATTERNS:
            if pat.search(line):
                hits.append(line.strip()[:200])
                break
    return hits


def tokenize(text: str) -> list[str]:
    return [t.strip(".") for t in _TOKEN.findall(text.lower()) if t.strip(".") and t not in _STOP]


@dataclass
class Section:
    doc_id: str
    heading: str
    text: str
    tokens: list[str] = field(default_factory=list)


@dataclass
class Document:
    id: str
    title: str
    source_type: str
    vendor: str
    date: str
    credibility_hint: str
    text: str
    sections: list[Section]


class Corpus:
    def __init__(self, corpus_dir: Path, reference_date: str = "2026-06-30"):
        self.dir = Path(corpus_dir)
        self.reference = date.fromisoformat(reference_date)
        self.docs: dict[str, Document] = {}
        self.sections: list[Section] = []
        self._load()
        self._index()

    def _load(self) -> None:
        for p in sorted(self.dir.glob("*.md")):
            raw = p.read_text(encoding="utf-8")
            meta, body = {}, raw
            if raw.startswith("---"):
                _, fm, body = raw.split("---", 2)
                for line in fm.strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
            doc_id = meta.get("id", p.stem)
            sections: list[Section] = []
            current, buf = "Overview", []
            for line in body.strip().splitlines():
                if line.startswith("## "):
                    if buf:
                        sections.append(Section(doc_id, current, "\n".join(buf).strip()))
                    current, buf = line[3:].strip(), []
                elif not line.startswith("# "):
                    buf.append(line)
            if buf:
                sections.append(Section(doc_id, current, "\n".join(buf).strip()))
            self.docs[doc_id] = Document(doc_id, meta.get("title", p.stem), meta.get("source_type", "vendor_page"),
                                         meta.get("vendor", ""), meta.get("date", ""), meta.get("credibility_hint", ""),
                                         body.strip(), sections)
            self.sections.extend(s for s in sections if s.text)

    def _index(self) -> None:
        self.df: dict[str, int] = {}
        for s in self.sections:
            s.tokens = tokenize(f"{self.docs[s.doc_id].title} {s.heading} {s.text}")
            for t in set(s.tokens):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = sum(len(s.tokens) for s in self.sections) / max(1, len(self.sections))

    def age_years(self, doc: Document) -> float | None:
        try:
            return (self.reference - date.fromisoformat(doc.date)).days / 365.25
        except ValueError:
            return None

    def recency_bucket(self, doc: Document) -> str:
        a = self.age_years(doc)
        if a is None:
            return "unknown"
        return "<1y" if a < 1 else "1-3y" if a < 3 else "3-5y" if a < 5 else ">5y"

    def search(self, query: str, source_type: str = "any", max_results: int = 5, recency: str = "any") -> list[dict]:
        q = tokenize(query)
        if not q:
            return []
        n = len(self.sections)
        limit = {"1y": 1, "3y": 3, "5y": 5}.get(recency)
        scored = []
        for s in self.sections:
            doc = self.docs[s.doc_id]
            if source_type != "any" and doc.source_type != source_type:
                continue
            if limit is not None:
                age = self.age_years(doc)
                if age is None or age > limit:
                    continue
            tf: dict[str, int] = {}
            for t in s.tokens:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for t in q:
                if t not in tf:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                f = tf[t]
                score += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(s.tokens) / self.avgdl))
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: -x[0])
        hits, seen = [], set()
        for score, s in scored:
            key = (s.doc_id, s.heading)
            if key in seen:
                continue
            seen.add(key)
            doc = self.docs[s.doc_id]
            hits.append({"document_id": s.doc_id, "title": doc.title, "section": s.heading,
                         "source_type": doc.source_type, "vendor": doc.vendor, "date": doc.date or None,
                         "score": round(score, 3), "snippet": self._snippet(s.text, q)})
            if len(hits) >= max_results:
                break
        return hits

    @staticmethod
    def _snippet(text: str, q: list[str], width: int = 420) -> str:
        low = text.lower()
        pos = min([low.find(t) for t in q if low.find(t) >= 0] or [0])
        start = max(0, pos - 120)
        snip = text[start:start + width].replace("\n", " ")
        return ("…" if start else "") + snip + ("…" if start + width < len(text) else "")

    def get(self, doc_id: str) -> Document | None:
        return self.docs.get(doc_id)
