#!/usr/bin/env python
"""
Build a comparison CSV from translategemma translations vs a baseline (e.g., agent translations).
Feeds into subjective_compare.py for LLM-based quality analysis.

Usage:
    python scripts/build_translation_compare.py \
        --translategemma data/evals/sample/translations.csv \
        --baseline data/evals/wave_3/translations_*.csv \
        --output data/evals/sample/compare.csv
"""
import argparse
import csv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Build a compare CSV from two translation result files"
    )
    parser.add_argument(
        "--translategemma", type=Path, required=True,
        help="CSV from translate_sample.py (columns: sctid, preferred_term, translation)",
    )
    parser.add_argument(
        "--baseline", type=Path, required=True,
        help="Baseline CSV (columns: sctid, preferred_term, translations or agent_translation)",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/evals/sample/translation_compare.csv"),
    )
    args = parser.parse_args()

    # Load translategemma results
    gemma = {}
    with args.translategemma.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            gemma[row["sctid"]] = row

    # Load baseline
    baseline = {}
    with args.baseline.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            baseline[row["sctid"]] = row

    # Find common concepts
    common = set(gemma.keys()) & set(baseline.keys())
    if not common:
        raise SystemExit("No overlapping concepts found between the two files")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sctid", "preferred_term", "baseline_translation", "gemma_translation",
        ])
        writer.writeheader()
        for sctid in sorted(common):
            bl = baseline[sctid]
            gm = gemma[sctid]
            bl_translation = (
                bl.get("translations") or bl.get("agent_translation") or bl.get("translation", "")
            )
            writer.writerow({
                "sctid": sctid,
                "preferred_term": gm["preferred_term"],
                "baseline_translation": bl_translation,
                "gemma_translation": gm["translation"],
            })

    print(f"Wrote {len(common)} comparisons to {args.output}")


if __name__ == "__main__":
    main()
