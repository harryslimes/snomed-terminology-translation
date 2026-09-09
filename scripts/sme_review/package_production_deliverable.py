#!/usr/bin/env python3
"""Package the production imaging translation run into the SME deliverable.

Merges, per concept: the machine translation (run artifact), the SME-approved
rendering where one exists (batch-1/2 gold overrides machine output), accepted
synonyms, and the audit signals (contrast fidelity, transliteration echo,
acceptability judge) collapsed into a review_priority for the SME's sampling.

Usage: package_production_deliverable.py <run_dir> [<nbest_run_dir>]

When a second run dir is given (a translate_consistency sampling run over the
same terms), review_priority is driven by SAMPLING DISAGREEMENT (n_distinct)
instead of the acceptability judge. Measured on the 200-row SME gold set,
n_distinct predicts incorrectness at AUC 0.755 same-model (unanimous 57.7%
exact vs 14.6% when samples disagree; none of the 5-distinct concepts were
correct), whereas the judge correlates poorly with SME verdicts. Cross-model
the signal is weaker (AUC 0.609), so when the shipped translations come from a
different model than the sampler, treat it as a difficulty proxy.

Outputs (next to the pool file, data/languages/ko/sme_review/2026-08-09/):
  production_imaging_deliverable.csv
  production_imaging_deliverable.xlsx
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL = ROOT / "data/languages/ko/sme_review/2026-08-09/production_imaging_pool.csv"
GOLD = ROOT / "data/evals/korean/sme_gold_splits/sme_gold_all.csv"
OUT_DIR = POOL.parent


def read_map(path: Path, key: str) -> dict[str, dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return {r[key].strip(): r for r in csv.DictReader(f)}


def main() -> None:
    run_dir = Path(sys.argv[1])
    art = run_dir / "artifacts"
    # Cascade runs emit `cascade_<tag>.csv` (with n_distinct + routed); plain
    # translate runs emit `translations_<tag>_lookup.csv`. Support both.
    cascade_files = sorted(art.glob("cascade_*.csv"))
    if cascade_files:
        translations = read_map(cascade_files[0], "sctid")
        is_cascade = True
    else:
        translations = read_map(
            next(art.glob("translations_production_imaging_v6_0*.csv")), "sctid")
        is_cascade = False

    def optional(path: Path) -> dict:
        """Audit artifacts are optional — a missing one must not crash the
        packaging of a finished (expensive) run."""
        return read_map(path, "sctid") if path.exists() else {}

    contrast = optional(run_dir / "contrast_fidelity_flags.csv")
    translit = optional(run_dir / "transliteration_flags.csv")
    judge = optional(run_dir / "acceptability_judgements.csv")
    gold = read_map(GOLD, "sctid")
    nbest: dict[str, dict] = {}
    if len(sys.argv) > 2:
        nb = Path(sys.argv[2]) / "artifacts"
        nbest = read_map(next(nb.glob("candidates_*.csv")), "sctid")

    rows = []
    for r in csv.DictReader(POOL.open(encoding="utf-8")):
        sctid = r["sctid"].strip()
        mt = (translations.get(sctid, {}).get("translation") or "").strip()
        g = gold.get(sctid)
        if g:
            translation = g["ko_reference"]
            syns = [s for s in g["ko_all"].split("|")[1:] if s.strip()]
            source = "sme_approved"
        else:
            translation = mt
            syns = []
            source = "machine_v6_0"
        c_issue = (contrast.get(sctid, {}).get("issue") or "").strip()
        t_flag = translit.get(sctid, {}).get("flag") in ("1", 1)
        j_label = (judge.get(sctid, {}).get("judge_label") or "").strip().upper()
        row_src = translations.get(sctid, {})
        n_distinct = int(nbest.get(sctid, {}).get("n_distinct")
                         or row_src.get("n_distinct") or 0)
        routed = (row_src.get("routed") or "").strip()
        if source == "sme_approved":
            priority = "done"
        elif routed == "escalation_failed":
            # The escalation call failed, so this row silently kept the LOW
            # confidence answer — always send it to a human.
            priority = "high"
        elif nbest or n_distinct:
            # Disagreement-first ranking. The deterministic detectors still
            # force `high` because they are high-precision and catch a
            # different error class than sampling variance.
            if c_issue or t_flag or n_distinct >= 3:
                priority = "high"
            elif n_distinct == 2:
                priority = "medium"
            else:
                priority = "low"
        elif c_issue or t_flag or j_label == "WRONG":
            priority = "high"
        elif j_label == "PARTIAL":
            priority = "medium"
        else:
            priority = "low"
        rows.append({
            "sctid": sctid,
            "preferred_term": r["preferred_term"],
            "translation_ko": translation,
            "synonyms_ko": "|".join(syns),
            "translation_source": source,
            "review_priority": priority,
            "contrast_issue": c_issue,
            "transliteration_echo": int(bool(t_flag)),
            "judge_label": j_label,
            "n_distinct": n_distinct or "",
            "routed": routed,
        })

    cols = list(rows[0].keys())
    out_csv = OUT_DIR / "production_imaging_deliverable.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "translations"
        ws.append(cols)
        for r in rows:
            ws.append([r[c] for c in cols])
        wb.save(OUT_DIR / "production_imaging_deliverable.xlsx")
    except Exception as exc:  # xlsx is a convenience copy only
        print(f"xlsx skipped: {exc}")

    from collections import Counter
    print("rows:", len(rows))
    print("priority:", dict(Counter(r["review_priority"] for r in rows)))
    print("source:", dict(Counter(r["translation_source"] for r in rows)))
    missing = sum(1 for r in rows if not r["translation_ko"])
    print("missing translations:", missing)


if __name__ == "__main__":
    main()
