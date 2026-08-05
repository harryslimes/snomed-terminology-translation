#!/usr/bin/env python
"""Thin CLI wrapper: build the Spanish bilingual pool from an Athena bundle.

The logic now lives (language-agnostic) in ``snomed_translation.materialize``;
this just wires the Spanish defaults. See ``docs/add-a-language.md``.

Usage:
    python scripts/data_prep/build_es_pool.py \
        --bundle data/athena/snomed_es \
        --out data/languages/es/pool/athena_es_pool.csv
"""
import argparse
import logging
from pathlib import Path

from snomed_translation.materialize import build_pool


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default="data/athena/snomed_es", type=Path)
    ap.add_argument("--out", default="data/languages/es/pool/athena_es_pool.csv", type=Path)
    ap.add_argument("--language-name", default="Spanish")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build_pool(bundle=a.bundle, out=a.out, language_name=a.language_name)


if __name__ == "__main__":
    main()
