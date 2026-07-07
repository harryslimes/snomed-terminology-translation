"""Build a per-concept Korean *register oracle* directly from RF2 sources.

For every SNOMED concept that the Korean Managed Service extension translates,
record which Korean surface forms the extension actually uses, tagged with the
extension's own PREFERRED/ACCEPTABLE designation (from the ko language refset)
and a best-effort register label (sino | native | loan | mixed).

This reads the RF2 release files, NOT the derived data/EN-KO/*.csv and NOT a
Snowstorm server, so the oracle is reproducible from the terminology drop:

  - KR extension  : sct2_Description_Snapshot-ko  + der2_cRefset_LanguageSnapshot-ko
  - KR extension  : sct2_Description_Snapshot-en   (English FSNs for KR-only concepts)
  - International  : sct2_Description_Snapshot-en   (English FSN + synonyms -> concept index)

Outputs (data/register_oracle/):
  register_oracle.csv    one row per (concept, korean form)
  register_oracle.jsonl  one row per concept, forms nested (machine-friendly)
  build_manifest.json    source file paths + sha1 + row counts (provenance)

Usage:
  python scripts/register_oracle/build_register_oracle.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

ROOT = Path(__file__).resolve().parents[2]
KR_BASE = (
    ROOT
    / "data/korean/SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20251215T120000Z"
    / "Snapshot"
)
INT_BASE = (
    Path.home()
    / "SNOMED-Terminologies/SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z"
    / "Snapshot/Terminology"
)
OUT_DIR = ROOT / "data" / "register_oracle"
OUT_DIR.mkdir(parents=True, exist_ok=True)

KR_KO_DESC = KR_BASE / "Terminology/sct2_Description_Snapshot-ko_KR1000267_20251215.txt"
KR_EN_DESC = KR_BASE / "Terminology/sct2_Description_Snapshot-en_KR1000267_20251215.txt"
KR_LANG_KO = KR_BASE / "Refset/Language/der2_cRefset_LanguageSnapshot-ko_KR1000267_20251215.txt"
INT_EN_DESC = INT_BASE / "sct2_Description_Snapshot-en_INT_20260101.txt"

FSN_TYPE = "900000000000003001"
SYN_TYPE = "900000000000013009"
PREFERRED = "900000000000548007"
ACCEPTABLE = "900000000000549004"

HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")

# Native (non-Sino) Korean roots that surface in medical/anatomy terms. Presence
# of one of these signals that the form is at least partly native rather than the
# default Sino-Korean. This is a LABEL aid only; the dictionary/extension evidence
# is the authority, per the analysis note.
NATIVE_ROOTS = [
    "다리", "팔", "손", "발", "머리", "목", "등", "배", "가슴", "허리", "어깨",
    "무릎", "발목", "손목", "팔꿈치", "엉덩이", "볼기", "코", "귀", "눈", "입",
    "이마", "턱", "뺨", "혀", "잇몸", "이빨", "뼈", "살", "피", "땀", "침", "젖",
    "쓸개", "지라", "콩팥", "허파", "밥통", "창자", "오줌", "똥", "물", "골",
    "낟알", "빗장", "복사", "정강", "종아리", "넓적다리", "새끼", "엄지", "검지",
]


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_register(term: str) -> str:
    """Best-effort register label. loan > native > sino precedence.

    - loan  : contains Latin script (e.g. 'B-스캔', 'MRI 검사'), i.e. an
              untranslated/transliterated borrowing surfaces in the form.
    - native: contains a known native Korean root (다리, 팔, 코 ...).
    - mixed : both a native root AND other Hangul (heuristic 'partly native').
    - sino  : default for Hangul medical terminology (overwhelmingly Sino-Korean).

    NOTE: sino-vs-native is not resolved morphologically here (that needs a hanja
    lexicon); everything without a known native root defaults to sino. Treat the
    label as a reviewer aid, never as ground truth.
    """
    if LATIN.search(term):
        return "loan"
    hit = next((r for r in NATIVE_ROOTS if r in term), None)
    if hit:
        # if the term is *only* the native root (+ spaces) call it native,
        # otherwise it's a native/Sino compound.
        stripped = term.replace(" ", "")
        return "native" if stripped == hit else "mixed"
    return "sino"


def load_english_index() -> tuple[dict[str, str], dict[str, set[str]]]:
    """Return (conceptId -> English FSN, lowercased English term -> {conceptId}).

    FSN comes from the International FSN; the term index folds in ALL active
    International descriptions (FSN + synonyms) plus KR-extension English so that
    dictionary lookups (which use bare anatomy names, not FSNs) can resolve to a
    concept.
    """
    fsn: dict[str, str] = {}
    term_index: dict[str, set[str]] = defaultdict(set)

    def feed(path: Path, label: str) -> int:
        n = 0
        with path.open(encoding="utf-8") as f:
            r = csv.reader(f, delimiter="\t")
            next(r, None)
            for row in r:
                # id,eff,active,module,conceptId,lang,typeId,term,caseSig
                if len(row) < 8 or row[2] != "1":
                    continue
                cid, typeid, term = row[4], row[6], row[7].strip()
                if not term:
                    continue
                if typeid == FSN_TYPE and cid not in fsn:
                    fsn[cid] = term
                term_index[term.lower()].add(cid)
                n += 1
        print(f"  [{label}] {n:,} active descriptions")
        return n

    feed(INT_EN_DESC, "int-en")
    feed(KR_EN_DESC, "kr-en")
    print(f"  FSNs: {len(fsn):,}  |  distinct english terms: {len(term_index):,}")
    return fsn, term_index


def load_acceptability() -> dict[str, str]:
    """descriptionId -> acceptabilityId (preferred/acceptable) from ko lang refset."""
    acc: dict[str, str] = {}
    with KR_LANG_KO.open(encoding="utf-8") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)
        for row in r:
            # id,eff,active,module,refsetId,referencedComponentId,acceptabilityId
            if len(row) < 7 or row[2] != "1":
                continue
            acc[row[5]] = row[6]
    print(f"  language refset members: {len(acc):,}")
    return acc


def load_korean_forms(acc: dict[str, str]) -> dict[str, list[dict]]:
    """conceptId -> [ {term, acceptability, register}... ] from ko descriptions."""
    by_concept: dict[str, list[dict]] = defaultdict(list)
    seen = 0
    with KR_KO_DESC.open(encoding="utf-8") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)
        for row in r:
            if len(row) < 8 or row[2] != "1":
                continue
            desc_id, cid, term = row[0], row[4], row[7].strip()
            if not term:
                continue
            a = acc.get(desc_id)
            label = "preferred" if a == PREFERRED else ("acceptable" if a == ACCEPTABLE else "unrefset")
            by_concept[cid].append(
                {"term": term, "acceptability": label, "register": classify_register(term)}
            )
            seen += 1
    # order preferred first, then acceptable, then unrefset
    order = {"preferred": 0, "acceptable": 1, "unrefset": 2}
    for cid, forms in by_concept.items():
        forms.sort(key=lambda d: order.get(d["acceptability"], 3))
    print(f"  korean descriptions: {seen:,} across {len(by_concept):,} concepts")
    return by_concept


def main() -> None:
    print("[1/4] English index (International + KR-en) ...")
    fsn, _term_index = load_english_index()
    print("[2/4] ko acceptability refset ...")
    acc = load_acceptability()
    print("[3/4] korean forms ...")
    by_concept = load_korean_forms(acc)

    print("[4/4] writing oracle ...")
    csv_path = OUT_DIR / "register_oracle.csv"
    jsonl_path = OUT_DIR / "register_oracle.jsonl"
    n_rows = 0
    with csv_path.open("w", newline="", encoding="utf-8") as cf, jsonl_path.open(
        "w", encoding="utf-8"
    ) as jf:
        w = csv.writer(cf)
        w.writerow(
            ["sctid", "en_fsn", "ko_term", "acceptability", "register", "n_forms"]
        )
        for cid, forms in sorted(by_concept.items()):
            en = fsn.get(cid, "")
            jf.write(
                json.dumps(
                    {"sctid": cid, "en_fsn": en, "forms": forms},
                    ensure_ascii=False,
                )
                + "\n"
            )
            for form in forms:
                w.writerow(
                    [cid, en, form["term"], form["acceptability"], form["register"], len(forms)]
                )
                n_rows += 1

    manifest = {
        "sources": {
            name: {"path": str(p), "sha1": sha1(p)}
            for name, p in {
                "kr_ko_desc": KR_KO_DESC,
                "kr_en_desc": KR_EN_DESC,
                "kr_lang_ko": KR_LANG_KO,
                "int_en_desc": INT_EN_DESC,
            }.items()
        },
        "counts": {
            "concepts": len(by_concept),
            "form_rows": n_rows,
            "fsn_resolved": sum(1 for c in by_concept if c in fsn),
        },
    }
    (OUT_DIR / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )
    print(f"  wrote {csv_path.name}: {n_rows:,} form rows / {len(by_concept):,} concepts")
    print(f"  fsn resolved for {manifest['counts']['fsn_resolved']:,} concepts")


if __name__ == "__main__":
    main()
