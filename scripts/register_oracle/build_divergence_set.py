"""Where does the KR extension's PREFERRED Korean form disagree with an authority?

Joins the register oracle (built from RF2) against the three authorities and
emits the disagreement set -- the contested-register cases a reviewer should see
and the seed for the 'Sino vs native vs loanword choice' taxonomy bucket.

Authorities:
  - kaa_anatomy.tsv   (Korean Association of Anatomists: en, ko_preferred, ko_synonyms)
  - karp_radiation.tsv (radiation terminology: en, ko)
  - sme_labels_v1.csv  (61 SME corrections: sctid, pipeline_translation_ko, sme_corrected_ko)

For dictionaries we resolve the English term -> SNOMED concept via the International
description index, then compare the authority's preferred Korean against the
extension's forms. For SME we join directly on sctid.

Outputs (data/register_oracle/):
  divergence_kaa.csv, divergence_karp.csv, divergence_sme.csv
  divergence_summary.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "register_oracle"
ORACLE_JSONL = OUT_DIR / "register_oracle.jsonl"

KR_BASE = (
    ROOT
    / "data/korean/SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20251215T120000Z"
    / "Snapshot"
)
INT_EN_DESC = (
    Path.home()
    / "SNOMED-Terminologies/SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z"
    / "Snapshot/Terminology/sct2_Description_Snapshot-en_INT_20260101.txt"
)
KR_EN_DESC = KR_BASE / "Terminology/sct2_Description_Snapshot-en_KR1000267_20251215.txt"

KAA = ROOT / "data/korean/dictionaries/kaa_anatomy.tsv"
KARP = ROOT / "data/korean/dictionaries/karp_radiation.tsv"
SME = ROOT / "data/sme_review/2026-04-24/sme_labels_v1.csv"

WS = re.compile(r"\s+")


def norm(s: str) -> str:
    """Normalise a Korean surface form for comparison: collapse whitespace.

    Spacing is treated as noise here so we detect *register* disagreement, not
    the orthogonal spacing question -- 자기 공명 영상 and 자기공명영상 compare equal.
    """
    return WS.sub("", s.strip())


def load_oracle() -> dict[str, dict]:
    """sctid -> {en_fsn, preferred:[..], acceptable:[..], all:set(norm)}"""
    out: dict[str, dict] = {}
    with ORACLE_JSONL.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            pref = [x["term"] for x in d["forms"] if x["acceptability"] == "preferred"]
            acc = [x["term"] for x in d["forms"] if x["acceptability"] == "acceptable"]
            out[d["sctid"]] = {
                "en_fsn": d["en_fsn"],
                "preferred": pref,
                "acceptable": acc,
                "all_norm": {norm(x["term"]) for x in d["forms"]},
                "all_terms": [x["term"] for x in d["forms"]],
            }
    return out


def load_english_index() -> dict[str, set[str]]:
    """lowercased English term -> {conceptId} across International + KR-en."""
    idx: dict[str, set[str]] = defaultdict(set)
    for path in (INT_EN_DESC, KR_EN_DESC):
        with path.open(encoding="utf-8") as f:
            r = csv.reader(f, delimiter="\t")
            next(r, None)
            for row in r:
                if len(row) < 8 or row[2] != "1":
                    continue
                term = row[7].strip()
                if term:
                    idx[term.lower()].add(row[4])
    return idx


def resolve(en: str, idx: dict[str, set[str]]) -> set[str]:
    """Resolve a dictionary English term to concept ids, trying light variants."""
    e = en.strip().lower()
    for cand in (e, f"{e} (body structure)", f"structure of {e}", f"{e} structure"):
        if cand in idx:
            return idx[cand]
    return set()


def classify_div(auth_ko: str, oracle: dict) -> str:
    """How does the authority's preferred form relate to the extension's forms?"""
    a = norm(auth_ko)
    ext_pref = {norm(x) for x in oracle["preferred"]}
    if a in ext_pref:
        return "agree"                      # extension prefers the same form
    if a in oracle["all_norm"]:
        return "extension_demotes"          # authority form exists but only as 'acceptable'
    return "extension_absent"               # extension never uses the authority form


def dict_divergence(rows, en_key, ko_key, syn_key, idx, oracle, label):
    out = []
    resolved = matched = 0
    for row in rows:
        en = row[en_key].strip()
        auth_ko = row[ko_key].strip()
        if not en or not auth_ko:
            continue
        cids = resolve(en, idx)
        if not cids:
            continue
        resolved += 1
        # pick the first concept that the extension actually translates
        cid = next((c for c in cids if c in oracle), None)
        if not cid:
            continue
        matched += 1
        o = oracle[cid]
        verdict = classify_div(auth_ko, o)
        if verdict == "agree":
            continue
        out.append(
            {
                "sctid": cid,
                "en": en,
                "en_fsn": o["en_fsn"],
                "authority": label,
                "authority_ko": auth_ko,
                "authority_synonyms": row.get(syn_key, "") if syn_key else "",
                "extension_preferred": " | ".join(o["preferred"]),
                "extension_acceptable": " | ".join(o["acceptable"]),
                "verdict": verdict,
            }
        )
    return out, resolved, matched


def main() -> None:
    print("loading oracle ...")
    oracle = load_oracle()
    print(f"  {len(oracle):,} concepts")
    print("loading english index ...")
    idx = load_english_index()
    print(f"  {len(idx):,} english terms")

    summary = {}

    # --- kaa ---
    kaa_rows = list(csv.DictReader(KAA.open(encoding="utf-8"), delimiter="\t"))
    kaa_div, kaa_res, kaa_match = dict_divergence(
        kaa_rows, "en", "ko_preferred", "ko_synonyms", idx, oracle, "kaa_anatomy"
    )
    _write(OUT_DIR / "divergence_kaa.csv", kaa_div)
    summary["kaa"] = _stats(len(kaa_rows), kaa_res, kaa_match, kaa_div)

    # --- karp ---
    karp_rows = list(csv.DictReader(KARP.open(encoding="utf-8"), delimiter="\t"))
    karp_div, karp_res, karp_match = dict_divergence(
        karp_rows, "en", "ko", None, idx, oracle, "karp_radiation"
    )
    _write(OUT_DIR / "divergence_karp.csv", karp_div)
    summary["karp"] = _stats(len(karp_rows), karp_res, karp_match, karp_div)

    # --- sme (join on sctid) ---
    sme_div = []
    sme_rows = [r for r in csv.DictReader(SME.open(encoding="utf-8"))]
    sme_corr = [r for r in sme_rows if r.get("sme_corrected_ko", "").strip()]
    for r in sme_corr:
        cid = r["sctid"].strip()
        o = oracle.get(cid)
        sme_ko = r["sme_corrected_ko"].strip()
        pipe_ko = r["pipeline_translation_ko"].strip()
        row = {
            "sctid": cid,
            "en_fsn": (o or {}).get("en_fsn", r.get("english_term", "")),
            "sme_corrected_ko": sme_ko,
            "pipeline_translation_ko": pipe_ko,
            "extension_preferred": " | ".join(o["preferred"]) if o else "",
            "extension_acceptable": " | ".join(o["acceptable"]) if o else "",
            "in_extension": bool(o),
        }
        if o:
            row["sme_vs_extension"] = classify_div(sme_ko, o)
            row["pipeline_vs_extension"] = classify_div(pipe_ko, o)
        else:
            row["sme_vs_extension"] = "concept_not_in_extension"
            row["pipeline_vs_extension"] = "concept_not_in_extension"
        sme_div.append(row)
    _write(OUT_DIR / "divergence_sme.csv", sme_div)
    in_ext = [r for r in sme_div if r["in_extension"]]
    summary["sme"] = {
        "corrections": len(sme_corr),
        "concept_in_extension": len(in_ext),
        "sme_agrees_extension_preferred": sum(1 for r in in_ext if r["sme_vs_extension"] == "agree"),
        "extension_matches_rejected_pipeline": sum(
            1 for r in in_ext if r["pipeline_vs_extension"] == "agree"
        ),
    }

    (OUT_DIR / "divergence_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        print(f"  wrote {path.name}: 0 rows")
        return
    cols = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path.name}: {len(rows)} rows")


def _stats(total, resolved, matched, div):
    from collections import Counter
    vc = Counter(d["verdict"] for d in div)
    return {
        "dict_rows": total,
        "resolved_to_concept": resolved,
        "concept_in_extension": matched,
        "divergences": len(div),
        "divergence_rate_of_matched": round(len(div) / matched, 3) if matched else None,
        "verdicts": dict(vc),
    }


if __name__ == "__main__":
    main()
