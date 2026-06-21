#!/usr/bin/env python
"""
Build a stratified evaluation sample from the SNOMED EE national extension.

Concepts are split into value tiers based on translation complexity:
  - High:   disorder, procedure, morphologic abnormality, body structure, finding
  - Medium: substance, physical object, observable entity
  - Low:    organism, person, specimen, qualifier value, regime/therapy, event, ...

Uses the local SNOMED graph (GML) for fast bulk resolution instead of HTTP calls.

Usage:
    python scripts/build_eval_sample.py
    python scripts/build_eval_sample.py --high 350 --medium 100 --low 50
    python scripts/build_eval_sample.py --rebuild-splits  # also rebuild rule optimization splits
"""
import argparse
import csv
import json
import logging
import random
import re
import sys
from pathlib import Path

import networkx as nx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_eval_sample")

EE_EXTENSION_PATH = Path("data/SNOMED_EE_national_extension/xsct2_Description_Snapshot-et_EE1000181_20250530.txt")
SNOMED_GRAPH_PATH = Path("data/snomed_graph/full_concept_graph.gml")
EVAL_SAMPLE_PATH = Path("data/evals/sample/500_eval_concepts.csv")
SPLITS_DIR = Path("data/evals/splits")

HIGH_VALUE = ["disorder", "procedure", "morphologic abnormality", "body structure", "finding"]
MEDIUM_VALUE = ["substance", "physical object", "observable entity"]
LOW_VALUE = ["organism", "person", "specimen", "qualifier value", "regime/therapy", "event"]

SEED = 42


def load_ee_extension() -> dict[str, dict]:
    """Load all active Estonian descriptions, grouped by concept ID."""
    with EE_EXTENSION_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = [r for r in reader if r["active"] == "1"]

    concepts = {}
    for r in rows:
        cid = r["conceptId"]
        if cid not in concepts:
            concepts[cid] = {"sctid": cid, "terms": []}
        concepts[cid]["terms"].append(r["term"])
    return concepts


