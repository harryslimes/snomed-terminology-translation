"""Build a Korean procedure eval set from the SNOMEDCT-KR RF2 release.

Output CSV columns: sctid, preferred_term, hierarchy, ko_reference

ko_reference is the Korean description marked PREFERRED for the Korean
language reference set, restricted to the Synonym description type
(i.e. the Korean equivalent of the English Preferred Term, not the FSN).

Concepts included: descendants of 71388002 |Procedure (procedure)|, taken
from the local serialised International Edition graph, that have at least
one preferred Korean synonym in the KR release.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

import networkx as nx

# Data lives in this repo's own data/ dir (repo root is two levels up from
# scripts/data_prep/). Override with DATA_DIR if the data lives elsewhere.
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

KR_DIR = (
    DATA_DIR / "korean"
    / "SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20251215T120000Z/Snapshot"
)
KR_DESC = KR_DIR / "Terminology/sct2_Description_Snapshot-ko_KR1000267_20251215.txt"
KR_LANG = KR_DIR / "Refset/Language/der2_cRefset_LanguageSnapshot-ko_KR1000267_20251215.txt"
GRAPH_PATH = DATA_DIR / "snomed_graph/full_concept_graph.gml"
OUT_CSV = DATA_DIR / "evals/korean/procedure_eval_set.csv"

PROCEDURE_ROOT = "71388002"
TYPE_SYNONYM = "900000000000013009"
ACCEPTABILITY_PREFERRED = "900000000000548007"
ISA = "Is a (attribute)"

FSN_TAG_RE = re.compile(r"\s*\(([^()]+)\)\s*$")


def parse_fsn(fsn: str) -> tuple[str, str]:
    """Return (preferred_term_without_tag, hierarchy_tag)."""
    m = FSN_TAG_RE.search(fsn)
    if not m:
        return fsn.strip(), ""
    return fsn[: m.start()].strip(), m.group(1).strip()


def load_procedure_descendants(graph_path: Path) -> dict[str, tuple[str, str]]:
    print(f"Loading SNOMED graph from {graph_path} ...")
    G = nx.read_gml(graph_path)
    print(f"  nodes={G.number_of_nodes():,}  edges={G.number_of_edges():,}")

    # Build a subgraph containing only Is-a edges so descendants are well-defined.
    isa_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get("type") == ISA]
    H = nx.DiGraph()
    H.add_edges_from(isa_edges)
    print(f"  is-a edges: {H.number_of_edges():,}")

    # In this graph, edge (child -> parent) means child IS-A parent.
    # Descendants of PROCEDURE_ROOT = all ancestors in H of the root node
    # (i.e. nodes that can reach the root by following is-a edges).
    descendants = nx.ancestors(H, PROCEDURE_ROOT)
    descendants.add(PROCEDURE_ROOT)
    print(f"  procedure descendants (incl. root): {len(descendants):,}")

    out: dict[str, tuple[str, str]] = {}
    for sctid in descendants:
        attrs = G.nodes[sctid]
        fsn = attrs.get("fsn", "")
        pt, hierarchy = parse_fsn(fsn)
        out[sctid] = (pt, hierarchy)
    return out


def load_kr_descriptions() -> dict[str, tuple[str, str, str]]:
    """Return {description_id: (concept_id, term, type_id)} for active ko descriptions."""
    print(f"Loading KR descriptions from {KR_DESC.name} ...")
    descs: dict[str, tuple[str, str, str]] = {}
    with KR_DESC.open(encoding="utf-8") as fh:
        next(fh)  # header
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            (
                desc_id,
                _eff,
                active,
                _module,
                concept_id,
                lang,
                type_id,
                term,
                _case,
            ) = parts
            if active != "1" or lang != "ko":
                continue
            descs[desc_id] = (concept_id, term, type_id)
    print(f"  active ko descriptions: {len(descs):,}")
    return descs


def load_kr_preferred_desc_ids() -> set[str]:
    """Description IDs marked PREFERRED in the active ko language refset."""
    print(f"Loading KR ko language refset from {KR_LANG.name} ...")
    preferred: set[str] = set()
    with KR_LANG.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            (
                _id,
                _eff,
                active,
                _module,
                _refset,
                referenced_component_id,
                acceptability_id,
            ) = parts
            if active != "1":
                continue
            if acceptability_id == ACCEPTABILITY_PREFERRED:
                preferred.add(referenced_component_id)
    print(f"  preferred ko description rows: {len(preferred):,}")
    return preferred


def main() -> None:
    procedures = load_procedure_descendants(GRAPH_PATH)
    descs = load_kr_descriptions()
    preferred_desc_ids = load_kr_preferred_desc_ids()

    # For each concept, find its preferred Korean SYNONYM (= ko PT-equivalent).
    concept_to_ko_pt: dict[str, str] = {}
    concept_has_any_ko: set[str] = set()
    for desc_id, (concept_id, term, type_id) in descs.items():
        concept_has_any_ko.add(concept_id)
        if type_id != TYPE_SYNONYM:
            continue
        if desc_id not in preferred_desc_ids:
            continue
        # Take the first preferred we encounter; in well-formed RF2 there
        # should be exactly one preferred synonym per concept per language.
        concept_to_ko_pt.setdefault(concept_id, term)

    procs_with_pref_ko = [s for s in procedures if s in concept_to_ko_pt]
    procs_with_any_ko = [s for s in procedures if s in concept_has_any_ko]

    print()
    print("=" * 60)
    print(f"Total procedure concepts (International):       {len(procedures):,}")
    print(f"Procedure concepts with ANY active ko desc:     {len(procs_with_any_ko):,}")
    print(f"Procedure concepts with PREFERRED ko synonym:   {len(procs_with_pref_ko):,}")
    print(
        f"Coverage (preferred / total):                   "
        f"{100 * len(procs_with_pref_ko) / max(len(procedures), 1):.2f}%"
    )
    print("=" * 60)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sctid", "preferred_term", "hierarchy", "ko_reference"])
        for sctid in sorted(procs_with_pref_ko, key=int):
            pt, hierarchy = procedures[sctid]
            writer.writerow([sctid, pt, hierarchy, concept_to_ko_pt[sctid]])

    print(f"\nWrote {len(procs_with_pref_ko):,} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
