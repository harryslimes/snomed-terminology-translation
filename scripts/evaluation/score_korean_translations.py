#!/usr/bin/env python
"""Score Korean translation outputs against the KR extension reference.

Reads two CSVs (baseline + styleguide) with columns:
    sctid, preferred_term, ko_reference, translation

Computes per-row:
    - exact_match              (1 if translation == ko_reference, else 0)
    - normalised_match         (after stripping all whitespace)
    - char_levenshtein         (raw edit distance on Hangul chars)
    - char_similarity          (1 - lev / max(len_a, len_b))
    - token_jaccard            (Jaccard over space-separated tokens)

Then prints summary metrics for each file plus a side-by-side diff of
the rows where the two modes disagree most strongly.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def normalise(s: str) -> str:
    return "".join(s.split())


def score_row(translation: str, reference: str) -> dict:
    t = translation.strip()
    r = reference.strip()
    nt, nr = normalise(t), normalise(r)
    lev = levenshtein(nt, nr)
    max_len = max(len(nt), len(nr), 1)
    sim = 1.0 - lev / max_len
    t_tok = set(t.split())
    r_tok = set(r.split())
    jacc = (len(t_tok & r_tok) / len(t_tok | r_tok)) if (t_tok | r_tok) else 0.0
    return {
        "exact": int(t == r),
        "normalised": int(nt == nr),
        "char_lev": lev,
        "char_sim": sim,
        "token_jaccard": jacc,
    }


def score_file(path: Path) -> tuple[list[dict], dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    scored = []
    for row in rows:
        if row["translation"].startswith("ERROR"):
            continue
        s = score_row(row["translation"], row["ko_reference"])
        scored.append({**row, **s})
    n = len(scored)
    summary = {
        "n": n,
        "exact_match_pct": 100 * sum(r["exact"] for r in scored) / n,
        "normalised_match_pct": 100 * sum(r["normalised"] for r in scored) / n,
        "mean_char_sim": sum(r["char_sim"] for r in scored) / n,
        "mean_token_jaccard": sum(r["token_jaccard"] for r in scored) / n,
    }
    return scored, summary


def print_summary(label: str, summary: dict) -> None:
    print(f"\n{label}")
    print(f"  n                       = {summary['n']}")
    print(f"  exact match             = {summary['exact_match_pct']:5.1f}%")
    print(f"  whitespace-normalised   = {summary['normalised_match_pct']:5.1f}%")
    print(f"  mean char similarity    = {summary['mean_char_sim']:.3f}")
    print(f"  mean token Jaccard      = {summary['mean_token_jaccard']:.3f}")


def main() -> None:
    base_path = Path("data/evals/korean/translations_qwen35b_baseline.csv")
    sg_path = Path("data/evals/korean/translations_qwen35b_styleguide.csv")

    if not base_path.exists() or not sg_path.exists():
        print("Missing one of the translation files; run translate_korean_sample.py first.")
        sys.exit(1)

    base_scored, base_summary = score_file(base_path)
    sg_scored, sg_summary = score_file(sg_path)

    print("=" * 64)
    print("KOREAN TRANSLATION EVAL — Qwen 3.5 35B vs SNOMEDCT-KR reference")
    print("=" * 64)
    print_summary("BASELINE (no style guide)", base_summary)
    print_summary("STYLE GUIDE", sg_summary)

    delta = {
        k: sg_summary[k] - base_summary[k]
        for k in ("exact_match_pct", "normalised_match_pct", "mean_char_sim", "mean_token_jaccard")
    }
    print("\nDELTA (style guide - baseline)")
    print(f"  exact match             = {delta['exact_match_pct']:+5.1f} pp")
    print(f"  whitespace-normalised   = {delta['normalised_match_pct']:+5.1f} pp")
    print(f"  mean char similarity    = {delta['mean_char_sim']:+.3f}")
    print(f"  mean token Jaccard      = {delta['mean_token_jaccard']:+.3f}")

    # Side-by-side comparison: where did style guide help / hurt the most?
    base_by_id = {r["sctid"]: r for r in base_scored}
    sg_by_id = {r["sctid"]: r for r in sg_scored}
    common = sorted(set(base_by_id) & set(sg_by_id),
                    key=lambda i: sg_by_id[i]["char_sim"] - base_by_id[i]["char_sim"],
                    reverse=True)

    print("\n" + "=" * 64)
    print("TOP 10 IMPROVEMENTS (style guide better than baseline)")
    print("=" * 64)
    for sctid in common[:10]:
        b, s = base_by_id[sctid], sg_by_id[sctid]
        delta = s["char_sim"] - b["char_sim"]
        if delta <= 0:
            break
        print(f"\n  EN  : {b['preferred_term']}")
        print(f"  REF : {b['ko_reference']}")
        print(f"  BASE: {b['translation']}  (sim={b['char_sim']:.2f})")
        print(f"  STY : {s['translation']}  (sim={s['char_sim']:.2f})  Δ={delta:+.2f}")

    print("\n" + "=" * 64)
    print("TOP 10 REGRESSIONS (style guide worse than baseline)")
    print("=" * 64)
    for sctid in reversed(common[-10:]):
        b, s = base_by_id[sctid], sg_by_id[sctid]
        delta = s["char_sim"] - b["char_sim"]
        if delta >= 0:
            break
        print(f"\n  EN  : {b['preferred_term']}")
        print(f"  REF : {b['ko_reference']}")
        print(f"  BASE: {b['translation']}  (sim={b['char_sim']:.2f})")
        print(f"  STY : {s['translation']}  (sim={s['char_sim']:.2f})  Δ={delta:+.2f}")


if __name__ == "__main__":
    main()
