# MarketMind AI — Technical documentation (draft skeleton)

> This document contains the design rationale that is fixed by the code. Sections marked **[MEASURE]** need
> numbers from **your own runs**; the manual grades the measurement and the reasoning, not the claim.

## 1. Architecture and rationale
Seven components with single contracts (Section 4). Separation gives debuggability (each defect is attributable to a stage), independent control (prompt, schema, model and temperature per stage) and adversarial separation (QC never wrote the text it checks; it uses code checks plus a different prompt and stage model).

## 2. Model and temperature per stage (Task 02)
| Stage | Default model | Temp | Reason |
|---|---|---|---|
| Request analyser | gpt-4o-mini | 0.0 | classification; determinism matters |
| Planner | gpt-4o | 0.2 | reasoning-heavy; low temperature keeps plan structure stable |
| Researcher | gpt-4o-mini | 0.0 | many calls, tool selection; cost dominates |
| Evidence analyst | gpt-4o-mini | 0.0 | extraction must be reproducible |
| Synthesis | gpt-4o | 0.3 | phrasing variance is harmless; reasoning quality matters |
| Quality control | gpt-4o | 0.0 | checker must be stable |
| Report generator | gpt-4o-mini | 0.2 | formatting |

**[MEASURE]** Run the planner on S1 three times at 0.2 and at 0.9; record objective counts and question overlap. Paste the table here.

## 3. Schema design
Plan, evidence and report schemas live in `src/schemas/` and are exported to `docs/schemas/`. Enums close every value space the code branches on (claim type, credibility, attribute, tools). Strict decoding guarantees shape; Pydantic guarantees our tighter contract (lengths, bounds, id patterns); `validate_plan` and `report_invariants` check what no schema can express. **Shape ≠ traceability ≠ truth.**

**[MEASURE]** Paste one object from your runs that was valid JSON and schema-valid but wrong (T-09 runs are a good source).

## 4. Agent loop
Termination: all resolved · iteration cap · tool-call cap · cost ceiling · stuck loop (identical call hash twice) · per-question step cap. Selection: priority then plan order. Context: per-question scoping with compact evidence references; retrieved text capped at 3,500 chars. **[MEASURE]** which condition fires most often.

## 5. Evidence and QC
`save_research` rejects unresolvable `source_ref`, facts without a quote, and any quote not found verbatim in the cited result. Conflicts on the same entity + attribute + year become system-generated uncertainty records. A source ≥2 years older on the same attribute is superseded (recorded, down-weighted), a documented mechanical rule. Evidence Analyst thresholds: reject if unsupported or relevance < 2; flag (confidence low) if credibility low or promotional; credibility capped by source type. QC: unsupported claims, missing sources and coverage gaps in code; low-confidence hybrid; contradictions by code + model. Repair ≤ 2 rounds, then publish with declared defects.

## 6. Security — two trust boundaries
1. **Model → code:** registry resolution, JSON parse, Pydantic validation (`extra=forbid`, enums, bounds, id patterns), stage permissions, budgets, timeouts. No path/URL/expression is ever built from model output.
2. **Retrieved content → prompt:** delimited `<retrieved_content trust="untrusted">`, data-not-instruction rules in every prompt, regex scan with flags in the log, and no model output can trigger a side effect without the dispatcher and the human gate.

## 7. Evaluation findings — **[MEASURE]**
Run `python -m evaluation.run_eval --repeats 3`, paste the table, the per-dimension Section 11 scores, the manual spot-check fraction and the worst dimension with its cause.

## 8. Cost analysis — **[MEASURE]**
From `runs/<id>/usage_summary.json`: cost per stage, most expensive stage, and what you changed.

## 9. Limitations
See README. State one thing the system does badly, in your own words.
