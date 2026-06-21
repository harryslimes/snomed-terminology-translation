#!/usr/bin/env python3
"""Build the two SME-review CSVs from the sampled 100 concepts.

Inputs:
  --sample        Sampled 100 concepts CSV (from sample_concepts.py)
  --translations  Pipeline translation CSV (covers all 5,796) — joined on sctid
  --back-trans    Back-translation CSV — joined on sctid
  --sonnet        Sonnet review CSV (the 100, structured fields). Optional —
                  if absent or missing rows, Sonnet columns are left blank.
  --kr-body-sites KR-native body-site dictionary TSV for site Korean reference
  --out-dir       Output directory

Outputs:
  sme_review_critique.csv    — SME critiques our output and provides corrections
  sme_review_independent.csv — SME translates first, then compares
  sme_review_internal.csv    — full audit trail with Sonnet's reasoning (for our records)
"""
from __future__ import annotations
import argparse, csv, re
from collections import defaultdict
from pathlib import Path


SEM = re.compile(r"\s*\([^)]+\)\s*$")


def strip_tag(s: str) -> str:
    return SEM.sub("", s or "").strip()


def load_kr_body_sites(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    if not path.exists():
        return table
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            en = r["en"].strip()
            ko_pref = r["ko_preferred"].strip()
            ko_syn = r.get("ko_synonyms", "").strip()
            entry = ko_pref + (f" (also: {ko_syn})" if ko_syn else "")
            if en:
                table[en.lower()] = entry
                table[strip_tag(en).lower()] = entry
    return table


def kr_site_korean(site_fsn: str, kr: dict[str, str]) -> str:
    if not site_fsn:
        return ""
    return kr.get(strip_tag(site_fsn).lower(), "")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=Path, required=True)
    p.add_argument("--translations", type=Path, required=True)
    p.add_argument("--back-trans", type=Path, required=True)
    p.add_argument("--sonnet", type=Path, default=None)
    p.add_argument("--kr-body-sites", type=Path,
                   default=Path("data/korean/dictionaries/kr_body_sites.tsv"))
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()

    sample = list(csv.DictReader(args.sample.open(encoding="utf-8")))
    trans = {r["sctid"]: r for r in csv.DictReader(args.translations.open(encoding="utf-8"))}
    bt = {r["sctid"]: r for r in csv.DictReader(args.back_trans.open(encoding="utf-8"))}
    sonnet: dict[str, dict] = {}
    if args.sonnet and args.sonnet.exists():
        sonnet = {r["sctid"]: r for r in csv.DictReader(args.sonnet.open(encoding="utf-8"))}
    kr_dict = load_kr_body_sites(args.kr_body_sites)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows_internal = []
    for s in sample:
        sctid = s["sctid"]
        t = trans.get(sctid, {})
        b = bt.get(sctid, {})
        snt = sonnet.get(sctid, {})
        site_ko = kr_site_korean(s.get("site_fsn", ""), kr_dict)
        rows_internal.append({
            "sctid": sctid,
            "english_term": s["preferred_term"],
            "stratum": s.get("stratum", ""),
            "snomed_body_site_en": strip_tag(s.get("site_fsn", "")),
            "snomed_body_site_ko_kr_dict": site_ko,
            "snomed_modality_en": strip_tag(s.get("method_fsn", "")),
            "pipeline_translation_ko": t.get("translation", ""),
            "pipeline_back_translation_en": b.get("back_translated", ""),
            "back_translation_similarity": b.get("sim_en_back", ""),
            "sonnet_label": snt.get("sonnet_label", ""),
            "sonnet_what_is_right": snt.get("sonnet_what_is_right", ""),
            "sonnet_what_is_wrong": snt.get("sonnet_what_is_wrong", ""),
            "sonnet_wrong_aspect": snt.get("sonnet_wrong_aspect", ""),
            "sonnet_suggested_translation": snt.get("sonnet_suggested", ""),
            "sonnet_confidence": snt.get("sonnet_confidence", ""),
        })

    # Internal full-audit CSV
    int_path = args.out_dir / "sme_review_internal.csv"
    with int_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_internal[0].keys()))
        w.writeheader()
        w.writerows(rows_internal)
    print(f"Wrote {int_path} ({len(rows_internal)} rows)")

    # ---- Critique CSV ----
    crit_fields = [
        "sctid", "english_term",
        "snomed_body_site_en", "snomed_body_site_ko_kr_dict",
        "snomed_modality_en",
        "pipeline_translation_ko",
        "sme_rating",                 # ACCEPTABLE | PARTIAL | WRONG
        "sme_corrected_translation",  # SME's preferred Korean
        "sme_notes",                  # rationale
        "pipeline_back_translation_en",
        "sonnet_label",
        "sonnet_what_is_wrong",
        "sonnet_suggested_translation",
        "sme_agree_with_sonnet",      # Y | N | partial
    ]
    crit_path = args.out_dir / "sme_review_critique.csv"
    with crit_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=crit_fields)
        w.writeheader()
        for r in rows_internal:
            w.writerow({k: r.get(k, "") for k in crit_fields})
    print(f"Wrote {crit_path}")

    # ---- Independent CSV ----
    ind_fields = [
        "sctid", "english_term",
        "snomed_body_site_en", "snomed_body_site_ko_kr_dict",
        "snomed_modality_en",
        "sme_translation",            # SME fills first (before seeing ours)
        "sme_notes_translation",
        "pipeline_translation_ko",
        "sme_rating_pipeline",        # ACCEPTABLE | PARTIAL | WRONG
        "sme_notes_comparison",
    ]
    ind_path = args.out_dir / "sme_review_independent.csv"
    with ind_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ind_fields)
        w.writeheader()
        for r in rows_internal:
            w.writerow({k: r.get(k, "") for k in ind_fields})
    print(f"Wrote {ind_path}")

    # Stratum summary
    strata = defaultdict(int)
    for r in rows_internal:
        strata[r["stratum"]] += 1
    print()
    print("Stratum breakdown:")
    for k, v in sorted(strata.items()):
        print(f"  {k:42s}  {v}")


if __name__ == "__main__":
    main()
