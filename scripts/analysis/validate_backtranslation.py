#!/usr/bin/env python
"""Validate the back-translation confidence method against the gold KR pairs.

The ladder (see the research-planning "Back-translation confidence" problem):

  1. CEILING — look up each concept's *real English* (FSN) in the SNOMED index;
     recovery should be ~100%. If not, the retrieval is broken (not translation).
  2. MEASUREMENT — translate the gold *Korean* term KO->EN with an LLM + prompt,
     look that up, and measure recovery. The gap from the ceiling is the loss the
     round trip introduces. Recovered concepts at a high score = high confidence;
     the misses are where a terminologist should review.

The KO->EN prompt is a first-class, tunable knob: evolve SYSTEM_PROMPT (or pass
--prompt-file) and re-run to measure whether recovery improves.

Prereqs: a built SNOMED index (snomed_index.build_index over the gold concepts;
this script reuses the collection named by release+model), a running Qdrant, and
a chat-completions model server (see configs/models.json).

    python scripts/analysis/validate_backtranslation.py \
        --int /path/to/SnomedCT_InternationalRF2_... \
        --base-url http://localhost:8086 \
        --model cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4 -n 60
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "translation"))

from snomed_translation import snomed_index as si  # noqa: E402
from snomed_translation.snomed_rf2 import (  # noqa: E402
    SYNONYM_TYPE, read_concept_terms, release_id,
)
from translate_korean_with_lookup import translate_one  # noqa: E402

SYSTEM_PROMPT = (
    "You are a medical terminologist. Translate the given Korean SNOMED CT "
    "clinical term into its standard English medical term. Output ONLY the "
    "English term, with no notes, no quotes, no semantic tag."
)


def _gold_korean(kr_desc_file: str) -> dict[str, str]:
    """{sctid -> a Korean term} from the KR extension (prefer a synonym)."""
    ko: dict[str, tuple[str, str]] = {}
    with open(kr_desc_file, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r.get("active") != "1" or r.get("languageCode") != "ko":
                continue
            cid, typ, term = r["conceptId"], r.get("typeId"), (r.get("term") or "").strip()
            if term and (cid not in ko or (typ == SYNONYM_TYPE and ko[cid][1] != SYNONYM_TYPE)):
                ko[cid] = (term, typ)
    return {c: v[0] for c, v in ko.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--int", required=True, help="International RF2 release root.")
    ap.add_argument("--kr", help="KR extension ko Description Snapshot file.")
    ap.add_argument("--base-url", default="http://localhost:8086")
    ap.add_argument("--model", default="cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4")
    ap.add_argument("--embedding-model", default="BAAI/bge-m3")
    ap.add_argument("-n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--prompt-file", help="Override the KO->EN system prompt.")
    ap.add_argument("--mode", default="hybrid",
                    choices=["hybrid", "dense", "sparse"],
                    help="Retrieval strategy against the index.")
    ap.add_argument("--direct", action="store_true",
                    help="Skip the LLM: embed the Korean term directly and search "
                         "the English index (tests the multilingual embedding's "
                         "cross-lingual lookup, no back-translation).")
    args = ap.parse_args()

    kr = args.kr or next(iter(sorted(Path("data/korean").rglob(
        "sct2_Description_Snapshot-ko_*.txt"))), None)
    if not kr:
        ap.error("could not find a KR ko Description file; pass --kr")
    system = (Path(args.prompt_file).read_text(encoding="utf-8")
              if args.prompt_file else SYSTEM_PROMPT)

    from agent.qdrant_store import BGEM3Embedder, QdrantHybridStore
    emb, store = BGEM3Embedder(), QdrantHybridStore()
    collection = si.index_collection_name(release_id(args.int), args.embedding_model)

    ko = _gold_korean(str(kr))
    indexed = {c.sctid: c for c in read_concept_terms(args.int, scope=set(ko))}
    random.seed(args.seed)
    sample = random.sample(sorted(set(ko) & set(indexed)), min(args.n, len(indexed)))

    bt_rec = real_rec = 0
    bt_scores: list[float] = []
    rows = []
    for sid in sample:
        if args.direct:
            query = ko[sid]                 # embed the Korean directly, no LLM
        else:
            en = translate_one(args.base_url, args.model, system, ko[sid],
                               {"temperature": 0, "max_tokens": 48})
            query = en.strip().splitlines()[0].strip().strip('".') if en else ""
        bt = si.retrieve_concepts(collection, [(sid, query)], limit=1,
                                  mode=args.mode, embedder=emb, store=store)[0]
        rl = si.retrieve_concepts(collection, [(sid, indexed[sid].fsn)], limit=1,
                                  mode=args.mode, embedder=emb, store=store)[0]
        bt_rec += bt["recovered"]
        real_rec += rl["recovered"]
        if bt["recovered"]:
            bt_scores.append(bt["top_score"])
        rows.append((sid, ko[sid], query, indexed[sid].fsn, bt["recovered"],
                     bt["top_score"], bt["top_fsn"]))

    n = len(sample)
    method = (f"DIRECT Korean embedding [{args.mode}]" if args.direct
              else f"back-translation [{args.mode}] ({args.model})")
    print(f"\n=== validation: {method}, n={n} ===")
    print(f"real-English recovery (ceiling, {args.mode}): {real_rec}/{n} = {100*real_rec/n:.1f}%")
    print(f"{'direct-KO' if args.direct else 'back-translation'} recovery:       "
          f"{bt_rec}/{n} = {100*bt_rec/n:.1f}%")
    if bt_scores:
        print(f"recovered score: mean {statistics.mean(bt_scores):.3f}")
    print("\nmisses (low-confidence — review these):")
    for sid, k, en, fsn, rec, sc, top in rows:
        if not rec:
            print(f"  {k!r} -> {en!r} -> {top!r}  [gold: {fsn}]")


if __name__ == "__main__":
    main()
