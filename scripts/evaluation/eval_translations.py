#!/usr/bin/env python
"""
Evaluate SNOMED CT translations against reference using a hybrid metric:
  - chrF (character n-gram F-score) — surface/style similarity
  - BGE-M3 cosine similarity — semantic similarity
  - Exact match — strict match

Composite score: 0.5 * chrF_norm + 0.3 * cosine + 0.2 * exact

Usage:
    python scripts/eval_translations.py \
        --translations data/evals/sample/500_translations_sonnet.csv \
        --reference data/evals/sample/500_eval_concepts.csv

    # Compare multiple translation files:
    python scripts/eval_translations.py \
        --translations file1.csv file2.csv file3.csv \
        --reference data/evals/sample/500_eval_concepts.csv
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import sacrebleu
from FlagEmbedding import BGEM3FlagModel


def load_reference(path: Path) -> dict:
    """Load reference translations. Returns {sctid: {hierarchy, ee_all: [list], ee_preferred}}."""
    ref = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            sctid = row["sctid"]
            all_trans = [t.strip() for t in row["ee_all"].split("|") if t.strip()]
            ref[sctid] = {
                "hierarchy": row.get("hierarchy", ""),
                "preferred_term": row.get("preferred_term", ""),
                "ee_reference": row.get("ee_reference", all_trans[0] if all_trans else ""),
                "ee_all": all_trans,
            }
    return ref


def load_translations(path: Path) -> dict:
    """Load candidate translations. Returns {sctid: translation_string}."""
    trans = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            trans[row["sctid"]] = row["translation"].strip()
    return trans


def compute_chrf(candidate: str, references: list[str]) -> float:
    """Compute best chrF score against any of the accepted references."""
    best = 0.0
    for ref in references:
        score = sacrebleu.sentence_chrf(candidate, [ref]).score
        best = max(best, score)
    return best  # 0-100 scale


def compute_exact(candidate: str, references: list[str]) -> float:
    """1.0 if candidate matches any reference (case-insensitive), else 0.0."""
    cl = candidate.lower()
    return 1.0 if any(cl == r.lower() for r in references) else 0.0


def compute_bgem3_scores(
    model: BGEM3FlagModel,
    candidates: list[str],
    reference_groups: list[list[str]],
    batch_size: int = 256,
) -> list[float]:
    """Compute best BGE-M3 cosine similarity for each candidate against its references."""
    # Build flat list of all strings to encode
    all_strings = list(candidates)
    ref_offsets = []  # (start_idx, count) for each candidate's references
    for refs in reference_groups:
        ref_offsets.append((len(all_strings), len(refs)))
        all_strings.extend(refs)

    # Encode everything in one batch
    embeddings = model.encode(
        all_strings,
        batch_size=batch_size,
        max_length=512,
    )["dense_vecs"]

    # Compute per-candidate best cosine similarity
    scores = []
    for i, (offset, count) in enumerate(ref_offsets):
        cand_vec = embeddings[i]
        best_sim = 0.0
        for j in range(offset, offset + count):
            ref_vec = embeddings[j]
            sim = float(np.dot(cand_vec, ref_vec) / (np.linalg.norm(cand_vec) * np.linalg.norm(ref_vec) + 1e-9))
            best_sim = max(best_sim, sim)
        scores.append(best_sim)

    return scores


def evaluate(
    translations: dict,
    reference: dict,
    model: BGEM3FlagModel,
) -> list[dict]:
    """Evaluate all translations. Returns list of per-term score dicts."""
    # Align candidates with references
    sctids = [s for s in reference if s in translations]
    candidates = [translations[s] for s in sctids]
    ref_groups = [reference[s]["ee_all"] for s in sctids]

    # Batch compute BGE-M3 cosine similarities
    print(f"  Computing BGE-M3 embeddings for {len(candidates)} candidates + references...")
    cosine_scores = compute_bgem3_scores(model, candidates, ref_groups)

    results = []
    for i, sctid in enumerate(sctids):
        cand = candidates[i]
        refs = ref_groups[i]
        ref_info = reference[sctid]

        chrf = compute_chrf(cand, refs)
        exact = compute_exact(cand, refs)
        cosine = cosine_scores[i]

        # Composite: chrF is 0-100, normalise to 0-1
        chrf_norm = chrf / 100.0
        composite = 0.5 * chrf_norm + 0.3 * cosine + 0.2 * exact

        results.append({
            "sctid": sctid,
            "preferred_term": ref_info["preferred_term"],
            "hierarchy": ref_info["hierarchy"],
            "reference": ref_info["ee_reference"],
            "candidate": cand,
            "chrf": chrf,
            "cosine": cosine,
            "exact": exact,
            "composite": composite,
        })

    return results


def print_summary(results: list[dict], label: str):
    """Print summary statistics overall and by hierarchy."""
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")

    errors = [r for r in results if r["candidate"].startswith("ERROR")]
    valid = [r for r in results if not r["candidate"].startswith("ERROR")]

    if errors:
        print(f"  Errors: {len(errors)}")

    if not valid:
        print("  No valid translations.")
        return

    avg_chrf = np.mean([r["chrf"] for r in valid])
    avg_cosine = np.mean([r["cosine"] for r in valid])
    avg_exact = np.mean([r["exact"] for r in valid])
    avg_composite = np.mean([r["composite"] for r in valid])

    print(f"\n  Overall ({len(valid)} terms):")
    print(f"    chrF:      {avg_chrf:6.1f}")
    print(f"    Cosine:    {avg_cosine:6.3f}")
    print(f"    Exact:     {avg_exact * 100:5.1f}%")
    print(f"    Composite: {avg_composite:6.3f}")

    # By hierarchy
    hierarchies = sorted(set(r["hierarchy"] for r in valid))
    if len(hierarchies) > 1:
        print(f"\n  {'Hierarchy':<35s} {'chrF':>6s} {'Cosine':>7s} {'Exact':>6s} {'Comp':>6s} {'N':>4s}")
        print(f"  {'-' * 35} {'-' * 6} {'-' * 7} {'-' * 6} {'-' * 6} {'-' * 4}")
        for h in hierarchies:
            hr = [r for r in valid if r["hierarchy"] == h]
            print(
                f"  {h:<35s} "
                f"{np.mean([r['chrf'] for r in hr]):6.1f} "
                f"{np.mean([r['cosine'] for r in hr]):7.3f} "
                f"{np.mean([r['exact'] for r in hr]) * 100:5.1f}% "
                f"{np.mean([r['composite'] for r in hr]):6.3f} "
                f"{len(hr):4d}"
            )

    # Worst 10
    print(f"\n  Bottom 10 (lowest composite):")
    worst = sorted(valid, key=lambda r: r["composite"])[:10]
    for r in worst:
        print(f"    {r['composite']:.3f}  {r['preferred_term'][:40]:<40s}  {r['candidate'][:30]:<30s}  ref: {r['reference'][:30]}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate SNOMED CT translations with hybrid metric")
    parser.add_argument(
        "--translations", type=Path, nargs="+", required=True,
        help="One or more translation CSV files to evaluate",
    )
    parser.add_argument(
        "--reference", type=Path,
        default=Path("data/evals/sample/500_eval_concepts.csv"),
    )
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional: write detailed per-term scores to CSV",
    )
    args = parser.parse_args()

    if not args.reference.exists():
        raise SystemExit(f"Reference not found: {args.reference}")

    print("Loading BGE-M3 model (CPU)...")
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, device="cpu")

    reference = load_reference(args.reference)
    print(f"Loaded {len(reference)} reference terms")

    all_results = {}
    for tpath in args.translations:
        if not tpath.exists():
            print(f"WARNING: {tpath} not found, skipping")
            continue

        translations = load_translations(tpath)
        overlap = len(set(translations) & set(reference))
        print(f"\nEvaluating {tpath.name} ({overlap} terms matched)")

        results = evaluate(translations, reference, model)
        all_results[tpath.name] = results
        print_summary(results, tpath.name)

    # Comparison table if multiple files
    if len(all_results) > 1:
        print(f"\n{'=' * 70}")
        print(f"  Comparison")
        print(f"{'=' * 70}")
        print(f"  {'File':<45s} {'chrF':>6s} {'Cosine':>7s} {'Exact':>6s} {'Comp':>6s}")
        print(f"  {'-' * 45} {'-' * 6} {'-' * 7} {'-' * 6} {'-' * 6}")
        for name, results in all_results.items():
            valid = [r for r in results if not r["candidate"].startswith("ERROR")]
            if valid:
                print(
                    f"  {name:<45s} "
                    f"{np.mean([r['chrf'] for r in valid]):6.1f} "
                    f"{np.mean([r['cosine'] for r in valid]):7.3f} "
                    f"{np.mean([r['exact'] for r in valid]) * 100:5.1f}% "
                    f"{np.mean([r['composite'] for r in valid]):6.3f}"
                )

    # Optional detailed output
    if args.output and all_results:
        # Write results from last file (or first if only one)
        last_results = list(all_results.values())[-1]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "sctid", "preferred_term", "hierarchy", "reference", "candidate",
                "chrf", "cosine", "exact", "composite",
            ])
            writer.writeheader()
            writer.writerows(last_results)
        print(f"\nDetailed scores written to {args.output}")


if __name__ == "__main__":
    main()
