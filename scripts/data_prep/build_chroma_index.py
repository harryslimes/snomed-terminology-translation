from __future__ import annotations

import argparse
import logging
import os
import sys
from itertools import count
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
from dotenv import load_dotenv
from more_itertools import chunked
from tqdm import tqdm

import chromadb
from llama_index.core.node_parser.text import SentenceSplitter


load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("snomed.build_chroma")

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"


def iter_text_files(root: Path, limit: int | None = None) -> Iterable[Path]:
    files = sorted(path for path in root.iterdir() if path.suffix == ".txt")
    if limit is not None:
        files = files[:limit]
    return files


def insert_document_to_chroma(
    client: chromadb.PersistentClient,
    document_text: str,
    metadata: dict,
    doc_id: str,
    collection_name: str,
    splitter: SentenceSplitter,
) -> int:
    chunks = splitter.split_text(document_text)
    if not chunks:
        return 0

    collection = client.get_or_create_collection(name=collection_name)
    chunk_ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    collection.add(
        documents=chunks,
        metadatas=[metadata] * len(chunks),
        ids=chunk_ids,
    )
    return len(chunks)


def build_monolingual_collection(
    client: chromadb.PersistentClient,
    collection_name: str,
    source_dir: Path,
    limit: int | None,
    resume: bool,
) -> None:
    splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=200)
    files = list(iter_text_files(source_dir, limit))

    total_chunks = 0
    logger.info("Indexing '%s' from %s (%d files).", collection_name, source_dir, len(files))
    collection = client.get_or_create_collection(name=collection_name)

    for path in tqdm(files, desc=collection_name, unit="file"):
        if resume:
            try:
                existing = collection.get(ids=[f"{path.name}_0"])["ids"]
                if existing:
                    continue
            except Exception:
                pass
        text = path.read_text(encoding="utf-8", errors="ignore")
        total_chunks += insert_document_to_chroma(
            client=client,
            document_text=text,
            metadata={"filename": path.name},
            doc_id=path.name,
            collection_name=collection_name,
            splitter=splitter,
        )
    logger.info("Finished '%s'. Total chunks: %d.", collection_name, total_chunks)


def build_paired_translations(
    client: chromadb.PersistentClient,
    csv_path: Path,
    limit: int | None,
    resume: bool,
) -> None:
    df = pd.read_csv(csv_path).dropna(subset=["EN", "EE"])
    if limit is not None:
        df = df.head(limit)

    collection = client.get_or_create_collection(name="paired_translations")
    existing_count = collection.count() if resume else 0
    id_iter = count(existing_count + 1)
    to_skip = existing_count
    chunk_size = 100
    n_iter = max(1, df.shape[0] // chunk_size)

    logger.info("Indexing 'paired_translations' from %s (%d rows).", csv_path, df.shape[0])
    for rows in tqdm(chunked(df.itertuples(index=False), chunk_size), total=n_iter, unit="chunk"):
        rows = list(rows)
        if not rows:
            continue

        et_to_en = list(
            pd.DataFrame(rows)[["EE", "EN"]]
            .dropna()
            .groupby("EE")
            .first()
            .reset_index()
            .itertuples()
        )
        if et_to_en:
            if to_skip:
                if to_skip >= len(et_to_en):
                    to_skip -= len(et_to_en)
                    et_to_en = []
                else:
                    et_to_en = et_to_en[to_skip:]
                    to_skip = 0
        if et_to_en:
            collection.add(
                documents=[r.EE for r in et_to_en],
                metadatas=[
                    {"direction": "ET->EN", "translation": r.EN}
                    for r in et_to_en
                ],
                ids=[f"{next(id_iter)}_ET" for _ in et_to_en],
            )

        en_to_et = list(
            pd.DataFrame(rows)[["EE", "EN"]]
            .dropna()
            .groupby("EN")
            .first()
            .reset_index()
            .itertuples()
        )
        if en_to_et:
            if to_skip:
                if to_skip >= len(en_to_et):
                    to_skip -= len(en_to_et)
                    en_to_et = []
                else:
                    en_to_et = en_to_et[to_skip:]
                    to_skip = 0
        if en_to_et:
            collection.add(
                documents=[r.EN for r in en_to_et],
                metadatas=[
                    {"direction": "EN->EE", "translation": r.EE}
                    for r in en_to_et
                ],
                ids=[f"{next(id_iter)}_EN" for _ in en_to_et],
            )

    logger.info("paired_translations count: %d", collection.count())


def build_sonaveeb(
    client: chromadb.PersistentClient,
    csv_path: Path,
    limit: int | None,
    resume: bool,
) -> None:
    df = pd.read_csv(csv_path).dropna(subset=["term", "desc", "lang"])
    if limit is not None:
        df = df.head(limit)

    collection = client.get_or_create_collection("sonaveeb")
    logger.info("Indexing 'sonaveeb' from %s (%d rows).", csv_path, df.shape[0])
    for row in tqdm(df.itertuples(index=False), total=df.shape[0], unit="row"):
        if resume:
            try:
                existing = collection.get(ids=[row.term])["ids"]
                if existing:
                    continue
            except Exception:
                pass
        collection.upsert(
            documents=[row.desc],
            metadatas=[{"lang": row.lang}],
            ids=[row.term],
        )
    logger.info("sonaveeb count: %d", collection.count())


def main(args: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Rebuild legacy Chroma indexes.")
    parser.add_argument(
        "--collections",
        nargs="*",
        default=["paired_translations", "eesti_arst", "kliinikum", "haiglateliit", "sonaveeb"],
        help="Collections to build.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit per collection.",
    )
    parser.add_argument(
        "--chroma-path",
        default=str(ROOT_DIR / "notebooks" / "chroma"),
        help="Path for chroma PersistentClient storage.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete existing collections before indexing.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume indexing without deleting collections.",
    )
    parsed = parser.parse_args(args=args)

    chroma_path = Path(parsed.chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))

    if parsed.recreate and parsed.resume:
        raise SystemExit("Use either --recreate or --resume, not both.")

    if parsed.recreate:
        for name in parsed.collections:
            try:
                client.delete_collection(name=name)
                logger.info("Deleted collection '%s'.", name)
            except Exception:
                pass

    if "paired_translations" in parsed.collections:
        build_paired_translations(
            client,
            DATA_DIR / "EE-EN" / "all_bilingual_pairs.csv",
            parsed.limit,
            resume=parsed.resume,
        )

    if "eesti_arst" in parsed.collections:
        build_monolingual_collection(
            client,
            "eesti_arst",
            DATA_DIR / "eesti_arst",
            parsed.limit,
            resume=parsed.resume,
        )

    if "kliinikum" in parsed.collections:
        build_monolingual_collection(
            client,
            "kliinikum",
            DATA_DIR / "kliinikum",
            parsed.limit,
            resume=parsed.resume,
        )

    if "haiglateliit" in parsed.collections:
        build_monolingual_collection(
            client,
            "haiglateliit",
            DATA_DIR / "haiglateliit",
            parsed.limit,
            resume=parsed.resume,
        )

    if "sonaveeb" in parsed.collections:
        sonaveeb_csv = DATA_DIR / "sonaveeb.csv"
        if sonaveeb_csv.exists():
            build_sonaveeb(client, sonaveeb_csv, parsed.limit, resume=parsed.resume)
        else:
            logger.warning("sonaveeb.csv not found at %s. Skipping.", sonaveeb_csv)


if __name__ == "__main__":
    main()
