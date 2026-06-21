#!/usr/bin/env python
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence


TEXT_EXTENSIONS = {".txt", ".md"}


HEADER_KEYWORDS = (
    "references",
    "reference",
    "additional information",
    "additional info",
    "lisainfo",
    "viited",
    "allikad",
    "kasutatud kirjandus",
    "kirjandus",
    "used literature",
    "bibliography",
    "version",
    "koostaja",
    "author",
    "authors",
    "contact",
    "kontakt",
)


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
PAGE_NUM_RE = re.compile(
    r"^\s*(page|lk\.?|lehek(ülg|g))?\s*\d+\s*((/|of)\s*\d+)?\s*$",
    re.IGNORECASE,
)
AUTHOR_LINE_RE = re.compile(
    r"\b(koostaja|author|authors|contact|kontakt|version|versioon)\b",
    re.IGNORECASE,
)
ADDRESS_HINT_RE = re.compile(
    r"\b(tn\.?|tänav|street|st\.?|road|rd\.?|ave\.?|avenue|puiestee)\b",
    re.IGNORECASE,
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _normalize_for_df(text: str) -> str:
    """Normalization tuned for document-frequency boilerplate detection."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = URL_RE.sub(" ", text)
    text = EMAIL_RE.sub(" ", text)
    text = re.sub(r"\d+", " ", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_light(text: str) -> str:
    """Light normalization used for output text cleanup."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_markdown_links(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)
    return text


def _is_probable_header(line: str) -> tuple[bool, int | None, str]:
    """
    Return (is_header, level, title).
    Level is only known for markdown headers.
    """
    m = re.match(r"^(#{1,6})\s+(.*)$", line)
    if m:
        return True, len(m.group(1)), m.group(2).strip()

    # Heuristic: short-ish all-caps lines can be section headers in OCR output.
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False, None, ""
    letters = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿÕÄÖÜŠŽ\s-]", "", stripped)
    if letters and letters == letters.upper() and len(letters.split()) <= 10:
        return True, None, stripped

    return False, None, ""


def _strip_sections(lines: list[str], header_keywords: Sequence[str]) -> list[str]:
    """
    Remove sections whose headers match any keyword.
    If a header is matched, skip until the next header.
    """
    out: list[str] = []
    skip = False
    skip_level: int | None = None
    keywords = tuple(k.lower() for k in header_keywords)

    for line in lines:
        is_header, level, title = _is_probable_header(line)
        if is_header:
            title_l = title.strip().lower()

            # End a skipped section when we encounter a header that is
            # at the same or higher level (when level is known).
            if skip:
                if level is None or skip_level is None or level <= skip_level:
                    skip = False
                    skip_level = None

            if not skip and any(k in title_l for k in keywords):
                skip = True
                skip_level = level
                continue

        if skip:
            continue
        out.append(line)
    return out


def _drop_layout_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    if PAGE_NUM_RE.match(stripped):
        return True
    if URL_RE.search(stripped):
        return True
    if EMAIL_RE.search(stripped):
        return True
    if PHONE_RE.search(stripped) and re.search(r"\b(tel|telefon|phone|kontakt)\b", stripped, re.I):
        return True
    if AUTHOR_LINE_RE.search(stripped) and len(stripped) <= 200:
        return True
    if ADDRESS_HINT_RE.search(stripped) and re.search(r"\d", stripped) and len(stripped) <= 200:
        return True
    if re.match(r"^[-_=]{4,}$", stripped):
        return True
    return False


