#!/usr/bin/env python3
"""Build a per-SCTID attributes file for an eval set.

For each sctid in the eval CSV, extracts:
  - Body-site attributes (procedure_site_direct, procedure_site_indirect,
    procedure_site, finding_site)
  - Method attribute
  - Using substance / access (optional)

Output JSON: {sctid: {method_id, method_fsn, procedure_site_direct_id, ...}}

Generalises build_imaging_ablation_inputs.py — operates on any eval CSV.
Used by the synthetic-long-tail runner to compute neighbour sets
(concepts sharing Method or Procedure site).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

ROOT_DIR = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT_DIR / "snomed_graph" / "full_concept_graph.gml"

IS_A_ID = 116680003
METHOD_ID = 260686004
SITE_ATTR_IDS = {
    405813007: "procedure_site_direct",
    405814001: "procedure_site_indirect",
    363704007: "procedure_site",
    363698007: "finding_site",
}
USING_SUBSTANCE_ID = 424361007
ACCESS_ID = 260507000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_eval_attrs")


def collect_attributes(g: nx.MultiDiGraph, sctids: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for u, v, data in g.edges(data=True):
        if u not in sctids:
            continue
        tid = data.get("type_id")
        target_fsn = g.nodes[v].get("fsn", "")
        entry = out.setdefault(u, {})
        if tid in SITE_ATTR_IDS:
            name = SITE_ATTR_IDS[tid]
            if f"{name}_id" not in entry:
                entry[f"{name}_id"] = v
                entry[f"{name}_fsn"] = target_fsn
        elif tid == METHOD_ID and "method_id" not in entry:
            entry["method_id"] = v
            entry["method_fsn"] = target_fsn
        elif tid == USING_SUBSTANCE_ID and "using_substance_id" not in entry:
            entry["using_substance_id"] = v
            entry["using_substance_fsn"] = target_fsn
        elif tid == ACCESS_ID and "access_id" not in entry:
            entry["access_id"] = v
            entry["access_fsn"] = target_fsn
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", type=Path, required=True,
                        help="CSV with a 'sctid' column.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output JSON path.")
    args = parser.parse_args()

    with args.eval_set.open(encoding="utf-8") as f:
        sctids = {row["sctid"] for row in csv.DictReader(f)}
    log.info("Eval set: %d sctids", len(sctids))

    log.info("Loading graph (~30s)...")
    g = nx.read_gml(GRAPH_PATH, label="label")
    log.info("  %d nodes, %d edges", g.number_of_nodes(), g.number_of_edges())

    log.info("Collecting attributes...")
    attrs = collect_attributes(g, sctids)
    log.info("  %d concepts with any attribute", len(attrs))

    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(attrs, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        rel = out.relative_to(ROOT_DIR)
    except ValueError:
        rel = out
    log.info("Wrote %s", rel)


if __name__ == "__main__":
    main()
