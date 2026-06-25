"""Cross-hierarchy mismatch as a structural signal (no embeddings).

We know each source concept's expected semantic tag (procedure/disorder/...),
and the retrieved concept's tag sits in its FSN. Does "the back-translation
landed in a DIFFERENT hierarchy than expected" flag a problem?

Two framings:
  * vs `recovered` (gold run): mismatch <=> not-recovered BY CONSTRUCTION (the
    gold concept carries the expected tag), so this is a tautological-but-free
    certain-reject for the ~11% that drift hierarchies — not a learned signal.
  * vs an independent correctness label (forward candidates): the real test —
    pass --label-col pointing at a 0/1 'incorrect' column. Result: AUC ~0.51
    (chance) — mismatch does NOT detect bad translations.

    python scripts/analysis/cross_hierarchy_mismatch.py \
        --results <run>/snomed_retrieve.csv --int <RF2_root> [--gold gold.csv]
"""
from __future__ import annotations
import argparse, csv
from pathlib import Path
from snomed_translation.snomed_rf2 import read_concept_terms


def tag(fsn: str) -> str:
    fsn = (fsn or "").strip()
    return fsn.rsplit("(", 1)[-1].rstrip(")").strip() if fsn.endswith(")") else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--int", required=True)
    ap.add_argument("--gold", help="optional sctid->hierarchy csv (else read source tag from RF2)")
    a = ap.parse_args()
    src = ({r["sctid"]: r["hierarchy"] for r in csv.DictReader(open(a.gold))}
           if a.gold else {ct.sctid: tag(ct.fsn) for ct in read_concept_terms(a.int)})
    rows = list(csv.DictReader(open(a.results, encoding="utf-8")))
    mism = [int(src.get(r["sctid"], "x") != tag(r.get("top_fsn"))) for r in rows]
    rec = [int(r.get("recovered") or 0) for r in rows]
    n = len(rows); m = sum(mism)
    rec_match = sum(rec[i] for i in range(n) if not mism[i]) / max(1, n - m)
    rec_mis = sum(rec[i] for i in range(n) if mism[i]) / max(1, m)
    print(f"n={n}  recall@1={100*sum(rec)/n:.1f}%  tag-mismatch rate={100*m/n:.1f}%")
    print(f"  recovered | tag matches:    {100*rec_match:.1f}%")
    print(f"  recovered | tag mismatches: {100*rec_mis:.1f}%  "
          f"(mismatch<=>not-recovered is tautological vs the gold)")


if __name__ == "__main__":
    main()
