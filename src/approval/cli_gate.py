"""Terminal approval gate. Requires typed input; there is no default and no timeout."""
from __future__ import annotations

import json

from src.approval.gate import DECISIONS, SCOPE_FIELDS, ApprovalError, decide, reviewer_brief


def cli_gate(pipe) -> dict:
    b = reviewer_brief(pipe.state)
    print("\n" + "=" * 78 + "\nREVIEWER BRIEF (read before the draft)\n" + "=" * 78)
    print(json.dumps({k: b[k] for k in ("objective", "assumptions", "report_status", "qc_verdict",
                                         "confidence", "claims_by_type")}, indent=2))
    print("Outstanding defects:", len(b["outstanding_defects"]))
    for l in b["limitations"][:15]:
        print("  -", l)
    print(f"Draft: runs/{pipe.state.run_id}/report_draft.md")
    while True:
        choice = input(f"\nDecision {DECISIONS} (no default): ").strip().lower()
        if choice not in DECISIONS:
            print("No decision recorded. Type one of the four options exactly.")
            continue
        approver = input("Your name (recorded as approver): ").strip()
        notes = input("Notes / reason: ").strip()
        questions, changes = None, None
        if choice == "expand":
            questions = [q for q in input("Additional questions, separated by ';': ").split(";") if q.strip()]
        if choice == "rescope":
            changes = {}
            for f in SCOPE_FIELDS:
                v = input(f"  new {f} (blank = unchanged): ").strip()
                if v:
                    changes[f] = v
        if choice == "approve" and input("Type APPROVE to confirm publication: ").strip() != "APPROVE":
            print("Not confirmed - nothing published.")
            continue
        try:
            return decide(pipe, choice, approver, notes, questions, changes)
        except ApprovalError as e:
            print("Rejected input:", e)
