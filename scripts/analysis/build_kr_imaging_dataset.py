#!/usr/bin/env python3
"""Build a consolidated dataset of KR-translated procedure concepts under a
given root. Phase 1 ran over 363679005 |Imaging (procedure)| (774 concepts);
Phase 2 runs over 71388002 |Procedure| (~3,693 concepts).

For each concept that is both a descendant of the root AND has an active
Korean preferred synonym in the KR release, write a row with its English
FSN, Korean preferred term, Korean acceptable synonyms, method attribute,
and body-site attributes.

Output: data/analysis/<scope>_inconsistencies/kr_<scope>_dataset.csv

This is the input to analyze_kr_imaging_inconsistencies.py.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

ROOT_DIR = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT_DIR / "snomed_graph" / "full_concept_graph.gml"
KR_ROOT = ROOT_DIR / "data" / "korean" / "SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20251215T120000Z" / "Snapshot"
KO_DESC = KR_ROOT / "Terminology" / "sct2_Description_Snapshot-ko_KR1000267_20251215.txt"
KO_LANGREFSET = KR_ROOT / "Refset" / "Language" / "der2_cRefset_LanguageSnapshot-ko_KR1000267_20251215.txt"

# Scope → (root sctid, human label)
SCOPES: dict[str, tuple[str, str]] = {
    "imaging": ("363679005", "Imaging (procedure)"),
    "procedure": ("71388002", "Procedure"),
    "body_structure": ("123037004", "Body structure"),
}
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

SYNONYM_TYPE_ID = "900000000000013009"
KR_LANG_REFSET_ID = "21000267104"
PREFERRED = "900000000000548007"
ACCEPTABLE = "900000000000549004"

SEMANTIC_TAG_SUFFIX = {
    " (body structure)", " (procedure)", " (finding)", " (substance)",
    " (qualifier value)", " (regime/therapy)", " (morphologic abnormality)",
    " (organism)", " (product)", " (physical object)", " (observable entity)",
    " (disorder)", " (event)", " (specimen)", " (attribute)",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kr_dataset")


def strip_tag(fsn: str) -> str:
    for s in SEMANTIC_TAG_SUFFIX:
        if fsn.endswith(s):
            return fsn[: -len(s)].strip()
    return fsn.strip()


def load_lang_refset() -> tuple[set[str], set[str]]:
    pref, acc = set(), set()
    with KO_LANGREFSET.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["active"] != "1" or row["refsetId"] != KR_LANG_REFSET_ID:
                continue
            did = row["referencedComponentId"]
            a = row["acceptabilityId"]
            if a == PREFERRED:
                pref.add(did)
            elif a == ACCEPTABLE:
                acc.add(did)
    return pref, acc


def load_ko_descriptions(pref: set[str], acc: set[str]) -> dict[str, dict]:
    preferred: dict[str, str] = {}
    acceptables: dict[str, list[str]] = defaultdict(list)
    with KO_DESC.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["active"] != "1" or row["typeId"] != SYNONYM_TYPE_ID:
                continue
            did = row["id"]
            cid = row["conceptId"]
            term = row["term"].strip()
            if not term:
                continue
            if did in pref and cid not in preferred:
                preferred[cid] = term
            elif did in acc:
                acceptables[cid].append(term)
    return {cid: {"ko_preferred": preferred[cid], "ko_acceptables": acceptables.get(cid, [])}
            for cid in preferred}


def descendants_of(g: nx.MultiDiGraph, root: str) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for u, v, d in g.edges(data=True):
        if d.get("type_id") == IS_A_ID:
            children[v].append(u)
    seen = {root}
    stack = [root]
    while stack:
        n = stack.pop()
        for c in children.get(n, []):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def collect_attributes(g: nx.MultiDiGraph, sctids: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for u, v, d in g.edges(data=True):
        if u not in sctids:
            continue
        tid = d.get("type_id")
        target_fsn = g.nodes[v].get("fsn", "")
        e = out.setdefault(u, {})
        if tid in SITE_ATTR_IDS:
            name = SITE_ATTR_IDS[tid]
            if f"{name}_id" not in e:
                e[f"{name}_id"] = v
                e[f"{name}_fsn"] = target_fsn
        elif tid == METHOD_ID and "method_id" not in e:
            e["method_id"] = v
            e["method_fsn"] = target_fsn
        elif tid == USING_SUBSTANCE_ID and "using_substance_id" not in e:
            e["using_substance_id"] = v
            e["using_substance_fsn"] = target_fsn
        elif tid == ACCESS_ID and "access_id" not in e:
            e["access_id"] = v
            e["access_fsn"] = target_fsn
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=list(SCOPES), default="imaging",
                        help="Named hierarchy scope. Determines root sctid and output paths.")
    args = parser.parse_args()

    root_sctid, root_label = SCOPES[args.scope]
    out_path = ROOT_DIR / "data" / "analysis" / f"{args.scope}_inconsistencies" / f"kr_{args.scope}_dataset.csv"

    log.info("Scope: %s (root %s '%s')", args.scope, root_sctid, root_label)
    log.info("Loading KR language refset...")
    pref, acc = load_lang_refset()
    log.info("  preferred desc ids: %d | acceptable: %d", len(pref), len(acc))

    log.info("Loading KR Korean descriptions...")
    ko = load_ko_descriptions(pref, acc)
    log.info("  concepts with preferred KR Korean: %d", len(ko))

    log.info("Loading SNOMED graph...")
    g = nx.read_gml(GRAPH_PATH, label="label")
    log.info("  nodes: %d, edges: %d", g.number_of_nodes(), g.number_of_edges())

    log.info("Enumerating descendants of %s...", root_sctid)
    in_scope = descendants_of(g, root_sctid)
    log.info("  %d %s concepts in International Edition", len(in_scope), args.scope)

    kr_in_scope = {cid for cid in in_scope if cid in ko}
    log.info("  %d of those have a KR preferred Korean term", len(kr_in_scope))

    log.info("Collecting attributes for the KR-%s subset...", args.scope)
    attrs = collect_attributes(g, kr_in_scope)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sctid", "en_fsn", "en_term", "ko_preferred", "ko_acceptables",
                "method_id", "method_fsn",
                "site_direct_id", "site_direct_fsn",
                "site_indirect_id", "site_indirect_fsn",
                "site_generic_id", "site_generic_fsn",
                "finding_site_id", "finding_site_fsn",
                "using_substance_id", "using_substance_fsn",
                "access_id", "access_fsn",
            ],
        )
        writer.writeheader()
        for cid in sorted(kr_in_scope):
            fsn = g.nodes[cid].get("fsn", "")
            a = attrs.get(cid, {})
            writer.writerow({
                "sctid": cid,
                "en_fsn": fsn,
                "en_term": strip_tag(fsn),
                "ko_preferred": ko[cid]["ko_preferred"],
                "ko_acceptables": "; ".join(ko[cid]["ko_acceptables"]),
                "method_id": a.get("method_id", ""),
                "method_fsn": a.get("method_fsn", ""),
                "site_direct_id": a.get("procedure_site_direct_id", ""),
                "site_direct_fsn": a.get("procedure_site_direct_fsn", ""),
                "site_indirect_id": a.get("procedure_site_indirect_id", ""),
                "site_indirect_fsn": a.get("procedure_site_indirect_fsn", ""),
                "site_generic_id": a.get("procedure_site_id", ""),
                "site_generic_fsn": a.get("procedure_site_fsn", ""),
                "finding_site_id": a.get("finding_site_id", ""),
                "finding_site_fsn": a.get("finding_site_fsn", ""),
                "using_substance_id": a.get("using_substance_id", ""),
                "using_substance_fsn": a.get("using_substance_fsn", ""),
                "access_id": a.get("access_id", ""),
                "access_fsn": a.get("access_fsn", ""),
            })

    log.info("Wrote %s (%d rows)", out_path.relative_to(ROOT_DIR), len(kr_in_scope))


if __name__ == "__main__":
    main()
