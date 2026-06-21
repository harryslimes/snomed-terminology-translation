#!/usr/bin/env python3
"""Score translations by cross-lingual BGE-M3 embedding similarity.

For each (English source, Korean translation) pair, compute cosine
similarity between their BGE-M3 dense embeddings. BGE-M3 is a multilingual
dense+sparse model; for EN↔KO medical terms a direct cross-lingual
semantic similarity is a cheap proxy for "did the translation preserve
the meaning."

Output CSV has the original translation columns plus:
  - sim_en_ko_translation : cosine similarity between source EN and our Korean
  - sim_en_ko_reference   : cosine similarity between source EN and the KR reference
                            (for diagnostic — should be high by construction)
  - sim_translation_ref   : cosine similarity between our Korean and the KR reference

Use cases:
  1. Rank translations by sim_en_ko_translation; bottom-tail rows are the most
     likely "obviously wrong" candidates to surface for review.
  2. Compare sim_en_ko_translation to sim_en_ko_reference per row — a gap
     suggests the translation lost meaning present in the reference.
  3. For the long tail with no reference, sim_en_ko_translation alone is the
     signal.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.qdrant_store import BGEM3Config, BGEM3Embedder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("xling_sim")


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise cosine similarity between two L2-normalised-or-not arrays."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    an = np.linalg.norm(a, axis=1, keepdims=True) + 1e-12
    bn = np.linalg.norm(b, axis=1, keepdims=True) + 1e-12
    return np.sum((a / an) * (b / bn), axis=1)


def embed_batch(embedder: BGEM3Embedder, texts: list[str]) -> np.ndarray:
    """BGE-M3 dense embeddings for a list of strings, as float32 (N, D)."""
    dense, _ = embedder.encode_documents(texts)
    return np.asarray(dense, dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translations", type=Path, required=True,
                        help="CSV with columns sctid, preferred_term, ko_reference, translation.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    rows = list(csv.DictReader(args.translations.open(encoding="utf-8")))
    rows = [r for r in rows if not r.get("translation", "").startswith("ERROR")]
    log.info("Loaded %d translation rows", len(rows))

    log.info("Loading BGE-M3 embedder...")
    t0 = time.monotonic()
    embedder = BGEM3Embedder(BGEM3Config(batch_size=args.batch_size))
    log.info("  loaded in %.1fs", time.monotonic() - t0)

    en_src = [r["preferred_term"] for r in rows]
    ko_ref = [r.get("ko_reference", "") for r in rows]
    ko_trans = [r["translation"] for r in rows]

    log.info("Embedding source English (%d)...", len(en_src))
    t0 = time.monotonic()
    en_emb = embed_batch(embedder, en_src)
    log.info("  %.1fs", time.monotonic() - t0)

    log.info("Embedding Korean reference (%d)...", len(ko_ref))
    t0 = time.monotonic()
    ref_emb = embed_batch(embedder, ko_ref)
    log.info("  %.1fs", time.monotonic() - t0)

    log.info("Embedding Korean translation (%d)...", len(ko_trans))
    t0 = time.monotonic()
    trans_emb = embed_batch(embedder, ko_trans)
    log.info("  %.1fs", time.monotonic() - t0)

    sim_en_trans = cosine(en_emb, trans_emb)
    sim_en_ref = cosine(en_emb, ref_emb)
    sim_trans_ref = cosine(trans_emb, ref_emb)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) + [
        "sim_en_ko_translation", "sim_en_ko_reference", "sim_translation_ref",
    ]
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, r in enumerate(rows):
            out = dict(r)
            out["sim_en_ko_translation"] = f"{float(sim_en_trans[i]):.4f}"
            out["sim_en_ko_reference"] = f"{float(sim_en_ref[i]):.4f}"
            out["sim_translation_ref"] = f"{float(sim_trans_ref[i]):.4f}"
            writer.writerow(out)

    log.info("Wrote %s", args.output)

    # Summary statistics
    def pct(arr, q): return float(np.percentile(arr, q))
    log.info("sim(en, translation)  mean=%.3f  p10=%.3f  p50=%.3f  p90=%.3f",
             float(sim_en_trans.mean()), pct(sim_en_trans, 10), pct(sim_en_trans, 50), pct(sim_en_trans, 90))
    log.info("sim(en, reference)    mean=%.3f  p10=%.3f  p50=%.3f  p90=%.3f",
             float(sim_en_ref.mean()), pct(sim_en_ref, 10), pct(sim_en_ref, 50), pct(sim_en_ref, 90))
    log.info("sim(translation, ref) mean=%.3f  p10=%.3f  p50=%.3f  p90=%.3f",
             float(sim_trans_ref.mean()), pct(sim_trans_ref, 10), pct(sim_trans_ref, 50), pct(sim_trans_ref, 90))


if __name__ == "__main__":
    main()