def _split_into_chunks(text: str, max_chars: int, min_chars: int) -> list[str]:
    """
    Split into short paragraphs, then further split very long paragraphs by lines.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            if len(para) >= min_chars:
                chunks.append(para)
            continue

        # Further split oversized paragraphs by lines.
        for line in para.splitlines():
            line = line.strip()
            if len(line) >= min_chars:
                chunks.append(line)
    return chunks


def _word_ngrams(tokens: Sequence[str], n: int) -> set[str]:
    if len(tokens) < n:
        return set(tokens) if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(0, len(tokens) - n + 1)}


def _hash_u64(text: str, seed: int) -> int:
    # Stable, fast-enough 64-bit hash via blake2b.
    h = hashlib.blake2b(digest_size=8, person=seed.to_bytes(8, "little"))
    h.update(text.encode("utf-8", errors="ignore"))
    return int.from_bytes(h.digest(), "little", signed=False)


def _minhash_signature(shingles: Iterable[str], num_hashes: int) -> tuple[int, ...]:
    shingles = list(shingles)
    if not shingles:
        # Empty chunks are already filtered, but keep this safe.
        return tuple(0 for _ in range(num_hashes))
    sig: list[int] = []
    for seed in range(num_hashes):
        sig.append(min(_hash_u64(s, seed) for s in shingles))
    return tuple(sig)


def _band_keys(signature: Sequence[int], band_size: int) -> Iterable[tuple[int, tuple[int, ...]]]:
    if band_size <= 0:
        raise ValueError("band_size must be > 0")
    if len(signature) % band_size != 0:
        raise ValueError("num_hashes must be divisible by band_size")
    bands = len(signature) // band_size
    for band_idx in range(bands):
        start = band_idx * band_size
        yield band_idx, tuple(signature[start : start + band_size])


def _iter_text_files(root: Path, recursive: bool) -> list[Path]:
    paths = root.rglob("*") if recursive else root.glob("*")
    files = [p for p in paths if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS]
    return sorted(files)


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


@dataclasses.dataclass(frozen=True)
class Chunk:
    doc_id: int
    doc_path: Path
    ordinal: int
    raw: str
    norm_df: str


@dataclasses.dataclass
class CleanStats:
    documents: int = 0
    chunks_total: int = 0
    chunks_after_rules: int = 0
    chunks_after_df: int = 0
    chunks_after_minhash: int = 0
    dropped_by_rules: int = 0
    dropped_by_df: int = 0
    dropped_by_minhash: int = 0
    df_threshold_docs: int = 0
    minhash_threshold_docs: int = 0


def clean_corpus(
    input_dir: Path,
    output_dir: Path,
    recursive: bool,
    df_percent_threshold: float,
    minhash_percent_threshold: float,
    max_chars: int,
    min_chars: int,
    shingle_size: int,
    num_hashes: int,
    band_size: int,
    header_keywords: Sequence[str],
    edge_block_lines: int,
) -> CleanStats:
    files = _iter_text_files(input_dir, recursive=recursive)
    stats = CleanStats(documents=len(files))

    if not files:
        output_dir.mkdir(parents=True, exist_ok=True)
        return stats

    # First pass: per-doc cleanup, chunking, and layout edge blocks.
    chunks_by_doc: dict[int, list[Chunk]] = {}
    edge_blocks_start: list[tuple[int, str]] = []
    edge_blocks_end: list[tuple[int, str]] = []

    for doc_id, path in enumerate(files):
        raw = _read_text(path)
        raw = _strip_markdown_links(raw)
        lines = [ln.rstrip("\n") for ln in raw.splitlines()]

        lines = _strip_sections(lines, header_keywords=header_keywords)
        filtered_lines = [ln for ln in lines if not _drop_layout_noise(ln)]
        cleaned_text = "\n".join(filtered_lines).strip()

        # Capture repeated top/bottom blocks using light normalization.
        if edge_block_lines > 0 and filtered_lines:
            start_block = "\n".join(filtered_lines[:edge_block_lines]).strip()
            end_block = "\n".join(filtered_lines[-edge_block_lines:]).strip()
            if start_block:
                edge_blocks_start.append((doc_id, _normalize_for_df(start_block)))
            if end_block:
                edge_blocks_end.append((doc_id, _normalize_for_df(end_block)))

        doc_chunks: list[Chunk] = []
        for ordinal, chunk in enumerate(_split_into_chunks(cleaned_text, max_chars=max_chars, min_chars=min_chars)):
            norm = _normalize_for_df(chunk)
            if not norm:
                continue
            doc_chunks.append(
                Chunk(
                    doc_id=doc_id,
                    doc_path=path,
                    ordinal=ordinal,
                    raw=chunk,
                    norm_df=norm,
                )
            )

        chunks_by_doc[doc_id] = doc_chunks
        stats.chunks_total += len(doc_chunks)

    # Identify frequent edge blocks (headers/footers) and drop exact matches.
    def _edge_df(blocks: list[tuple[int, str]]) -> Counter[str]:
        df = Counter()
        per_doc: dict[int, set[str]] = defaultdict(set)
        for doc_id, block in blocks:
            if block:
                per_doc[doc_id].add(block)
        for doc_blocks in per_doc.values():
            df.update(doc_blocks)
        return df

    edge_df_start = _edge_df(edge_blocks_start)
    edge_df_end = _edge_df(edge_blocks_end)

    def _doc_threshold(n_docs: int, pct: float) -> int:
        if n_docs <= 1:
            return 1
        # Avoid degenerate behavior on small corpora where ceil(n * pct) becomes 1.
        return min(n_docs, max(2, math.ceil(n_docs * pct)))

    df_threshold_docs = _doc_threshold(len(files), df_percent_threshold)
    minhash_threshold_docs = _doc_threshold(len(files), minhash_percent_threshold)
    stats.df_threshold_docs = df_threshold_docs
    stats.minhash_threshold_docs = minhash_threshold_docs

    frequent_edge_blocks = {
        block
        for block, count in (edge_df_start + edge_df_end).items()
        if count >= df_threshold_docs
    }

    # Second pass: drop chunks that exactly match frequent edge blocks.
    for doc_id, doc_chunks in list(chunks_by_doc.items()):
        kept: list[Chunk] = []
        for ch in doc_chunks:
            if ch.norm_df in frequent_edge_blocks:
                stats.dropped_by_rules += 1
                continue
            kept.append(ch)
        chunks_by_doc[doc_id] = kept
        stats.chunks_after_rules += len(kept)

    # Document-frequency boilerplate detection.
    df_counter: Counter[str] = Counter()
    for doc_chunks in chunks_by_doc.values():
        df_counter.update({ch.norm_df for ch in doc_chunks})

    frequent_chunks = {chunk for chunk, count in df_counter.items() if count >= df_threshold_docs}

    for doc_id, doc_chunks in list(chunks_by_doc.items()):
        kept: list[Chunk] = []
        for ch in doc_chunks:
            if ch.norm_df in frequent_chunks:
                stats.dropped_by_df += 1
                continue
            kept.append(ch)
        chunks_by_doc[doc_id] = kept
        stats.chunks_after_df += len(kept)

    # MinHash near-duplicate boilerplate detection.
    # We use LSH banding to find near-duplicate clusters that appear in many docs.
    bucket_docs: dict[tuple[int, tuple[int, ...]], set[int]] = defaultdict(set)
    bucket_chunks: dict[tuple[int, tuple[int, ...]], list[Chunk]] = defaultdict(list)

    for doc_chunks in chunks_by_doc.values():
        for ch in doc_chunks:
            tokens = ch.norm_df.split()
            shingles = _word_ngrams(tokens, n=shingle_size)
            sig = _minhash_signature(shingles, num_hashes=num_hashes)
            for key in _band_keys(sig, band_size=band_size):
                bucket_docs[key].add(ch.doc_id)
                bucket_chunks[key].append(ch)

    boilerplate_buckets = {key for key, docs in bucket_docs.items() if len(docs) >= minhash_threshold_docs}

    boilerplate_chunk_keys: set[tuple[int, int]] = set()
    for key in boilerplate_buckets:
        for ch in bucket_chunks[key]:
            boilerplate_chunk_keys.add((ch.doc_id, ch.ordinal))

    for doc_id, doc_chunks in list(chunks_by_doc.items()):
        kept: list[Chunk] = []
        for ch in doc_chunks:
            if (ch.doc_id, ch.ordinal) in boilerplate_chunk_keys:
                stats.dropped_by_minhash += 1
                continue
            kept.append(ch)
        chunks_by_doc[doc_id] = kept
        stats.chunks_after_minhash += len(kept)

    # Write cleaned output.
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_id_to_path = {i: p for i, p in enumerate(files)}
    for doc_id, doc_chunks in chunks_by_doc.items():
        in_path = doc_id_to_path[doc_id]
        rel = _relative_to(in_path, input_dir)
        out_path = output_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n\n".join(ch.raw.strip() for ch in doc_chunks if ch.raw.strip())
        out_path.write_text(_normalize_light(text) + "\n", encoding="utf-8")

    return stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Corpus-level boilerplate removal using document frequency and MinHash near-duplicate detection."
        )
    )
    p.add_argument("--input-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--recursive", action="store_true", help="Recurse into subdirectories.")

    p.add_argument(
        "--df-percent-threshold",
        type=float,
        default=0.02,
        help="Drop chunks that appear in at least this fraction of documents (e.g., 0.01-0.03).",
    )
    p.add_argument(
        "--minhash-percent-threshold",
        type=float,
        default=0.02,
        help="Drop chunks whose MinHash buckets appear in at least this fraction of documents.",
    )

    p.add_argument("--min-chars", type=int, default=40)
    p.add_argument("--max-chars", type=int, default=800)

    p.add_argument("--shingle-size", type=int, default=5, help="Word shingle size.")
    p.add_argument("--num-hashes", type=int, default=64, help="MinHash signature length.")
    p.add_argument(
        "--band-size",
        type=int,
        default=4,
        help="LSH band size; num-hashes must be divisible by band-size.",
    )

    p.add_argument(
        "--edge-block-lines",
        type=int,
        default=3,
        help="Number of top/bottom lines to treat as header/footer candidates.",
    )
    p.add_argument(
        "--header-keywords",
        type=str,
        default=",".join(HEADER_KEYWORDS),
        help="Comma-separated header keywords to strip sections under.",
    )

    p.add_argument(
        "--stats-path",
        type=Path,
        default=None,
        help="Optional path to write JSON stats.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    header_keywords = [k.strip() for k in args.header_keywords.split(",") if k.strip()]

    if args.num_hashes % args.band_size != 0:
        raise SystemExit("--num-hashes must be divisible by --band-size.")
    if not (0 < args.df_percent_threshold <= 1):
        raise SystemExit("--df-percent-threshold must be in (0, 1].")
    if not (0 < args.minhash_percent_threshold <= 1):
        raise SystemExit("--minhash-percent-threshold must be in (0, 1].")

    stats = clean_corpus(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        recursive=args.recursive,
        df_percent_threshold=args.df_percent_threshold,
        minhash_percent_threshold=args.minhash_percent_threshold,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        shingle_size=args.shingle_size,
        num_hashes=args.num_hashes,
        band_size=args.band_size,
        header_keywords=header_keywords,
        edge_block_lines=args.edge_block_lines,
    )

    stats_dict = dataclasses.asdict(stats)
    print(json.dumps(stats_dict, indent=2, ensure_ascii=False))
    if args.stats_path:
        args.stats_path.parent.mkdir(parents=True, exist_ok=True)
        args.stats_path.write_text(json.dumps(stats_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
