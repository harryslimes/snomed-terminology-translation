"""Break a back-translation retrieval run's recall@K down by hierarchy.

Reads a run's per-query result CSV (``sctid,correct_rank,...`` — from the
snomed_retrieve / rerank node) and the gold CSV (``sctid,hierarchy,...`` — from
build_kr_gold.py), joins on ``sctid``, and reports recall@1/3/5/10 + MRR overall
and per hierarchy region, with concept counts.

    python scripts/analysis/recall_by_hierarchy.py \
        --results data/wizard_runs/<job>/snomed_retrieve.csv \
        --gold    /path/to/kr_gold_full.csv \
        --min-n 100
"""
from __future__ import annotations

import argparse
import csv


def _load_rank(results_csv: str) -> dict[str, int]:
    rank: dict[str, int] = {}
    with open(results_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = (r.get("sctid") or "").strip()
            if sid:
                rank[sid] = int(r.get("correct_rank") or 0)
    return rank


def _load_hierarchy(gold_csv: str) -> dict[str, str]:
    hcol: dict[str, str] = {}
    with open(gold_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = (r.get("sctid") or "").strip()
            if sid:
                hcol[sid] = (r.get("hierarchy") or "(no tag)").strip() or "(no tag)"
    return hcol


def _metrics(ranks: list[int]) -> dict:
    n = len(ranks)
    if not n:
        return {"n": 0}
    at = lambda k: 100.0 * sum(1 for r in ranks if 0 < r <= k) / n
    mrr = sum(1.0 / r for r in ranks if r > 0) / n
    return {"n": n, "r@1": at(1), "r@3": at(3), "r@5": at(5), "r@10": at(10),
            "mrr": mrr}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--min-n", type=int, default=100,
                    help="Only break out hierarchies with at least this many concepts.")
    a = ap.parse_args()

    rank = _load_rank(a.results)
    hier = _load_hierarchy(a.gold)
    by: dict[str, list[int]] = {}
    allranks: list[int] = []
    for sid, rk in rank.items():
        allranks.append(rk)
        by.setdefault(hier.get(sid, "(unmapped)"), []).append(rk)

    def line(label: str, m: dict) -> str:
        return (f"  {label:24s} n={m['n']:6d}  "
                f"@1={m['r@1']:5.1f}  @3={m['r@3']:5.1f}  @5={m['r@5']:5.1f}  "
                f"@10={m['r@10']:5.1f}  mrr={m['mrr']:.3f}")

    overall = _metrics(allranks)
    print(line("OVERALL", overall))
    print("  " + "-" * 78)
    big = {h: rs for h, rs in by.items() if len(rs) >= a.min_n}
    for h, rs in sorted(big.items(), key=lambda x: -_metrics(x[1])["r@5"]):
        print(line(h, _metrics(rs)))
    small_n = sum(len(rs) for h, rs in by.items() if len(rs) < a.min_n)
    if small_n:
        print("  " + "-" * 78)
        print(f"  ({small_n} concepts in hierarchies below n={a.min_n}, not broken out)")


if __name__ == "__main__":
    main()
