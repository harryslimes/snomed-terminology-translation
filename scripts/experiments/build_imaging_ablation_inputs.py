#!/usr/bin/env python3
"""Build the inputs for the imaging-resources ablation experiment.

Outputs under data/evals/korean/imaging_ablation/:

  imaging_eval_set.csv       Rows of procedure_eval_set.csv whose sctid is a
                             descendant of 363679005 |Imaging (procedure)|.
  imaging_attributes.json    {sctid: {procedure_site_id, procedure_site_fsn,
                                       finding_site_id, finding_site_fsn}}
                             Attribute targets for each imaging sctid, used at
                             prompt-build time to look up the body-site English
                             FSN in the KAA anatomy dictionary.

Reads the full SNOMED concept graph from snomed_graph/full_concept_graph.gml,
which encodes every IS-A and attribute relationship in the International
Edition.
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

ROOT_DIR = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT_DIR / "snomed_graph" / "full_concept_graph.gml"
EVAL_PATH = ROOT_DIR / "data" / "evals" / "korean" / "procedure_eval_set.csv"
OUT_DIR = ROOT_DIR / "data" / "evals" / "korean" / "imaging_ablation"

IMAGING_ROOT_SCTID = "363679005"
IS_A_ID = 116680003
# Body-site attribute IDs. Imaging procedures predominantly use
# "Procedure site - Direct" (405813007); the generic "Procedure site"
# (363704007) is rare in the imaging hierarchy.
SITE_ATTR_IDS = {
    405813007: "procedure_site_direct",
    405814001: "procedure_site_indirect",
    363704007: "procedure_site",
    363698007: "finding_site",
}
METHOD_ATTR_ID = 260686004

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("imaging_inputs")


def load_graph() -> nx.MultiDiGraph:
    log.info("Loading graph from %s (this takes ~30s)...", GRAPH_PATH.relative_to(ROOT_DIR))
    g = nx.read_gml(GRAPH_PATH, label="label")
    log.info("Loaded: %d nodes, %d edges", g.number_of_nodes(), g.number_of_edges())
    return g


def descendants_of(g: nx.MultiDiGraph, root: str) -> set[str]:
    """Find all SCTIDs whose IS-A ancestor chain reaches `root` (inclusive)."""
    if root not in g:
        sys.exit(f"Root sctid {root} not found in graph")

    # IS-A edges point child -> parent. Reverse to find descendants.
    children = defaultdict(list)
    for u, v, data in g.edges(data=True):
        if data.get("type_id") == IS_A_ID:
            children[v].append(u)

    visited = {root}
    stack = [root]
    while stack:
        node = stack.pop()
        for child in children.get(node, []):
            if child not in visited:
                visited.add(child)
                stack.append(child)
    return visited


def attribute_targets(g: nx.MultiDiGraph, sctids: set[str]) -> dict[str, dict]:
    """For each sctid, extract body-site and method attribute targets.

    Body-site attributes produce one entry per attribute kind (direct /
    indirect / generic site / finding site). If a concept has multiple
    targets for the same attribute, keep the first encountered.
    """
    result: dict[str, dict] = {}
    for u, v, data in g.edges(data=True):
        if u not in sctids:
            continue
        tid = data.get("type_id")
        target_fsn = g.nodes[v].get("fsn", "")
        entry = result.setdefault(u, {})
        if tid in SITE_ATTR_IDS:
            name = SITE_ATTR_IDS[tid]
            if f"{name}_id" not in entry:
                entry[f"{name}_id"] = v
                entry[f"{name}_fsn"] = target_fsn
        elif tid == METHOD_ATTR_ID and "method_id" not in entry:
            entry["method_id"] = v
            entry["method_fsn"] = target_fsn
    return result


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    g = load_graph()

    log.info("Computing descendants of %s (Imaging procedure)...", IMAGING_ROOT_SCTID)
    imaging_ids = descendants_of(g, IMAGING_ROOT_SCTID)
    log.info("  %d imaging descendants (incl. self)", len(imaging_ids))

    # Filter the existing eval set to imaging concepts
    log.info("Reading eval set %s...", EVAL_PATH.relative_to(ROOT_DIR))
    eval_rows = list(csv.DictReader(EVAL_PATH.open(encoding="utf-8")))
    imaging_rows = [r for r in eval_rows if r["sctid"] in imaging_ids]
    log.info("  eval total: %d, imaging subset: %d", len(eval_rows), len(imaging_rows))

    out_eval = OUT_DIR / "imaging_eval_set.csv"
    with out_eval.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(eval_rows[0].keys()))
        writer.writeheader()
        writer.writerows(imaging_rows)
    log.info("Wrote %s (%d rows)", out_eval.relative_to(ROOT_DIR), len(imaging_rows))

    # Attribute targets for the imaging subset only (fast)
    log.info("Collecting body-site attributes for imaging eval subset...")
    imaging_eval_ids = {r["sctid"] for r in imaging_rows}
    attrs = attribute_targets(g, imaging_eval_ids)
    site_keys = ("procedure_site_direct_id", "procedure_site_indirect_id",
                 "procedure_site_id", "finding_site_id")
    with_any_site = sum(1 for v in attrs.values() if any(k in v for k in site_keys))
    log.info(
        "  with direct site: %d | indirect site: %d | generic site: %d | "
        "finding site: %d | method: %d | any site: %d",
        sum(1 for v in attrs.values() if "procedure_site_direct_id" in v),
        sum(1 for v in attrs.values() if "procedure_site_indirect_id" in v),
        sum(1 for v in attrs.values() if "procedure_site_id" in v),
        sum(1 for v in attrs.values() if "finding_site_id" in v),
        sum(1 for v in attrs.values() if "method_id" in v),
        with_any_site,
    )

    out_attrs = OUT_DIR / "imaging_attributes.json"
    out_attrs.write_text(json.dumps(attrs, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Wrote %s", out_attrs.relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
