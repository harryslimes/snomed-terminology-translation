#!/usr/bin/env python
"""Thin CLI wrapper: build disjoint train/dev/test splits for Spanish from the
RF2 Spanish Edition. Logic lives in ``snomed_translation.materialize.build_splits``
(language-agnostic). See ``docs/add-a-language.md``.

Usage:
    python scripts/data_prep/build_es_eval.py \
        --rf2 data/spanish-snomed-edition/SnomedCT_SpanishRelease-es_PRODUCTION_20260510T120000Z/Snapshot \
        --pool data/languages/es/pool/athena_es_pool.csv \
        --outdir data/languages/es/evals/dspy_splits --test 200 --dev 100 --train 300
"""
import argparse
import logging
from pathlib import Path

from snomed_translation.materialize import build_splits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rf2", type=Path, required=True, help="RF2 Snapshot dir")
    ap.add_argument("--pool", type=Path, default=Path("data/languages/es/pool/athena_es_pool.csv"))
    ap.add_argument("--outdir", type=Path, default=Path("data/languages/es/evals/dspy_splits"))
    ap.add_argument("--test", type=int, default=200)
    ap.add_argument("--dev", type=int, default=100)
    ap.add_argument("--train", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build_splits(rf2_snapshot=a.rf2, pool_csv=a.pool, outdir=a.outdir, code="es",
                 test=a.test, dev=a.dev, train=a.train, seed=a.seed)


if __name__ == "__main__":
    main()
