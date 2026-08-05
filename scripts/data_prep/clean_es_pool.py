#!/usr/bin/env python
"""Strip trailing SNOMED semantic tags from the Spanish side of the pool.

The Athena pool's Spanish synonyms include FSN-derived strings that carry a
trailing semantic tag, e.g. "hemorragia intraparto (trastorno)". The English
side and the RF2 preferred-term gold are tag-free, so these tags are noise that
confuses exemplar-guided translation (the model learns to add/keep tags
inconsistently). We strip ONLY trailing "(tag)" where tag is a real SNOMED-ES
semantic tag — the authoritative set derived from the RF2 Spanish FSNs — so
legitimate parenthetical content is preserved.

Usage:
    python scripts/data_prep/clean_es_pool.py \
        --rf2-desc data/spanish-snomed-edition/.../Snapshot/Terminology/sct2_Description_*.txt \
        --in  data/languages/es/pool/athena_es_pool.csv \
        --out data/languages/es/pool/athena_es_pool_clean.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("clean_es_pool")
csv.field_size_limit(sys.maxsize)

FSN_TYPE = "900000000000003001"
TRAILING_PAREN = re.compile(r"\s*\(([^()]+)\)\s*$")


def semantic_tags(desc_file: Path) -> set[str]:
    """Authoritative Spanish semantic-tag set = trailing (...) of active es FSNs."""
    tags: set[str] = set()
    with desc_file.open(encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)
        for row in r:
            if len(row) >= 8 and row[2] == "1" and row[5] == "es" and row[6] == FSN_TYPE:
                m = TRAILING_PAREN.search(row[7])
                if m:
                    tags.add(m.group(1).strip())
    log.info("derived %d distinct semantic tags from RF2 FSNs", len(tags))
    return tags


def strip_tag(term: str, tags: set[str]) -> str:
    m = TRAILING_PAREN.search(term)
    if m and m.group(1).strip() in tags:
        return term[: m.start()].rstrip()
    return term


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rf2-desc", type=Path, required=True)
    ap.add_argument("--in", dest="inp", type=Path,
                    default=Path("data/languages/es/pool/athena_es_pool.csv"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/languages/es/pool/athena_es_pool_clean.csv"))
    a = ap.parse_args()

    tags = semantic_tags(a.rf2_desc)
    changed = kept = 0
    seen: set[tuple[str, str]] = set()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.inp.open(encoding="utf-8", newline="") as f, \
         a.out.open("w", encoding="utf-8", newline="") as g:
        r = csv.DictReader(f)
        w = csv.writer(g)
        w.writerow(["sctid", "en", "target", "source"])
        for row in r:
            cleaned = strip_tag(row["target"], tags)
            if cleaned != row["target"]:
                changed += 1
            if not cleaned:
                continue
            key = (row["sctid"], cleaned)
            if key in seen:
                continue
            seen.add(key)
            w.writerow([row["sctid"], row["en"], cleaned, row["source"]])
            kept += 1
    log.info("stripped tags on %d rows; wrote %d unique pairs -> %s", changed, kept, a.out)


if __name__ == "__main__":
    main()
