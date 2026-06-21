from __future__ import annotations

import argparse
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Sequence
import sys

import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.qdrant_store import BGEM3Config, BGEM3Embedder, QdrantHybridStore


load_dotenv()


logger = logging.getLogger("snomed.build_qdrant")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


DATA_DIR = ROOT_DIR / "data"


def batched(iterable: Iterable[dict], batch_size: int) -> Iterator[list[dict]]:
    batch: list[dict] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def resolve_monolingual_dir(preferred: Path, fallback: Path) -> Path:
    return preferred if preferred.exists() else fallback


def iter_txt_documents(
    root: Path,
    collection_name: str,
    limit: int | None,
    skip: int = 0,
) -> Iterable[dict]:
    files = sorted(root.rglob("*.txt"))
    if limit is not None:
        files = files[:limit]
    for idx, path in enumerate(files, start=1):
        if idx <= skip:
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            continue
        if not text:
            continue
        doc_id = path.stem
        yield {
            "id": idx,
            "text": text,
            "payload": {
                "doc_id": doc_id,
                "source": collection_name,
                "lang": "et",
                "text": text,
                "path": str(path.relative_to(DATA_DIR)),
            },
        }


def paired_translations_items(
    csv_path: Path,
    limit: int | None,
    skip: int = 0,
) -> Iterable[dict]:
    df = pd.read_csv(csv_path).dropna(subset=["EN", "EE"])
    if limit is not None:
        df = df.head(limit)

    for i, row in enumerate(df.itertuples(index=False), start=1):
        en = str(row.EN).strip()
        ee = str(row.EE).strip()
        if not en or not ee:
            continue

        id_en = i * 2 - 1
        id_et = i * 2
        if id_en > skip:
            yield {
                "id": id_en,
                "text": en,
                "payload": {
                    "source": "paired_translations",
                    "direction": "EN->EE",
                    "lang": "en",
                    "text": en,
                    "translation": ee,
                },
            }
        if id_et > skip:
            yield {
                "id": id_et,
                "text": ee,
                "payload": {
                    "source": "paired_translations",
                    "direction": "ET->EN",
                    "lang": "et",
                    "text": ee,
                    "translation": en,
                },
            }


def sonaveeb_items(
    csv_path: Path,
    limit: int | None,
    skip: int = 0,
) -> Iterable[dict]:
    df = pd.read_csv(csv_path).dropna(subset=["term", "definition"])
    if limit is not None:
        df = df.head(limit)
    for i, row in enumerate(df.itertuples(index=False), start=1):
        if i <= skip:
            continue
        term = str(row.term).strip()
        definition = str(row.definition).strip()
        lang = str(getattr(row, "lang", "et")).strip() or "et"
        if not term or not definition:
            continue
        text = f"{term}\n\n{definition}"
        yield {
            "id": f"sonaveeb:{i}:{term}",
            "text": text,
            "payload": {
                "source": "sonaveeb",
                "doc_id": term,
                "term": term,
                "definition": definition,
                "lang": lang,
                "text": definition,
            },
        }


def count_files(root: Path, limit: int | None) -> int:
    files = sorted(root.rglob("*.txt"))
    if limit is not None:
        files = files[:limit]
    return len(files)


def count_paired_rows(csv_path: Path, limit: int | None) -> int:
    df = pd.read_csv(csv_path, usecols=["EN", "EE"]).dropna(subset=["EN", "EE"])
    if limit is not None:
        df = df.head(limit)
    return df.shape[0] * 2


def count_sonaveeb(csv_path: Path, limit: int | None) -> int:
    df = pd.read_csv(csv_path, usecols=["term", "definition"]).dropna(subset=["term", "definition"])
    if limit is not None:
        df = df.head(limit)
    return df.shape[0]


@dataclass
class CollectionSpec:
    name: str
    count_fn: Callable[[int | None], int]
    items_fn: Callable[[int | None, int], Iterable[dict]]


