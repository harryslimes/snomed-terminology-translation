#!/usr/bin/env python3
"""Build the production imaging term list for the full SME deliverable.

Takes the 5,796-concept untranslated-imaging pool (2026-04-24) and:
- drops concepts inactive in the current International release (the SME
  flagged these; INT_20260101 snapshot is the reference),
- carries an `in_sme_review` flag for terms already SME-reviewed
  (batch-1 / batch-2), whose SME-approved rendering will be used verbatim
  in packaging instead of machine output.

Output: data/languages/ko/sme_review/2026-08-09/production_imaging_pool.csv
        (+ audit JSON alongside).
"""
from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL = ROOT / "data/languages/ko/sme_review/2026-04-24/untranslated_imaging.csv"
GOLD = ROOT / "data/evals/korean/sme_gold_splits/sme_gold_all.csv"
RF2 = ("/home/jc2301/SNOMED-Terminologies/"
       "SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z/Snapshot/"
       "Terminology/sct2_Concept_Snapshot_*.txt")
OUT_DIR = ROOT / "data/languages/ko/sme_review/2026-08-09"
OUT = OUT_DIR / "production_imaging_pool.csv"


def main() -> None:
    active: dict[str, bool] = {}
    with open(glob.glob(RF2)[0], encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            active[row["id"]] = row["active"] == "1"

    gold_sctids = {r["sctid"].strip()
                   for r in csv.DictReader(GOLD.open(encoding="utf-8"))}

    kept, dropped = [], []
    with POOL.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            sctid = r["sctid"].strip()
            if active.get(sctid, False):
                kept.append({"sctid": sctid,
                             "preferred_term": r["preferred_term"].strip(),
                             "in_sme_review": int(sctid in gold_sctids)})
            else:
                dropped.append({"sctid": sctid,
                                "preferred_term": r["preferred_term"].strip(),
                                "reason": ("inactive_in_INT20260101"
                                           if sctid in active else
                                           "not_in_INT20260101")})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sctid", "preferred_term",
                                          "in_sme_review"])
        w.writeheader()
        w.writerows(kept)
    audit = {"input_rows": len(kept) + len(dropped), "kept": len(kept),
             "dropped": dropped,
             "sme_reviewed_in_pool": sum(r["in_sme_review"] for r in kept),
             "rf2_release": "INT_20260101"}
    (OUT_DIR / "production_imaging_pool.audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: audit[k] for k in
                      ("input_rows", "kept", "sme_reviewed_in_pool")},
                     indent=2))
    print("dropped:", len(dropped))


if __name__ == "__main__":
    main()