def load_snomed_graph() -> dict[str, dict]:
    """Load the SNOMED graph and build a SCTID → info lookup.

    Returns a dict keyed by SCTID string with:
      preferred_term, hierarchy, synonyms, parent_concepts
    """
    logger.info("Loading SNOMED graph from %s...", SNOMED_GRAPH_PATH)
    G = nx.read_gml(str(SNOMED_GRAPH_PATH))
    logger.info("Graph loaded: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())

    lookup = {}
    for sctid, data in G.nodes(data=True):
        fsn = data.get("fsn", "")
        m = re.search(r"\(([^)]+)\)\s*$", fsn)
        hierarchy = m.group(1) if m else ""
        preferred_term = re.sub(r"\s*\([^)]+\)\s*$", "", fsn)

        synonyms_raw = data.get("synonyms", [])
        if isinstance(synonyms_raw, str):
            synonyms = [synonyms_raw]
        else:
            synonyms = list(synonyms_raw)
        synonyms = [s for s in synonyms if s != "_networkx_list_start"]

        # Parents are successors in this graph (edges go child → parent)
        parent_terms = []
        for parent_id in G.successors(sctid):
            p_fsn = G.nodes[parent_id].get("fsn", "")
            p_term = re.sub(r"\s*\([^)]+\)\s*$", "", p_fsn)
            if p_term:
                parent_terms.append(p_term)

        lookup[sctid] = {
            "preferred_term": preferred_term,
            "hierarchy": hierarchy,
            "synonyms": synonyms,
            "parent_concepts": parent_terms[:10],
        }

    logger.info("Built lookup for %d concepts", len(lookup))
    return lookup


def resolve_all_concepts(ee_concepts: dict[str, dict], graph_lookup: dict[str, dict]) -> list[dict]:
    """Join EE extension concepts with SNOMED graph info."""
    resolved = []
    missing = 0
    for cid, concept in ee_concepts.items():
        info = graph_lookup.get(cid)
        if not info or not info["preferred_term"] or not info["hierarchy"]:
            missing += 1
            continue
        resolved.append({
            "sctid": cid,
            "preferred_term": info["preferred_term"],
            "hierarchy": info["hierarchy"],
            "ee_all": concept["terms"],
            "ee_reference": concept["terms"][0],
            "synonyms": info["synonyms"],
            "parent_concepts": info["parent_concepts"],
        })

    logger.info("Resolved %d concepts (%d not found in graph)", len(resolved), missing)
    return resolved


def build_eval_sample(
    resolved: list[dict],
    high_total: int = 350,
    medium_total: int = 100,
    low_total: int = 50,
    seed: int = SEED,
) -> list[dict]:
    """Build stratified eval sample from resolved concepts."""
    rng = random.Random(seed)

    # Group by hierarchy
    by_hierarchy = {}
    for item in resolved:
        h = item["hierarchy"]
        by_hierarchy.setdefault(h, []).append(item)

    logger.info("Available concepts by hierarchy:")
    for h in sorted(by_hierarchy, key=lambda x: -len(by_hierarchy[x])):
        logger.info("  %s: %d", h, len(by_hierarchy[h]))

    sample = []

    def sample_tier(hierarchies, total, tier_name):
        active = [h for h in hierarchies if h in by_hierarchy and len(by_hierarchy[h]) > 0]
        if not active:
            logger.warning("No concepts found for %s tier", tier_name)
            return
        per_hierarchy = total // len(active)
        remainder = total % len(active)
        for i, h in enumerate(active):
            n = per_hierarchy + (1 if i < remainder else 0)
            available = by_hierarchy[h]
            n = min(n, len(available))
            picked = rng.sample(available, n)
            sample.extend(picked)
            logger.info("  %s [%s]: %d/%d available", h, tier_name, n, len(available))

    logger.info("\nSampling high-value hierarchies (%d total):", high_total)
    sample_tier(HIGH_VALUE, high_total, "high")

    logger.info("\nSampling medium-value hierarchies (%d total):", medium_total)
    sample_tier(MEDIUM_VALUE, medium_total, "medium")

    logger.info("\nSampling low-value hierarchies (%d total):", low_total)
    sample_tier(LOW_VALUE, low_total, "low")

    rng.shuffle(sample)
    logger.info("\nTotal eval sample: %d concepts", len(sample))
    return sample


def build_rule_splits(
    resolved: list[dict],
    hierarchies: list[str],
    eval_sctids: set[str],
    train_ratio: float = 0.8,
    max_total: int = 300,
    seed: int = SEED,
):
    """Build train/holdout splits for rule optimization, excluding eval sample concepts.

    Samples from ALL available concepts for each hierarchy, after removing any
    concept that appears in the eval sample.
    """
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    by_hierarchy = {}
    for item in resolved:
        if item["sctid"] in eval_sctids:
            continue
        by_hierarchy.setdefault(item["hierarchy"], []).append(item)

    excluded = sum(1 for item in resolved if item["sctid"] in eval_sctids)
    logger.info("Excluded %d eval sample concepts from rule optimization pool", excluded)

    for h in hierarchies:
        split_path = SPLITS_DIR / f"{h.replace(' ', '_').replace('/', '_')}_split.json"
        available = by_hierarchy.get(h, [])
        if not available:
            logger.warning("No concepts for '%s', skipping split", h)
            continue

        if len(available) > max_total:
            items = rng.sample(available, max_total)
        else:
            items = list(available)

        rng.shuffle(items)
        split_idx = int(len(items) * train_ratio)
        train, holdout = items[:split_idx], items[split_idx:]

        with split_path.open("w", encoding="utf-8") as f:
            json.dump({"train": train, "holdout": holdout}, f, ensure_ascii=False, indent=2)
        logger.info("Split '%s': %d train, %d holdout (from %d available) -> %s",
                     h, len(train), len(holdout), len(available), split_path)


def write_eval_csv(sample: list[dict], path: Path):
    """Write eval sample to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sctid", "preferred_term", "hierarchy", "ee_reference", "ee_all"])
        for item in sample:
            writer.writerow([
                item["sctid"],
                item["preferred_term"],
                item["hierarchy"],
                item["ee_reference"],
                "|".join(item["ee_all"]),
            ])
    logger.info("Wrote %d concepts to %s", len(sample), path)


def main():
    parser = argparse.ArgumentParser(description="Build stratified SNOMED eval sample")
    parser.add_argument("--high", type=int, default=350, help="Total concepts from high-value hierarchies")
    parser.add_argument("--medium", type=int, default=100, help="Total concepts from medium-value hierarchies")
    parser.add_argument("--low", type=int, default=50, help="Total concepts from low-value hierarchies")
    parser.add_argument("--output", type=str, default=str(EVAL_SAMPLE_PATH), help="Output CSV path")
    parser.add_argument("--rebuild-splits", action="store_true",
                        help="Also rebuild train/holdout splits for rule optimization")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    logger.info("Loading EE extension...")
    concepts = load_ee_extension()
    logger.info("Loaded %d unique concepts", len(concepts))

    graph_lookup = load_snomed_graph()

    logger.info("Joining EE extension with graph data...")
    resolved = resolve_all_concepts(concepts, graph_lookup)

    # Build eval sample
    sample = build_eval_sample(
        resolved,
        high_total=args.high,
        medium_total=args.medium,
        low_total=args.low,
        seed=args.seed,
    )
    write_eval_csv(sample, Path(args.output))

    # Optionally rebuild rule optimization splits (excluding eval concepts)
    if args.rebuild_splits:
        eval_sctids = {item["sctid"] for item in sample}
        all_hierarchies = HIGH_VALUE + MEDIUM_VALUE + LOW_VALUE
        logger.info("\nRebuilding rule optimization splits (excluding %d eval concepts)...", len(eval_sctids))
        build_rule_splits(resolved, all_hierarchies, eval_sctids=eval_sctids, seed=args.seed)


if __name__ == "__main__":
    main()
