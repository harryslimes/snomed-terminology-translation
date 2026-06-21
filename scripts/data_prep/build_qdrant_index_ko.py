#!/usr/bin/env python3
"""Index EN-KO bilingual pairs into Qdrant for Korean translation lookup.

Creates collection 'paired_translations_ko' with BGE-M3 hybrid embeddings,
mirroring the Estonian paired_translations collection structure.

Usage:
    python scripts/data_prep/build_qdrant_index_ko.py [--resume] [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.qdrant_store import BGEM3Config, BGEM3Embedder, QdrantHybridStore

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("build_qdrant_ko")

COLLECTION = "paired_translations_ko"
CSV_PATH = ROOT_DIR / "data" / "EN-KO" / "all_bilingual_pairs.csv"


def batched(iterable: Iterable, batch_size: int) -> Iterator[list]:
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def iter_items(csv_path: Path, limit: int | None, skip: int = 0) -> Iterable[dict]:
    df = pd.read_csv(csv_path).dropna(subset=["EN", "KO"])
    if limit is not None:
        df = df.head(limit)

    for i, row in enumerate(df.itertuples(index=False), start=1):
        en = str(row.EN).strip()
        ko = str(row.KO).strip()
        source = str(getattr(row, "source", "")).strip()
        if not en or not ko:
            continue

        id_en = i * 2 - 1
        id_ko = i * 2
        if id_en > skip:
            yield {
                "id": id_en,
                "text": en,
                "payload": {
                    "source": "paired_translations",
                    "direction": "EN->KO",
                    "lang": "en",
                    "text": en,
                    "translation": ko,
                    "vocab_source": source,
                },
            }
        if id_ko > skip:
            yield {
                "id": id_ko,
                "text": ko,
                "payload": {
                    "source": "paired_translations",
                    "direction": "KO->EN",
                    "lang": "ko",
                    "text": ko,
                    "translation": en,
                    "vocab_source": source,
                },
            }


def count_items(csv_path: Path, limit: int | None) -> int:
    df = pd.read_csv(csv_path, usecols=["EN", "KO"]).dropna(subset=["EN", "KO"])
    if limit is not None:
        df = df.head(limit)
    return df.shape[0] * 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    embedder = BGEM3Embedder(BGEM3Config())
    store = QdrantHybridStore()
    store.client.get_collections()  # validate connectivity

    total = count_items(CSV_PATH, args.limit)
    logger.info("Total items to index: %d", total)

    skip = 0
    existing = {c.name for c in store.client.get_collections().collections}
    if args.resume and COLLECTION in existing:
        skip = int(store.client.count(collection_name=COLLECTION, exact=True).count)
        logger.info("Resuming from %d", skip)
    else:
        store.recreate_hybrid_collection(COLLECTION, embedder.dense_size)

    remaining = max(total - skip, 0)
    if remaining == 0:
        logger.info("Collection already complete.")
        return

    progress = tqdm(total=remaining, desc=COLLECTION, unit="doc")
    for batch in batched(iter_items(CSV_PATH, args.limit, skip), embedder.config.batch_size):
        texts = [item["text"] for item in batch]
        ids = [item["id"] for item in batch]
        payloads = [item["payload"] for item in batch]

        dense, sparse = embedder.encode_documents(texts)
        store.upsert_hybrid_points(COLLECTION, ids, dense, sparse, payloads)
        progress.update(len(batch))
    progress.close()
    logger.info("Done. Indexed %d items into '%s'.", total, COLLECTION)


if __name__ == "__main__":
    main()
