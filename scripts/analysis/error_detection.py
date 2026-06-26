"""Can back-translation flag incorrect machine translations?

Given forward-translation candidates (KO) with their gold reference, and the
back-translation retrieval of those candidates (did each map back to its source
concept), test whether "back-translation did NOT recover the source concept" is
a useful detector for "the candidate is a wrong translation".

Truth label comes from candidate-vs-gold similarity (char Jaccard + exact); the
detector signal is ``recovered`` (and, optionally, a ``margin`` threshold). Rows
are aligned by position (both files derive from the same ordered candidate set),
with an sctid cross-check.

    python scripts/analysis/error_detection.py \
        --results <run>/snomed_retrieve.csv \
        --labels  data/eval_inputs/kr_candidates_labels.csv
"""
from __future__ import annotations

import argparse
import csv


def norm(s: str) -> str:
    return (s or "").replace(" ", "").strip().lower()


def char_jaccard(a: str, b: str) -> float:
    A, B = set(norm(a)), set(norm(b))
    return len(A & B) / len(A | B) if (A | B) else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--correct-thresh", type=float, default=0.6,
                    help="char-Jaccard(candidate, gold) >= this ⇒ correct.")
    a = ap.parse_args()

    res = list(csv.DictReader(open(a.results, encoding="utf-8")))
    lab = list(csv.DictReader(open(a.labels, encoding="utf-8")))
    n = min(len(res), len(lab))
    mism = sum(1 for i in range(n)
               if str(res[i]["sctid"]) != str(lab[i]["sctid"]))
    rows = []
    for i in range(n):
        sim = (1.0 if norm(lab[i]["candidate"]) == norm(lab[i]["ko_reference"])
               else char_jaccard(lab[i]["candidate"], lab[i]["ko_reference"]))
        rows.append({
            "correct": sim >= a.correct_thresh,
            "recovered": int(res[i].get("recovered") or 0),
            "margin": float(res[i].get("margin") or 0.0),
        })

    n = len(rows)
    incorrect = [r for r in rows if not r["correct"]]
    correct = [r for r in rows if r["correct"]]
    print(f"n={n}  sctid-misalignments={mism}  "
          f"correct(sim>={a.correct_thresh})={len(correct)} ({100*len(correct)/n:.0f}%)  "
          f"incorrect={len(incorrect)} ({100*len(incorrect)/n:.0f}%)")

    # base rates of the detector signal
    def rec_rate(rs):
        return 100.0 * sum(r["recovered"] for r in rs) / len(rs) if rs else 0.0
    print(f"\nback-translation recovered SOURCE concept:")
    print(f"  among CORRECT candidates:   {rec_rate(correct):5.1f}%")
    print(f"  among INCORRECT candidates: {rec_rate(incorrect):5.1f}%")

    # detector = "NOT recovered" → flag as suspect
    flagged = [r for r in rows if not r["recovered"]]
    tp = sum(1 for r in flagged if not r["correct"])
    print(f"\ndetector: flag candidate when back-translation does NOT recover source")
    print(f"  flagged {len(flagged)}/{n} ({100*len(flagged)/n:.0f}%)")
    if flagged:
        print(f"  precision (flagged that are truly incorrect): {100*tp/len(flagged):.1f}%  "
              f"(base incorrect rate {100*len(incorrect)/n:.1f}%)")
    if incorrect:
        print(f"  recall (incorrect that get flagged):          {100*tp/len(incorrect):.1f}%")
    # and the clean bucket
    clean = [r for r in rows if r["recovered"]]
    if clean:
        good = sum(1 for r in clean if r["correct"])
        print(f"  of the RECOVERED (not flagged) bucket: {100*good/len(clean):.1f}% are correct "
              f"(n={len(clean)})")


if __name__ == "__main__":
    main()
