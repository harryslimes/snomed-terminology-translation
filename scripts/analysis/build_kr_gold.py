"""Build the Korean-extension back-translation gold set.

Joins the flattened EN<->KO bilingual pairs (the KR extension's SNOMED rows,
which carry the English FSN/synonym but not the concept id) back to the
International RF2 to recover each concept's ``sctid`` and hierarchy (the FSN
semantic tag — disorder / procedure / finding / body structure / ...).

Output: one row per concept ``sctid,korean,hierarchy,en`` — the gold for the
round-trip back-translation evaluation, classifiable by hierarchy region.

Reproducible: deterministic (first Korean term per concept, by file order), no
network. Run from the plugin repo root:

    python scripts/analysis/build_kr_gold.py \
        --int  ~/SNOMED-Terminologies/SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z \
        --pairs data/EN-KO/all_bilingual_pairs.csv \
        --out  /tmp/kr_gold_full.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from snomed_translation.snomed_rf2 import read_concept_terms

SNOMED_SOURCES = {"SNOMED", "SNOMED_synonyms"}


def semantic_tag(fsn: str) -> str:
    return fsn.rsplit("(", 1)[-1].rstrip(")").strip() if fsn.endswith(")") else ""


def en_to_concept(int_root: str) -> dict[str, tuple[str, str]]:
    """Map every English surface form (FSN with + without tag, and each synonym),
    lower-cased, to ``(sctid, hierarchy)``. First writer wins (FSN before
    synonyms), so a term shared across concepts resolves to its primary owner."""
    out: dict[str, tuple[str, str]] = {}
    for ct in read_concept_terms(int_root):
        tag = semantic_tag(ct.fsn)
        out.setdefault(ct.fsn.strip().lower(), (ct.sctid, tag))
        out.setdefault(ct.fsn.rsplit(" (", 1)[0].lower(), (ct.sctid, tag))
        for syn in ct.synonyms:
            out.setdefault(syn.strip().lower(), (ct.sctid, tag))
    return out


def build(int_root: str, pairs_csv: str, out_csv: str) -> dict:
    term2 = en_to_concept(int_root)
    # sctid -> (korean, hierarchy, en); keep the first Korean term seen per concept
    gold: dict[str, tuple[str, str, str]] = {}
    rows = 0
    with open(pairs_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("source") not in SNOMED_SOURCES:
                continue
            rows += 1
            hit = term2.get((r.get("EN") or "").strip().lower())
            if not hit:
                continue
            sctid, tag = hit
            ko = (r.get("KO") or "").strip()
            if sctid not in gold and ko:
                gold[sctid] = (ko, tag, (r.get("EN") or "").strip())

    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sctid", "korean", "hierarchy", "en"])
        for sctid, (ko, tag, en) in gold.items():
            w.writerow([sctid, ko, tag, en])

    by_tag: dict[str, int] = {}
    for _, tag, _ in gold.values():
        by_tag[tag] = by_tag.get(tag, 0) + 1
    return {"scanned_rows": rows, "concepts": len(gold), "by_hierarchy": by_tag,
            "out": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--int", required=True, help="International RF2 release root")
    ap.add_argument("--pairs", default="data/EN-KO/all_bilingual_pairs.csv")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    m = build(a.int, a.pairs, a.out)
    print(f"scanned {m['scanned_rows']} SNOMED rows -> {m['concepts']} concepts")
    for tag, n in sorted(m["by_hierarchy"].items(), key=lambda x: -x[1]):
        print(f"  {n:6d}  {tag or '(no tag)'}")
    print("wrote", m["out"])


if __name__ == "__main__":
    main()
