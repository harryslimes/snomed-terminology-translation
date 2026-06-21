#!/usr/bin/env python3
"""Build a KR-native body-site dictionary from the KR SNOMED release.

For every body-structure concept (descendant of 123037004 |Body structure|)
that has an active Korean preferred synonym in the KR release, produce a
TSV row with the same schema as the KAA termbase so it can be used as a
drop-in replacement via `translate_imaging_ablation.py --use-kaa --kaa <path>`.

The output file:
  data/korean/dictionaries/kr_body_sites.tsv
Columns: en, ko_preferred, ko_synonyms, la

Rationale: see docs/imaging_resources_ablation_findings_2026-04-20.md. The
prescriptive KAA diverges from the KR release's descriptive reality for
several common body sites (kidney, colon, oral cavity, etc.), which cost
translation quality. This dictionary is, by construction, KR-consistent.
"""
from __future__ import annotations

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
OUT_PATH = ROOT_DIR / "data" / "korean" / "dictionaries" / "kr_body_sites.tsv"

BODY_STRUCTURE_ROOT = "123037004"
IS_A_ID = 116680003

SYNONYM_TYPE_ID = "900000000000013009"
KR_LANG_REFSET_ID = "21000267104"
PREFERRED_ACCEPTABILITY_ID = "900000000000548007"
ACCEPTABLE_ACCEPTABILITY_ID = "900000000000549004"

SEMANTIC_TAG = " (body structure)"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kr_body_sites")


def load_preferred_descriptions() -> tuple[set[str], set[str]]:
    """Return (preferred_desc_ids, acceptable_desc_ids) in the KR language refset."""
    preferred: set[str] = set()
    acceptable: set[str] = set()
    with KO_LANGREFSET.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["active"] != "1":
                continue
            if row["refsetId"] != KR_LANG_REFSET_ID:
                continue
            acc = row["acceptabilityId"]
            desc_id = row["referencedComponentId"]
            if acc == PREFERRED_ACCEPTABILITY_ID:
                preferred.add(desc_id)
            elif acc == ACCEPTABLE_ACCEPTABILITY_ID:
                acceptable.add(desc_id)
    return preferred, acceptable


def load_korean_descriptions(
    preferred_ids: set[str], acceptable_ids: set[str]
) -> dict[str, tuple[str, list[str]]]:
    """Return {conceptId: (preferred_term, [acceptable_terms])}.

    If more than one preferred description is in the refset for a concept
    (rare but possible after edits), keep the first seen.
    """
    concept_preferred: dict[str, str] = {}
    concept_acceptable: dict[str, list[str]] = defaultdict(list)

    with KO_DESC.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["active"] != "1":
                continue
            if row["typeId"] != SYNONYM_TYPE_ID:
                continue
            desc_id = row["id"]
            concept_id = row["conceptId"]
            term = row["term"].strip()
            if not term:
                continue
            if desc_id in preferred_ids and concept_id not in concept_preferred:
                concept_preferred[concept_id] = term
            elif desc_id in acceptable_ids:
                concept_acceptable[concept_id].append(term)

    result: dict[str, tuple[str, list[str]]] = {}
    for cid, pref in concept_preferred.items():
        result[cid] = (pref, concept_acceptable.get(cid, []))
    return result


def body_structure_ids(g: nx.MultiDiGraph) -> set[str]:
    """Descendants of 123037004 |Body structure|, inclusive."""
    children: dict[str, list[str]] = defaultdict(list)
    for u, v, data in g.edges(data=True):
        if data.get("type_id") == IS_A_ID:
            children[v].append(u)
    seen = {BODY_STRUCTURE_ROOT}
    stack = [BODY_STRUCTURE_ROOT]
    while stack:
        n = stack.pop()
        for c in children.get(n, []):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def strip_tag(fsn: str) -> str:
    return fsn.replace(SEMANTIC_TAG, "").strip()


def main() -> None:
    log.info("Loading language refset...")
    preferred, acceptable = load_preferred_descriptions()
    log.info("  preferred desc ids: %d | acceptable: %d", len(preferred), len(acceptable))

    log.info("Loading Korean descriptions...")
    ko_by_concept = load_korean_descriptions(preferred, acceptable)
    log.info("  concepts with preferred Korean: %d", len(ko_by_concept))

    log.info("Loading SNOMED graph (for body-structure filter and English FSNs)...")
    g = nx.read_gml(GRAPH_PATH, label="label")

    log.info("Enumerating body-structure descendants of %s...", BODY_STRUCTURE_ROOT)
    body_ids = body_structure_ids(g)
    log.info("  %d body-structure concepts in International Edition", len(body_ids))

    kr_body_sites = {cid: v for cid, v in ko_by_concept.items() if cid in body_ids}
    log.info("  %d of those have a Korean preferred term in the KR release", len(kr_body_sites))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["en", "ko_preferred", "ko_synonyms", "la"],
            delimiter="\t",
        )
        writer.writeheader()
        written = 0
        missing_fsn = 0
        for cid, (ko_pref, ko_accept) in sorted(kr_body_sites.items()):
            if cid not in g:
                missing_fsn += 1
                continue
            fsn = g.nodes[cid].get("fsn", "")
            en = strip_tag(fsn)
            if not en:
                missing_fsn += 1
                continue
            writer.writerow({
                "en": en,
                "ko_preferred": ko_pref,
                "ko_synonyms": "; ".join(ko_accept),
                "la": "",
            })
            written += 1

    log.info("Wrote %s (%d rows, %d skipped for missing FSN)",
             OUT_PATH.relative_to(ROOT_DIR), written, missing_fsn)


if __name__ == "__main__":
    main()
