"""Build EN<->KO bilingual term pairs from multiple sources.

Mirrors the layout of data/EE-EN/: per-source 2-col CSVs (EN,KO) plus a
combined all_bilingual_pairs.csv.

Sources:
  1. Athena CONCEPT.csv + CONCEPT_SYNONYM.csv  (EDI, KCD7)
  2. SNOMED CT Korean national release  joined with SNOMED International
  3. LOINC linguistic variant (koKR13) - part-level pairs
  4. WHO ICD-11 Korean linearization (via API, optional)

Run:
    python scripts/data_prep/build_en_ko_pairs.py [--skip-icd11]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "EN-KO"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Source paths --------------------------------------------------------
ATHENA_DIR = Path.home() / "Projects/snomed-ct-entity-linking-new/data/athena"
SNOMED_KR_DIR = (
    ROOT
    / "data/korean/SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20251215T120000Z"
    / "Snapshot/Terminology"
)
SNOMED_INT_DIR = (
    Path.home()
    / "SNOMED-Terminologies/SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z"
    / "Snapshot/Terminology"
)
LOINC_KO_CSV = (
    ROOT
    / "data/loinc/Loinc_2.82/AccessoryFiles/LinguisticVariants/koKR13LinguisticVariant.csv"
)
LOINC_EN_CSV = ROOT / "data/loinc/Loinc_2.82/LoincTableCore/LoincTableCore.csv"

KO_LANG_ID = "4175771"  # Athena language_concept_id for Korean
FSN_TYPE = "900000000000003001"  # SNOMED FSN typeId
SYNONYM_TYPE = "900000000000013009"

csv.field_size_limit(sys.maxsize)


def write_pairs(name: str, rows: list[tuple[str, str]]) -> int:
    seen = set()
    deduped = []
    for en, ko in rows:
        en, ko = en.strip(), ko.strip()
        if not en or not ko:
            continue
        key = (en.lower(), ko)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((en, ko))
    path = OUT_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["EN", "KO"])
        w.writerows(deduped)
    print(f"  wrote {path.name}: {len(deduped):,} pairs")
    return len(deduped)


# ---- Athena --------------------------------------------------------------
def build_athena() -> dict[str, int]:
    print("[athena] loading CONCEPT.csv ...")
    # concept_id -> (vocabulary_id, concept_name)
    concept_info: dict[str, tuple[str, str]] = {}
    target_vocabs = {"EDI", "KCD7"}
    with (ATHENA_DIR / "CONCEPT.csv").open(encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        header = next(r)
        for row in r:
            if len(row) < 4:
                continue
            vocab = row[3]
            if vocab in target_vocabs:
                concept_info[row[0]] = (vocab, row[1])
    print(f"[athena] {len(concept_info):,} EDI+KCD7 concepts")

    print("[athena] streaming CONCEPT_SYNONYM.csv ...")
    by_vocab: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with (ATHENA_DIR / "CONCEPT_SYNONYM.csv").open(encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        next(r)
        for row in r:
            if len(row) < 3 or row[2] != KO_LANG_ID:
                continue
            cid = row[0]
            if cid not in concept_info:
                continue
            vocab, en = concept_info[cid]
            by_vocab[vocab].append((en, row[1]))

    counts = {}
    for vocab, rows in by_vocab.items():
        counts[vocab] = write_pairs(vocab, rows)
    return counts


# ---- SNOMED --------------------------------------------------------------
def build_snomed() -> dict[str, int]:
    print("[snomed] loading KR Korean descriptions ...")
    # conceptId -> {fsn: str|None, synonyms: set[str]}
    kr: dict[str, dict] = defaultdict(lambda: {"fsn": None, "syn": set()})
    with (SNOMED_KR_DIR / "sct2_Description_Snapshot-ko_KR1000267_20251215.txt").open(
        encoding="utf-8"
    ) as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            if row["active"] != "1":
                continue
            cid = row["conceptId"]
            term = row["term"]
            if row["typeId"] == FSN_TYPE:
                kr[cid]["fsn"] = term
            else:
                kr[cid]["syn"].add(term)
    print(f"[snomed] {len(kr):,} KR concepts with KO descriptions")

    print("[snomed] loading International English descriptions (filtered) ...")
    en_fsn: dict[str, str] = {}
    en_syn: dict[str, set[str]] = defaultdict(set)
    int_path = SNOMED_INT_DIR / "sct2_Description_Snapshot-en_INT_20260101.txt"
    with int_path.open(encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            if row["active"] != "1":
                continue
            cid = row["conceptId"]
            if cid not in kr:
                continue
            if row["typeId"] == FSN_TYPE:
                en_fsn[cid] = row["term"]
            else:
                en_syn[cid].add(row["term"])

    # Also fold in KR-extension English descriptions (for KR-only concepts)
    kr_en_path = SNOMED_KR_DIR / "sct2_Description_Snapshot-en_KR1000267_20251215.txt"
    if kr_en_path.exists():
        with kr_en_path.open(encoding="utf-8") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r:
                if row["active"] != "1":
                    continue
                cid = row["conceptId"]
                if cid not in kr:
                    continue
                if row["typeId"] == FSN_TYPE and cid not in en_fsn:
                    en_fsn[cid] = row["term"]
                elif row["typeId"] != FSN_TYPE:
                    en_syn[cid].add(row["term"])

    # FSN canonical pair
    fsn_pairs: list[tuple[str, str]] = []
    syn_pairs: list[tuple[str, str]] = []
    for cid, data in kr.items():
        en = en_fsn.get(cid)
        if not en:
            continue
        # KR release leaves FSNs in English; Korean terms are stored as synonyms.
        # Canonical pair = EN FSN <-> first KO synonym (or KO FSN if it exists).
        ko_canonical = data["fsn"] or (next(iter(data["syn"])) if data["syn"] else None)
        if ko_canonical:
            fsn_pairs.append((en, ko_canonical))
        for ko_s in data["syn"]:
            syn_pairs.append((en, ko_s))

    counts = {}
    counts["SNOMED"] = write_pairs("SNOMED", fsn_pairs)
    counts["SNOMED_synonyms"] = write_pairs("SNOMED_synonyms", syn_pairs)
    return counts


# ---- LOINC ---------------------------------------------------------------
def build_loinc() -> dict[str, int]:
    print("[loinc] loading koKR linguistic variant ...")
    # LOINC_NUM -> dict of part_field -> KO value
    ko_parts: dict[str, dict[str, str]] = {}
    fields = ["COMPONENT", "PROPERTY", "TIME_ASPCT", "SYSTEM", "SCALE_TYP", "METHOD_TYP"]
    with LOINC_KO_CSV.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            d = {k: row[k].strip() for k in fields if row.get(k, "").strip()}
            if d:
                ko_parts[row["LOINC_NUM"]] = d

    print("[loinc] loading LoincTableCore ...")
    pairs: list[tuple[str, str]] = []
    with LOINC_EN_CSV.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            num = row["LOINC_NUM"]
            ko = ko_parts.get(num)
            if not ko:
                continue
            for field, ko_val in ko.items():
                en_val = row.get(field, "").strip()
                if en_val and ko_val:
                    pairs.append((en_val, ko_val))

    counts = {"LOINC": write_pairs("LOINC", pairs)}
    return counts


# ---- ICD-11 --------------------------------------------------------------
def build_icd11() -> dict[str, int]:
    cid = os.environ.get("WHO_ICD_CLIENT_ID")
    csec = os.environ.get("WHO_ICD_CLIENT_SECRET")
    if not (cid and csec):
        env_file = ROOT / ".env.local"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            cid = os.environ.get("WHO_ICD_CLIENT_ID")
            csec = os.environ.get("WHO_ICD_CLIENT_SECRET")
    if not (cid and csec):
        print("[icd11] no creds, skipping")
        return {}

    try:
        import requests
    except ImportError:
        print("[icd11] requests not installed, skipping")
        return {}

    print("[icd11] authenticating ...")
    tok = requests.post(
        "https://icdaccessmanagement.who.int/connect/token",
        data={
            "client_id": cid,
            "client_secret": csec,
            "scope": "icdapi_access",
            "grant_type": "client_credentials",
        },
        timeout=30,
    ).json()["access_token"]

    base = "https://id.who.int/icd"
    def get(url, lang):
        return requests.get(
            url,
            headers={
                "Authorization": f"Bearer {tok}",
                "Accept": "application/json",
                "Accept-Language": lang,
                "API-Version": "v2",
            },
            timeout=30,
        ).json()

    # Walk MMS linearization recursively
    print("[icd11] crawling MMS linearization (this takes a while) ...")
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []

    def walk(url: str):
        if url in seen:
            return
        seen.add(url)
        try:
            en = get(url, "en")
            ko = get(url, "ko")
        except Exception as e:
            print(f"  fetch error {url}: {e}")
            return
        en_title = (en.get("title") or {}).get("@value", "").strip()
        ko_title = (ko.get("title") or {}).get("@value", "").strip()
        if en_title and ko_title and en_title != ko_title:
            pairs.append((en_title, ko_title))
        for child in en.get("child", []) or []:
            walk(child)
        if len(seen) % 500 == 0:
            print(f"  visited {len(seen)} entities, {len(pairs)} pairs")

    root = base + "/release/11/2024-01/mms"
    walk(root)
    return {"ICD11": write_pairs("ICD11", pairs)}


# ---- main ----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-icd11", action="store_true")
    ap.add_argument("--only", choices=["athena", "snomed", "loinc", "icd11"])
    args = ap.parse_args()

    all_counts: dict[str, int] = {}
    steps = {
        "athena": build_athena,
        "snomed": build_snomed,
        "loinc": build_loinc,
    }
    if not args.skip_icd11:
        steps["icd11"] = build_icd11

    if args.only:
        steps = {args.only: steps[args.only]}

    for name, fn in steps.items():
        print(f"\n=== {name} ===")
        all_counts.update(fn())

    # Combined file
    print("\n[combined] building all_bilingual_pairs.csv ...")
    combined: list[tuple[str, str, str]] = []
    seen = set()
    for src in ["EDI", "KCD7", "SNOMED", "SNOMED_synonyms", "LOINC", "ICD11"]:
        p = OUT_DIR / f"{src}.csv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            r = csv.reader(f)
            next(r)
            for en, ko in r:
                key = (en.lower(), ko)
                if key in seen:
                    continue
                seen.add(key)
                combined.append((en, ko, src))
    out = OUT_DIR / "all_bilingual_pairs.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["EN", "KO", "source"])
        w.writerows(combined)
    print(f"  wrote {out.name}: {len(combined):,} unique pairs")

    print("\n=== summary ===")
    for k, v in all_counts.items():
        print(f"  {k:20s} {v:>10,}")
    print(f"  {'COMBINED':20s} {len(combined):>10,}")


if __name__ == "__main__":
    main()
