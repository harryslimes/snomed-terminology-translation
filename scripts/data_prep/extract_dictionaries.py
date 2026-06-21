#!/usr/bin/env python3
"""Extract Korean radiology termbases from source markdown into TSV dictionaries.

Two sources, one output file each:

  1. Terms_from_KoreanAssociation_of_Anatomies.md
     Fixed-width three-column format: <Korean>  <English>  <Latin>
     Produces data/korean/dictionaries/kaa_anatomy.tsv

  2. Terms_from_TheKoreanAssociation_for_RadiationProtection.md
     Tab/whitespace-separated two-column: <English>\\t<Korean>
     Produces data/korean/dictionaries/karp_radiation.tsv

Both extractions are heuristic — the source markdown was produced by PDF
conversion and contains irregular line breaks and footnote markers. The
parsers skip malformed lines rather than try to recover. Missing rows are
acceptable; the dictionaries are for prompt-time reference, not
completeness.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "data" / "korean" / "RadiologyEditorialGuide_markdown"
OUT_DIR = ROOT_DIR / "data" / "korean" / "dictionaries"

HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
LATIN_RE = re.compile(r"[A-Za-z]")
WHITESPACE_SPLIT_RE = re.compile(r"\s{2,}")   # 2+ whitespace = column separator
FOOTNOTE_MARKER_RE = re.compile(r"\s+\d+\s*$")  # trailing "…  2"
SEMICOLON_SPLIT_RE = re.compile(r"\s*;\s*")
PAREN_RE = re.compile(r"^\((.*)\)$")


def clean(s: str) -> str:
    """Normalise a cell: strip, collapse internal whitespace, drop footnote markers."""
    s = s.strip()
    s = FOOTNOTE_MARKER_RE.sub("", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def strip_parens(s: str) -> str:
    m = PAREN_RE.match(s.strip())
    return m.group(1).strip() if m else s.strip()


def extract_kaa(src: Path, out: Path) -> tuple[int, int]:
    """Parse the KAA triples file.

    Expected layout per usable line:
        <Korean>  <English>  <Latin>
    Separator is 2+ whitespace. Korean and English may carry synonyms
    separated by semicolons. We preserve the first English term as the
    canonical key; additional English synonyms become extra rows keyed
    on each synonym.
    """
    rows: list[dict] = []
    seen_keys: set[str] = set()
    skipped = 0

    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line:
            continue
        parts = [clean(p) for p in WHITESPACE_SPLIT_RE.split(line.lstrip()) if p.strip()]
        if len(parts) < 2:
            continue
        ko_raw = parts[0]
        en_raw = parts[1]
        la_raw = parts[2] if len(parts) >= 3 else ""

        if not HANGUL_RE.search(ko_raw):
            skipped += 1
            continue
        if not LATIN_RE.search(en_raw):
            skipped += 1
            continue

        ko_terms = [clean(strip_parens(t)) for t in SEMICOLON_SPLIT_RE.split(ko_raw) if t.strip()]
        en_terms = [clean(strip_parens(t)) for t in SEMICOLON_SPLIT_RE.split(en_raw) if t.strip()]
        ko_terms = [t for t in ko_terms if t and HANGUL_RE.search(t)]
        en_terms = [t for t in en_terms if t and LATIN_RE.search(t) and len(t) <= 120]

        if not ko_terms or not en_terms:
            skipped += 1
            continue

        ko_preferred = ko_terms[0]
        ko_synonyms = "; ".join(ko_terms[1:]) if len(ko_terms) > 1 else ""

        for en in en_terms:
            key = en.lower().strip()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append({
                "en": en,
                "ko_preferred": ko_preferred,
                "ko_synonyms": ko_synonyms,
                "la": la_raw,
            })

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["en", "ko_preferred", "ko_synonyms", "la"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), skipped


def extract_karp(src: Path, out: Path) -> tuple[int, int]:
    """Parse the KARP flat English→Korean glossary.

    Expected layout per usable line:
        <English>\\t<Korean>
    The source uses a mix of single tab and wide-whitespace separators.
    """
    rows: list[dict] = []
    seen_keys: set[str] = set()
    skipped = 0

    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        # Split on tab first; fall back to 2+ whitespace
        if "\t" in line:
            parts = [clean(p) for p in line.split("\t") if p.strip()]
        else:
            parts = [clean(p) for p in WHITESPACE_SPLIT_RE.split(line.lstrip()) if p.strip()]

        if len(parts) < 2:
            skipped += 1
            continue
        en = parts[0]
        ko = parts[-1]

        if not LATIN_RE.search(en):
            skipped += 1
            continue
        if not HANGUL_RE.search(ko):
            skipped += 1
            continue
        if len(en) > 120 or len(ko) > 120:
            skipped += 1
            continue

        key = en.lower().strip()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append({"en": en, "ko": ko})

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["en", "ko"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), skipped


def main() -> None:
    kaa_src = SRC_DIR / "Terms_from_KoreanAssociation_of_Anatomies.md"
    kaa_out = OUT_DIR / "kaa_anatomy.tsv"
    karp_src = SRC_DIR / "Terms_from_TheKoreanAssociation_for_RadiationProtection.md"
    karp_out = OUT_DIR / "karp_radiation.tsv"

    for src in (kaa_src, karp_src):
        if not src.exists():
            sys.exit(f"Missing source: {src}")

    kaa_n, kaa_skipped = extract_kaa(kaa_src, kaa_out)
    karp_n, karp_skipped = extract_karp(karp_src, karp_out)

    print(f"KAA  → {kaa_out.relative_to(ROOT_DIR)}: {kaa_n} entries ({kaa_skipped} skipped)")
    print(f"KARP → {karp_out.relative_to(ROOT_DIR)}: {karp_n} entries ({karp_skipped} skipped)")


if __name__ == "__main__":
    main()
