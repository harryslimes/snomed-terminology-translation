"""Is the match score a usable confidence signal for a back-translation?

Given a retrieval run's per-query rows (``top_score`` of the #1 match +
``recovered`` = whether that #1 is the intended concept), measure how well the
score separates correct from incorrect matches:

  * AUC  — P(score of a correct match > score of an incorrect one)
  * a precision/coverage table — "accept matches with score >= t": what
    fraction of queries clear the bar (coverage) and, of those, what fraction
    are correct (precision@1). This is the deployable knob: pick t for a target
    precision, read off the coverage you keep.

    python scripts/analysis/confidence_curve.py --results <run>/snomed_retrieve.csv
"""
from __future__ import annotations

import argparse
import csv


def load(results_csv: str, score_col: str) -> list[tuple[float, int]]:
    out = []
    with open(results_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.append((float(r[score_col] or 0.0), int(r.get("recovered") or 0)))
            except (KeyError, ValueError):
                continue
    return out


def auc(sl: list[tuple[float, int]]) -> float:
    pos = [s for s, l in sl if l == 1]
    neg = [s for s, l in sl if l == 0]
    if not pos or not neg:
        return float("nan")
    # rank-sum (Mann-Whitney) AUC
    allv = sorted(((s, l) for s, l in sl), key=lambda x: x[0])
    ranks = {}
    i = 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg
        i = j
    rsum = sum(ranks[idx] for idx, (s, l) in enumerate(allv) if l == 1)
    return (rsum - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--score-col", default="top_score")
    a = ap.parse_args()
    sl = load(a.results, a.score_col)
    n = len(sl)
    base = 100.0 * sum(l for _, l in sl) / n
    print(f"n={n}  base precision@1 (accept all) = {base:.1f}%  AUC({a.score_col}) = {auc(sl):.3f}")
    print(f"  {'threshold':>9} {'coverage':>9} {'precision@1':>12}")
    lo = min(s for s, _ in sl)
    hi = max(s for s, _ in sl)
    for frac in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        t = lo + (hi - lo) * frac
        sel = [l for s, l in sl if s >= t]
        if not sel:
            continue
        print(f"  {t:9.3f} {100*len(sel)/n:8.1f}% {100*sum(sel)/len(sel):11.1f}%")


if __name__ == "__main__":
    main()
