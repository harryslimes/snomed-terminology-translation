"""Is the SNOMED-hierarchy coherence of the retrieved top-K a confidence signal?

When a back-translation is retrieved, are the top-K candidate concepts
ontologically CLUSTERED (close in the is-a graph) or SCATTERED? A tight cluster
should mean the meaning is pinned down (trustworthy #1); a scatter should mean
ambiguity. This tests whether that structural signal predicts a correct match
better than the embedding cosine/margin (which top out at ~82% precision).

Reads a retrieval run's CSV (needs a ``candidates`` column = top-K distinct
sctids, pipe-joined, plus ``recovered``/``margin``/``top_score``) and the
International RF2 is-a graph. No network.

    python scripts/analysis/hierarchy_coherence.py \
        --results <run>/snomed_retrieve.csv \
        --int ~/SNOMED-Terminologies/SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z
"""
from __future__ import annotations

import argparse
import csv
import sys
from functools import lru_cache
from itertools import combinations
from pathlib import Path

IS_A = "116680003"


def load_parents(int_root: str) -> dict[str, set[str]]:
    rel = next(Path(int_root, "Snapshot", "Terminology").glob(
        "sct2_Relationship_Snapshot*.txt"))
    parents: dict[str, set[str]] = {}
    with rel.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[2] == "1" and p[7] == IS_A:          # active is-a: source -> dest
                parents.setdefault(p[4], set()).add(p[5])
    return parents


def make_ancestors(parents: dict[str, set[str]]):
    @lru_cache(maxsize=None)
    def anc(c: str) -> frozenset:
        out: set[str] = set()
        for p in parents.get(c, ()):  # direct parents
            out.add(p)
            out |= anc(p)
        return frozenset(out)
    return anc


def auc(pairs: list[tuple[float, int]]) -> float:
    pos = [s for s, l in pairs if l == 1]
    neg = [s for s, l in pairs if l == 0]
    if not pos or not neg:
        return float("nan")
    # rank-sum
    order = sorted(pairs, key=lambda x: x[0])
    ranks = {}; i = 0
    while i < len(order):
        j = i
        while j < len(order) and order[j][0] == order[i][0]:
            j += 1
        for k in range(i, j):
            ranks[k] = (i + 1 + j) / 2.0
        i = j
    rsum = sum(ranks[idx] for idx, (_, l) in enumerate(order) if l == 1)
    return (rsum - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--int", required=True)
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args()

    print("building is-a ancestor closure...", file=sys.stderr)
    anc = make_ancestors(load_parents(a.int))

    def coherence(cands: list[str]) -> dict:
        cs = [c for c in cands[:a.k] if c]
        if len(cs) < 2:
            return {"anc_jaccard": 1.0, "lineage_frac": 1.0, "lca_depth": 0}
        # mean pairwise Jaccard of ancestor-sets (self included)
        sets = {c: anc(c) | {c} for c in cs}
        js = [len(sets[x] & sets[y]) / len(sets[x] | sets[y])
              for x, y in combinations(cs, 2)]
        # fraction of top-K on the top-1's is-a lineage (ancestor/descendant of #1)
        top = cs[0]
        lineage = sum(1 for c in cs[1:]
                      if top in sets[c] or c in sets[top]) / (len(cs) - 1)
        # depth of the deepest common ancestor (|ancestors| as a depth proxy)
        common = set.intersection(*[set(anc(c)) for c in cs])
        lca_depth = max((len(anc(x)) for x in common), default=0)
        return {"anc_jaccard": sum(js) / len(js),
                "lineage_frac": lineage, "lca_depth": lca_depth}

    rows = list(csv.DictReader(open(a.results, encoding="utf-8")))
    feats = {"anc_jaccard": [], "lineage_frac": [], "lca_depth": [],
             "margin": [], "top_score": []}
    labels = []
    for r in rows:
        c = coherence((r.get("candidates") or "").split("|"))
        labels.append(int(r.get("recovered") or 0))
        for k in ("anc_jaccard", "lineage_frac", "lca_depth"):
            feats[k].append(c[k])
        feats["margin"].append(float(r.get("margin") or 0))
        feats["top_score"].append(float(r.get("top_score") or 0))

    n = len(labels); base = 100 * sum(labels) / n
    print(f"n={n}  base recall@1={base:.1f}%")
    print(f"  {'signal':14s} {'AUC':>6}")
    for k, v in feats.items():
        print(f"  {k:14s} {auc(list(zip(v, labels))):6.3f}")

    # precision/coverage for the best structural signal (anc_jaccard)
    aj = sorted(zip(feats["anc_jaccard"], labels), reverse=True)
    print("\n  accept top X% by anc_jaccard:")
    for cov in (0.3, 0.5, 0.7):
        k = int(n * cov); sel = aj[:k]
        print(f"    cov {int(cov*100)}%: precision@1 = {100*sum(l for _, l in sel)/k:.1f}%")


if __name__ == "__main__":
    main()
