#!/usr/bin/env python3
"""Stratified sample of untranslated imaging concepts for SME review.

Strata:
  1. Novel site + common modality          (n=30)
  2. Novel site + uncommon modality        (n=20)
  3. Familiar site + uncommon modality     (n=20)
  4. Familiar site + common, long FSN ≥10w (n=15)
  5. Back-translation flagged (lowest sim) (n=10)
  6. Random untranslated                   (n=5)

Inputs:
  --untranslated      eval CSV (sctid, preferred_term, ko_reference, ...)
  --attrs-untranslated JSON {sctid: {method_id, site_*_id, ...}}
  --eval-set          translated 774 imaging CSV (to compute "familiar site" set)
  --attrs-translated  attributes JSON for the 774
  --back-trans        CSV with sim_en_back column for back-translation flagged stratum
  --output            sample CSV path
"""
from __future__ import annotations
import argparse, csv, json, random
from pathlib import Path

COMMON_MODALITY_IDS = {
    "312251004",  # CT
    "312250003",  # MRI
    "278292003",  # Ultrasound
    "168537006",  # Plain X-ray
    "44491008",   # Radiographic imaging - action (legacy)
    "363680008",  # Radiographic imaging
}

SITE_KEYS = ("procedure_site_direct_id", "procedure_site_indirect_id",
             "procedure_site_id", "finding_site_id")


def site_id(attr: dict) -> str | None:
    for k in SITE_KEYS:
        v = attr.get(k)
        if v:
            return v
    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--untranslated", type=Path, required=True)
    p.add_argument("--attrs-untranslated", type=Path, required=True)
    p.add_argument("--eval-set", type=Path,
                   default=Path("data/evals/korean/imaging_ablation/imaging_eval_set.csv"))
    p.add_argument("--attrs-translated", type=Path,
                   default=Path("data/evals/korean/imaging_ablation/imaging_attributes.json"))
    p.add_argument("--back-trans", type=Path, default=None,
                   help="Optional. CSV with sim_en_back per sctid for back-trans-flagged stratum.")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    rng = random.Random(args.seed)

    rows_unt = list(csv.DictReader(args.untranslated.open(encoding="utf-8")))
    rows_unt_by_id = {r["sctid"]: r for r in rows_unt}

    attrs_unt = json.loads(args.attrs_untranslated.read_text(encoding="utf-8"))
    attrs_tr = json.loads(args.attrs_translated.read_text(encoding="utf-8"))

    # Build the "familiar site" set: any body-site that appears in translated set
    familiar_sites = {site_id(a) for a in attrs_tr.values() if site_id(a)}
    familiar_sites.discard(None)

    # Annotate each untranslated concept
    annotated = []
    for r in rows_unt:
        sctid = r["sctid"]
        a = attrs_unt.get(sctid, {})
        sid = site_id(a)
        method = a.get("method_id")
        annotated.append({
            **r,
            "method_id": method or "",
            "method_fsn": a.get("method_fsn", ""),
            "site_id": sid or "",
            "site_fsn": (
                a.get("procedure_site_direct_fsn") or a.get("procedure_site_indirect_fsn")
                or a.get("procedure_site_fsn") or a.get("finding_site_fsn") or ""
            ),
            "site_familiar": bool(sid and sid in familiar_sites),
            "modality_common": method in COMMON_MODALITY_IDS if method else False,
            "fsn_words": len(r["preferred_term"].split()),
        })

    by_sctid = {a["sctid"]: a for a in annotated}

    # Back-trans similarity if provided
    bt_sim: dict[str, float] = {}
    if args.back_trans:
        for r in csv.DictReader(args.back_trans.open(encoding="utf-8")):
            try:
                bt_sim[r["sctid"]] = float(r.get("sim_en_back", "1.0"))
            except ValueError:
                pass

    # Stratum pools
    novel_common = [a for a in annotated if not a["site_familiar"] and a["site_id"] and a["modality_common"]]
    novel_uncommon = [a for a in annotated if not a["site_familiar"] and a["site_id"] and not a["modality_common"]]
    familiar_uncommon = [a for a in annotated if a["site_familiar"] and not a["modality_common"]]
    familiar_common_long = [a for a in annotated if a["site_familiar"] and a["modality_common"] and a["fsn_words"] >= 10]

    print(f"Pool sizes:")
    print(f"  novel site + common modality:           {len(novel_common)}")
    print(f"  novel site + uncommon modality:         {len(novel_uncommon)}")
    print(f"  familiar site + uncommon modality:      {len(familiar_uncommon)}")
    print(f"  familiar site + common, long FSN (>=10): {len(familiar_common_long)}")
    if bt_sim:
        print(f"  back-trans similarity available:        {len(bt_sim)}")

    sample: list[dict] = []
    seen_sctids: set[str] = set()

    def take(pool, n, stratum):
        rng.shuffle(pool)
        taken = 0
        for a in pool:
            if a["sctid"] in seen_sctids:
                continue
            sample.append({**a, "stratum": stratum})
            seen_sctids.add(a["sctid"])
            taken += 1
            if taken >= n:
                break

    take(list(novel_common), 30, "novel_site_common_modality")
    take(list(novel_uncommon), 20, "novel_site_uncommon_modality")
    take(list(familiar_uncommon), 20, "familiar_site_uncommon_modality")
    take(list(familiar_common_long), 15, "familiar_site_common_modality_long_fsn")

    if bt_sim:
        # Take the 10 lowest-back-trans-sim concepts not already sampled
        bt_ranked = sorted(
            [a for a in annotated if a["sctid"] not in seen_sctids and a["sctid"] in bt_sim],
            key=lambda a: bt_sim[a["sctid"]]
        )
        for a in bt_ranked[:10]:
            sample.append({**a, "stratum": "back_translation_flagged",
                           "sim_en_back": bt_sim[a["sctid"]]})
            seen_sctids.add(a["sctid"])
    else:
        # If no back-trans signal, just take 10 more random
        rest = [a for a in annotated if a["sctid"] not in seen_sctids]
        rng.shuffle(rest)
        for a in rest[:10]:
            sample.append({**a, "stratum": "random_substitute"})
            seen_sctids.add(a["sctid"])

    # 5 fully random sanity
    rest = [a for a in annotated if a["sctid"] not in seen_sctids]
    rng.shuffle(rest)
    for a in rest[:5]:
        sample.append({**a, "stratum": "random_sanity"})
        seen_sctids.add(a["sctid"])

    print(f"Sampled {len(sample)} concepts")
    stratum_counts = {}
    for s in sample:
        stratum_counts[s["stratum"]] = stratum_counts.get(s["stratum"], 0) + 1
    for k, v in stratum_counts.items():
        print(f"  {k}: {v}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["sctid", "preferred_term", "hierarchy", "stratum", "method_id",
                  "method_fsn", "site_id", "site_fsn", "site_familiar",
                  "modality_common", "fsn_words", "sim_en_back"]
    with args.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for s in sample:
            w.writerow(s)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
