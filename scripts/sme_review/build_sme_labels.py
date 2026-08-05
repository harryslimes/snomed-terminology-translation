#!/usr/bin/env python3
"""Structure the returned batch-1 SME feedback into one machine-readable label file.

Reconciles the SME-returned review packet (RadiologyTranslation.xlsx) with the
packet-as-sent CSVs on sctid and emits a single tidy per-term dataset that the
judge-agreement (task-27) and error-taxonomy (task-28) work can load directly.

Inputs (defaults point at the 2026-04-24 batch):
  --returned   SME-returned xlsx (sheet: khis_sme_review_packet) with
               sme_rating / sme_corrected_translation_ko / sme_notes filled.
  --packet-dir Directory with the packet-as-sent CSVs (sample_100.csv,
               sme_review_critique.csv, sonnet_review_100.csv,
               khis_sme_review_packet.csv).
  --out        Output CSV path (a .provenance.json sidecar is written next to it).

Notes:
  - Excel corrupts SCTIDs longer than 15 significant digits (stored as floats),
    so returned sctids are repaired by joining back on english_term, which is
    unique in the packet. Any unrepairable row is a hard error.
  - SME Korean (corrections, notes) is kept verbatim — spacing/orthography
    distinctions are signal for the error taxonomy, not noise.
  - Batch 1 returned only the packet view. The critique view (sme_agree_with_sonnet)
    and independent view (sme_translation) were not filled in; their columns are
    kept in the schema, empty, so batch 2+ can populate them.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# Ordinal encoding aligned with the eval judge labels in
# configs/investigations/sme_judge_agreement_v1.json / sme_error_taxonomy_v1.json.
RATING_ORDINAL = {"ACCEPTABLE": 2, "PARTIAL": 1, "WRONG": 0}

OUTPUT_COLUMNS = [
    "sctid",
    "english_term",
    "hierarchy",
    "stratum",
    "modality",
    "body_site_en",
    "body_site_ko_dict",
    "pipeline_translation_ko",
    "pipeline_back_translation_en",
    "sim_en_back",
    "sme_rating",
    "sme_rating_ordinal",
    "sme_corrected_ko",
    "sme_independent_ko",
    "sme_notes",
    "sonnet_label",
    "sonnet_notes",
    "sonnet_suggested_ko",
    "sme_agree_sonnet",
]


def read_returned(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="khis_sme_review_packet", dtype={"sctid": str})
    # The SME added one stray comment in an unnamed extra column ("열1");
    # fold any such extra columns into sme_notes rather than dropping them.
    known = {
        "sctid", "english_term", "snomed_body_site_en", "snomed_modality_en",
        "machine_translation_ko", "sme_rating", "sme_corrected_translation_ko",
        "sme_notes",
    }
    for col in [c for c in df.columns if c not in known]:
        extra = df[col].notna()
        if extra.any():
            df.loc[extra, "sme_notes"] = df.loc[extra].apply(
                lambda r: (str(r["sme_notes"]) + " | " if pd.notna(r["sme_notes"]) else "")
                + str(r[col]),
                axis=1,
            )
        df = df.drop(columns=[col])
    df["sme_rating"] = df["sme_rating"].str.strip().str.upper()
    return df


def repair_sctids(returned: pd.DataFrame, packet: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Fix sctids Excel rounded to 15 significant digits, joining on english_term."""
    canonical = packet.set_index("english_term")["sctid"]
    if not packet["english_term"].is_unique or not returned["english_term"].is_unique:
        raise ValueError("english_term is not unique; cannot repair sctids safely")
    repairs = []
    fixed = returned.copy()
    for i, row in fixed.iterrows():
        true_id = canonical.get(row["english_term"])
        if true_id is None:
            raise ValueError(f"returned row not in packet: {row['english_term']!r}")
        if true_id != row["sctid"]:
            repairs.append({"english_term": row["english_term"],
                            "excel_sctid": row["sctid"], "canonical_sctid": true_id})
            fixed.at[i, "sctid"] = true_id
    return fixed, repairs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--returned", type=Path,
                   default=Path("data/analysis/clinician_feedback/RadiologyTranslation.xlsx"))
    p.add_argument("--packet-dir", type=Path,
                   default=Path("data/sme_review/2026-04-24"))
    p.add_argument("--out", type=Path,
                   default=Path("data/sme_review/2026-04-24/sme_labels_v1.csv"))
    args = p.parse_args()

    packet = pd.read_csv(args.packet_dir / "khis_sme_review_packet.csv", dtype={"sctid": str})
    sample = pd.read_csv(args.packet_dir / "sample_100.csv", dtype={"sctid": str})
    critique = pd.read_csv(args.packet_dir / "sme_review_critique.csv", dtype={"sctid": str})
    sonnet = pd.read_csv(args.packet_dir / "sonnet_review_100.csv", dtype={"sctid": str})
    returned, repairs = repair_sctids(read_returned(args.returned), packet)

    unknown = set(returned["sme_rating"]) - set(RATING_ORDINAL)
    if unknown:
        raise ValueError(f"unmapped sme_rating values: {unknown}")

    # The packet-as-sent CSV is canonical for the pipeline translation: the SME
    # occasionally typed into the sent-translation cell instead of the correction
    # column. Keep what we actually sent and record any such edits in provenance.
    chk = returned.merge(packet[["sctid", "machine_translation_ko"]],
                         on="sctid", suffixes=("_returned", ""), validate="1:1")
    if len(chk) != len(returned):
        raise ValueError("returned rows missing from packet after sctid repair")
    edited = chk["machine_translation_ko_returned"] != chk["machine_translation_ko"]
    sent_cell_edits = chk.loc[
        edited, ["sctid", "machine_translation_ko", "machine_translation_ko_returned"]
    ].rename(columns={"machine_translation_ko": "sent",
                      "machine_translation_ko_returned": "sme_edited_to"}
             ).to_dict(orient="records")
    returned = chk.drop(columns=["machine_translation_ko_returned"])

    df = (
        returned
        .merge(sample[["sctid", "hierarchy", "stratum", "sim_en_back"]], on="sctid", validate="1:1")
        .merge(critique[["sctid", "snomed_body_site_ko_kr_dict", "pipeline_back_translation_en"]],
               on="sctid", validate="1:1")
        .merge(sonnet[["sctid", "sonnet_label", "sonnet_what_is_wrong", "sonnet_suggested"]],
               on="sctid", validate="1:1")
    )
    assert len(df) == len(returned), "join dropped rows"

    df = df.rename(columns={
        "snomed_modality_en": "modality",
        "snomed_body_site_en": "body_site_en",
        "snomed_body_site_ko_kr_dict": "body_site_ko_dict",
        "machine_translation_ko": "pipeline_translation_ko",
        "sme_corrected_translation_ko": "sme_corrected_ko",
        "sonnet_what_is_wrong": "sonnet_notes",
        "sonnet_suggested": "sonnet_suggested_ko",
    })
    df["sme_rating_ordinal"] = df["sme_rating"].map(RATING_ORDINAL)
    # Not returned in batch 1 — schema placeholders for later batches.
    df["sme_independent_ko"] = pd.NA
    df["sme_agree_sonnet"] = pd.NA

    df = df[OUTPUT_COLUMNS].sort_values("sctid").reset_index(drop=True)
    df.to_csv(args.out, index=False)

    rating_dist = df["sme_rating"].value_counts().to_dict()
    provenance = {
        "dataset": args.out.name,
        "batch": "2026-04-24 (batch 1: 100 long-tail radiology procedures, EN->KO)",
        "built_by": "scripts/sme_review/build_sme_labels.py",
        "sources": {
            "sme_returned": str(args.returned),
            "packet_as_sent": str(args.packet_dir / "khis_sme_review_packet.csv"),
            "sampling_frame": str(args.packet_dir / "sample_100.csv"),
            "critique_view": str(args.packet_dir / "sme_review_critique.csv"),
            "sonnet_review": str(args.packet_dir / "sonnet_review_100.csv"),
        },
        "rating_scale": {
            "values": list(RATING_ORDINAL),
            "ordinal": RATING_ORDINAL,
            "note": "SME used the packet's ACCEPTABLE/PARTIAL/WRONG vocabulary directly; "
                    "no free-text normalisation was needed beyond strip/upper.",
        },
        "sctid_repairs": {
            "reason": "Excel stores sctids as 64-bit floats (15 significant digits); "
                      "17-digit sctids were rounded. Repaired via english_term join.",
            "repaired": repairs,
        },
        "sent_cell_edits": {
            "reason": "Rows where the SME edited the machine_translation_ko cell "
                      "instead of (or in addition to) the correction column. "
                      "pipeline_translation_ko keeps the packet-as-sent value.",
            "edits": sent_cell_edits,
        },
        "sme_views_returned": {
            "packet": True,
            "critique (sme_agree_with_sonnet)": False,
            "independent (sme_translation)": False,
        },
        "row_count": len(df),
        "rating_distribution": rating_dist,
        "n_with_correction": int(df["sme_corrected_ko"].notna().sum()),
        "n_with_notes": int(df["sme_notes"].notna().sum()),
    }
    sidecar = args.out.with_suffix(".provenance.json")
    sidecar.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

    print(f"wrote {args.out} ({len(df)} rows) + {sidecar.name}")
    print(f"ratings: {rating_dist}")
    print(f"corrections: {provenance['n_with_correction']}, notes: {provenance['n_with_notes']}")
    if repairs:
        print(f"sctid repairs: {[r['canonical_sctid'] for r in repairs]}")
    # Cross-check the SME rating against the pre-review Sonnet label for awareness
    # (agreement analysis proper is task-27).
    agree = (df["sme_rating"] == df["sonnet_label"]).mean()
    print(f"raw SME/Sonnet label agreement (context only): {agree:.0%}")


if __name__ == "__main__":
    main()