def index_collection(
    spec: CollectionSpec,
    embedder: BGEM3Embedder,
    store: QdrantHybridStore,
    batch_size: int,
    resume: bool,
    limit: int | None,
) -> None:
    total = spec.count_fn(limit)
    logger.info("Indexing collection '%s' with %d items.", spec.name, total)
    if total == 0:
        logger.warning("No items found for collection '%s'. Skipping.", spec.name)
        return

    existing_collections = {c.name for c in store.client.get_collections().collections}
    skip = 0
    if resume and spec.name in existing_collections:
        try:
            count_result = store.client.count(collection_name=spec.name, exact=True)
            skip = int(count_result.count)
        except Exception as exc:
            logger.warning("Failed to read count for '%s': %s", spec.name, exc)
            skip = 0
        logger.info("Resuming '%s' from %d items.", spec.name, skip)
    else:
        store.recreate_hybrid_collection(spec.name, embedder.dense_size)

    remaining = max(total - skip, 0)
    if remaining == 0:
        logger.info("Collection '%s' is already complete.", spec.name)
        return

    progress = tqdm(total=remaining, desc=f"{spec.name}", unit="doc")
    for batch in batched(spec.items_fn(limit, skip), batch_size):
        texts = [item["text"] for item in batch]
        ids = [item["id"] for item in batch]
        payloads = [item["payload"] for item in batch]

        dense, sparse = embedder.encode_documents(texts)
        store.upsert_hybrid_points(spec.name, ids, dense, sparse, payloads)
        progress.update(len(batch))
    progress.close()
    logger.info("Finished indexing '%s'.", spec.name)


def main(args: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build Qdrant hybrid indexes with BGE-M3 embeddings.")
    parser.add_argument(
        "--collections",
        nargs="*",
        default=["paired_translations", "eesti_arst", "kliinikum", "haiglateliit", "sonaveeb"],
        help="Collections to build.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume indexing without recreating collections; skips already indexed items.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit per collection for faster iteration during development.",
    )
    parsed = parser.parse_args(args=args)

    embedder = BGEM3Embedder(BGEM3Config())
    store = QdrantHybridStore()

    # Validate connectivity early.
    store.client.get_collections()

    paired_csv = DATA_DIR / "EE-EN" / "all_bilingual_pairs.csv"

    eesti_arst_dir = resolve_monolingual_dir(
        DATA_DIR / "cleaned" / "eesti_arst_dedup",
        DATA_DIR / "eesti_arst",
    )
    kliinikum_dir = resolve_monolingual_dir(
        DATA_DIR / "cleaned" / "kliinikum_dedup",
        DATA_DIR / "kliinikum",
    )
    haiglateliit_dir = resolve_monolingual_dir(
        DATA_DIR / "cleaned" / "haiglateliit_dedup",
        DATA_DIR / "haiglateliit",
    )
    sonaveeb_csv = DATA_DIR / "sonaveeb.csv"

    collections_map: dict[str, CollectionSpec] = {
        "paired_translations": CollectionSpec(
            name="paired_translations",
            count_fn=lambda limit: count_paired_rows(paired_csv, limit),
            items_fn=lambda limit, skip: paired_translations_items(paired_csv, limit, skip),
        ),
        "eesti_arst": CollectionSpec(
            name="eesti_arst",
            count_fn=lambda limit: count_files(eesti_arst_dir, limit),
            items_fn=lambda limit, skip: iter_txt_documents(eesti_arst_dir, "eesti_arst", limit, skip),
        ),
        "kliinikum": CollectionSpec(
            name="kliinikum",
            count_fn=lambda limit: count_files(kliinikum_dir, limit),
            items_fn=lambda limit, skip: iter_txt_documents(kliinikum_dir, "kliinikum", limit, skip),
        ),
        "haiglateliit": CollectionSpec(
            name="haiglateliit",
            count_fn=lambda limit: count_files(haiglateliit_dir, limit),
            items_fn=lambda limit, skip: iter_txt_documents(haiglateliit_dir, "haiglateliit", limit, skip),
        ),
    }

    if sonaveeb_csv.exists():
        collections_map["sonaveeb"] = CollectionSpec(
            name="sonaveeb",
            count_fn=lambda limit: count_sonaveeb(sonaveeb_csv, limit),
            items_fn=lambda limit, skip: sonaveeb_items(sonaveeb_csv, limit, skip),
        )
    else:
        logger.warning("sonaveeb.csv not found at %s. Skipping sonaveeb collection.", sonaveeb_csv)

    for name in parsed.collections:
        spec = collections_map.get(name)
        if spec is None:
            logger.warning("Unknown collection '%s'. Skipping.", name)
            continue
        index_collection(
            spec=spec,
            embedder=embedder,
            store=store,
            batch_size=embedder.config.batch_size,
            resume=parsed.resume,
            limit=parsed.limit,
        )


if __name__ == "__main__":
    main()
