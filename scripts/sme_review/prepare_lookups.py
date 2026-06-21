#!/usr/bin/env python3
"""Prepare BGE-M3 lookup cache for an arbitrary eval CSV.

Standalone variant of translate_korean_with_lookup.py's --prepare-lookups
mode that doesn't write to the hardcoded data/evals/korean/lookup_cache.json
path. Use for SME-review batches against the untranslated long tail.
"""
from __future__ import annotations
import argparse, csv, json, logging, sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prep_lookups")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True,
                        help="CSV with sctid + preferred_term columns.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection", default="paired_translations_ko")
    parser.add_argument("--topn", type=int, default=5)
    args = parser.parse_args()

    import yake
    from agent.qdrant_store import BGEM3Config, BGEM3Embedder, QdrantHybridStore, direction_filter

    rows = list(csv.DictReader(args.input.open(encoding="utf-8")))
    log.info("Preparing lookups for %d terms (topn=%d)...", len(rows), args.topn)

    embedder = BGEM3Embedder(BGEM3Config())
    store = QdrantHybridStore()
    store.client.get_collections()

    filt = direction_filter("EN->KO")
    cache: dict[str, list[list[str]]] = {}

    for i, row in enumerate(rows, 1):
        text = row["preferred_term"]
        kw = yake.KeywordExtractor(lan="en", n=1, dedupLim=0.7, top=10)
        keywords = [k for k, _ in kw.extract_keywords(text)]
        if text not in keywords:
            keywords = [text, *keywords]
        hits: dict[str, tuple[float, dict]] = {}
        for keyword in keywords:
            try:
                dense, sparse = embedder.encode_query(keyword)
                res = store.hybrid_query(
                    collection_name=args.collection,
                    dense_vector=dense,
                    sparse_vector=sparse,
                    limit=max(args.topn * 3, args.topn),
                    query_filter=filt,
                )
                for p in res.points:
                    payload = getattr(p, "payload", {}) or {}
                    pid = str(getattr(p, "id", ""))
                    score = float(getattr(p, "score", 0.0))
                    if pid and (pid not in hits or score > hits[pid][0]):
                        hits[pid] = (score, payload)
            except Exception as exc:
                log.warning("Lookup failed for %r: %s", keyword, exc)

        ranked = sorted(hits.values(), key=lambda x: x[0], reverse=True)
        cache[row["sctid"]] = [[p.get("text", ""), p.get("translation", "")] for _, p in ranked[:args.topn]]

        if i % 200 == 0:
            log.info("  lookups: %d/%d", i, len(rows))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log.info("Saved %d lookups to %s", len(cache), args.output)


if __name__ == "__main__":
    main()
