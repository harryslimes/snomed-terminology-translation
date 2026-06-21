#!/usr/bin/env python3
"""Run BGE-M3 lookups for new concepts and merge into the existing cache.

The default lookup_cache.json holds top-K pairs for the 3,693 procedure
eval concepts. To translate the 100-concept long-tail sample we need
top-K pairs for those new SCTIDs too. This script:

  1. Reads sctids from a CSV (defaults to the long-tail sample).
  2. For each, runs YAKE keyword extraction + BGE-M3 hybrid lookup
     against the existing Qdrant collection (paired_translations_ko).
  3. Merges results into the existing lookup_cache.json (additive — does
     not overwrite entries that already exist).

Mirrors the lookup logic of translate_korean_with_lookup.py:--prepare-lookups.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

LOOKUP_CACHE = ROOT_DIR / "data" / "evals" / "korean" / "lookup_cache.json"
COLLECTION = "paired_translations_ko"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prep_lookups")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=ROOT_DIR / "data" / "evals" / "korean" / "long_tail_sme" / "sample_100.csv")
    parser.add_argument("--topn", type=int, default=5)
    parser.add_argument("--cache", type=Path, default=LOOKUP_CACHE)
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing entries for the same sctid (default: skip)")
    args = parser.parse_args()

    import yake
    from agent.qdrant_store import BGEM3Config, BGEM3Embedder, QdrantHybridStore, direction_filter

    rows = list(csv.DictReader(args.input.open(encoding="utf-8")))
    log.info("Input: %d concepts from %s", len(rows), args.input.relative_to(ROOT_DIR))

    cache: dict[str, list[list[str]]] = {}
    if args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
        log.info("Existing cache: %d entries", len(cache))

    work = [r for r in rows if args.overwrite or r["sctid"] not in cache]
    log.info("To process: %d (skipping %d already cached)",
             len(work), len(rows) - len(work))

    if not work:
        log.info("Nothing to do.")
        return

    embedder = BGEM3Embedder(BGEM3Config())
    store = QdrantHybridStore()
    store.client.get_collections()
    filt = direction_filter("EN->KO")

    t0 = time.monotonic()
    for i, row in enumerate(work, 1):
        text = row["preferred_term"]
        kw_extractor = yake.KeywordExtractor(lan="en", n=1, dedupLim=0.7, top=10)
        keywords = [kw for kw, _ in kw_extractor.extract_keywords(text)]
        if text not in keywords:
            keywords = [text, *keywords]

        hits_by_id: dict[str, tuple[float, dict]] = {}
        for keyword in keywords:
            try:
                dense, sparse = embedder.encode_query(keyword)
                result = store.hybrid_query(
                    collection_name=COLLECTION,
                    dense_vector=dense, sparse_vector=sparse,
                    limit=max(args.topn * 3, args.topn),
                    query_filter=filt,
                )
                for point in result.points:
                    payload = getattr(point, "payload", {}) or {}
                    pid = str(getattr(point, "id", ""))
                    score = float(getattr(point, "score", 0.0))
                    if pid:
                        prev = hits_by_id.get(pid)
                        if prev is None or score > prev[0]:
                            hits_by_id[pid] = (score, payload)
            except Exception as exc:
                log.warning("Lookup failed for %r: %s", keyword, exc)

        ranked = sorted(hits_by_id.values(), key=lambda x: x[0], reverse=True)
        pairs = [[p.get("text", ""), p.get("translation", "")] for _, p in ranked[: args.topn]]
        cache[row["sctid"]] = pairs

        if i % 20 == 0:
            elapsed = time.monotonic() - t0
            rate = i / elapsed if elapsed > 0 else 0
            log.info("Progress: %d/%d  %.1f /s  ETA %.0fs", i, len(work), rate, (len(work) - i) / max(rate, 1e-6))

    args.cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %s (%d total entries)", args.cache.relative_to(ROOT_DIR), len(cache))


if __name__ == "__main__":
    main()
