# 🧠 MarketMind AI — Autonomous Business Research Agent

**AAI-412 / PRAC-05.** A Python application that turns an under-specified client request into a schema-validated market-intelligence brief whose claims can be checked. It decomposes the request into a plan, gathers evidence through strictly-schema'd tools inside a hand-built bounded agent loop, types every claim (fact / inference / recommendation / uncertainty), audits the draft with a quality checker, and publishes **only** after a named human approves.

No agent framework is used: the loop, dispatcher and state are implemented in `src/`.

## Prerequisites
- Python 3.10+ (tested on 3.12)
- An OpenAI **project** API key with a hard spend limit

## Setup
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # optional: the Streamlit app asks for the key
python -m src.config                                     # prints validated settings, key masked
python -m src.main smoke                                 # one real API call: model, tokens, cost
```

## Run it
| What | Command |
|---|---|
| 🎨 Streamlit console (enter API key in the sidebar) | `streamlit run app.py` |
| Full CLI run to the approval gate | `python -m src.main run --scenario S1` |
| Partial-report demo (iteration cap) | `python -m src.main run --scenario S1 --max-iterations 3` |
| Budget-exhaustion demo | `python -m src.main run --scenario S1 --budget 0.01` |
| Resume a run waiting at the gate | `python -m src.main resume --run-id <id>` |
| Adversarial tool calls (no key needed) | `python -m src.main adversarial` |
| Export JSON Schemas (Deliverables 5/6) | `python -m src.main export-schemas` |
| 18-case evaluation | `python -m evaluation.run_eval --repeats 3` |
| Offline unit tests (no key, no cost) | `pytest -q` |

Every run writes `runs/<run_id>/`: `plan.json`, `tool_log.jsonl`, `evidence.json` (accepted, archived, rejections), `qc_verdict.json`, `report.json`, `report_draft.md`, `usage_summary.json`, `run_log.jsonl`, decision files and, only after approval, `published_report.md`.

## Environment variables
| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | Project-scoped key (required unless entered in the app) | — |
| `MODEL_<STAGE>` | Model per stage: REQUEST_ANALYSER, PLANNER, RESEARCHER, EVIDENCE_ANALYST, SYNTHESIS, QUALITY_CONTROL, REPORT_GENERATOR | see `.env.example` |
| `TEMP_<STAGE>` | Temperature per stage | 0.0–0.3 |
| `MAX_ITERATIONS` / `MAX_TOOL_CALLS` / `MAX_STEPS_PER_QUESTION` | Loop bounds | 40 / 60 / 6 |
| `BUDGET_USD` | Cumulative cost ceiling per run | 1.50 |
| `MAX_REPAIR_ROUNDS` | QC → research repair cap | 2 |
| `REQUEST_TIMEOUT_S` / `MAX_RETRIES` / `TOOL_TIMEOUT_S` | Reliability | 60 / 4 / 10 |
| `CORPUS_DIR` / `RUNS_DIR` / `CORPUS_REFERENCE_DATE` | Paths and the frozen "today" for recency | data/corpus / runs / 2026-06-30 |
| `MODEL_PRICING_JSON` | Override per-1M-token prices (verify on the pricing page) | built-in table |

## Architecture (as built)
```
request ─► Request Analyser ─► (clarify | recorded assumption) ─► Planner ─► plan validator (code)
                                                                              │
   ┌──────────────────────── bounded loop: iterations · tool calls · $ · stuck · per-question steps
   ▼
Research Agent ─tool_call─► Dispatcher: resolve→parse→validate→authorise→budget→execute(timeout)→catch→normalise→provenance→log
   ▲                              │ search_information · retrieve_document · calculate_metric · compare_companies
   │                              ▼
   └──── tool result ◄──── Evidence Analyst ──► save_research (source_ref + verbatim-quote checks, conflict detector)
                                                        │
Comparison (matrix, code) ─► Synthesis ─► QC (code checks + model contradictions) ──fail──► repair (≤2 rounds)
                                                        │ pass / exhausted
                                              generate_report ─► HUMAN GATE: approve · reject · expand · rescope
```
Components omitted: none. Additions: per-question step cap, supersession rule for stale sources, verbatim-quote verification.

## Corpus
`data/corpus/` holds 22 fictional documents for scenario S1 with planted gaps, two contradictions, a promotional low-credibility claim, a stale snapshot and a content-borne prompt injection. See `data/CORPUS_NOTES.md`.

## Known limitations
- Search is BM25 over a small local corpus; semantic paraphrases can be missed (Challenge C4 would address this).
- Claim support is checked by verbatim quote presence, which proves the words exist in the source, not that the claim's paraphrase is faithful; that still needs the human spot-check.
- Conflict detection compares numbers within the same entity + attribute; non-numeric disagreements rely on the model QC check.
- Pricing used for cost estimates is indicative and must be verified.
