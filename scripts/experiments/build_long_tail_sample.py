#!/usr/bin/env python3
"""Build a stratified 100-concept sample from the untranslated radiology long tail.

Sample strata (target n in parentheses, may shift slightly to fill):

  A. Novel-site + common modality (CT/MRI/US/X-ray)        n=30
     Tests the regime where exemplar retrieval cannot
     surface the body-site Korean (no translated procedure
     references this site), but the modality is well-known.
     → most likely to benefit from a body-site dictionary.

  B. Novel-site + uncommon modality                          n=20
     Both axes unfamiliar. The hardest regime; expect the
     pipeline to struggle here regardless.

  C. Familiar-site + uncommon modality                       n=20
     Site has Korean coverage via translated procedures, but
     modality is novel. Tests modality vocabulary handling.

  D. Familiar-site + common modality, compound FSN           n=20
     Site and modality are both familiar but the source FSN
     is long / has many modifiers (contrast, view, approach).
     Composition stress test.

  E. Random untranslated                                     n=10
     No stratification — controls against curator bias and
     gives a representative-of-typical-long-tail anchor.

A "common modality" is one of the top 4 in KR-translated set:
Computed tomography, Magnetic resonance imaging, Ultrasound, Plain X-ray.

A "novel site" is a Procedure-site-Direct attribute target that does NOT
appear as a Procedure-site-Direct on any concept in the KR-translated
imaging eval set.

"Compound FSN" = FSN length > 80 characters (median for the imaging
hierarchy is ~64; >80 captures the long-tail composition cases).

Output: data/evals/korean/long_tail_sme/sample_100.csv with columns
  sctid, preferred_term, en_fsn, hierarchy, ko_reference (empty),
  stratum, method_id, method_fsn, site_id, site_fsn,
  novel_site, common_modality, fsn_length
"""
from __future__ import annotations

import csv
import logging
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

ROOT_DIR = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT_DIR / "snomed_graph" / "full_concept_graph.gml"
TRANSLATED_EVAL = ROOT_DIR / "data" / "evals" / "korean" / "imaging_ablation" / "imaging_eval_set.csv"
OUT_PATH = ROOT_DIR / "data" / "evals" / "korean" / "long_tail_sme" / "sample_100.csv"

IMAGING_ROOT = "363679005"
IS_A = 116680003
METHOD = 260686004
DIRECT_SITE = 405813007

# Common modality method SCTIDs (the top 4 in the KR-translated set)
COMMON_MODALITY_IDS = {
    "312251004",  # Computed tomography imaging - action
    "312250003",  # Magnetic resonance imaging - action
    "278292003",  # Ultrasound imaging - action
    "168537006",  # Plain X-ray imaging - action
}

SEMANTIC_TAG_RE = re.compile(r"\s*\([^)]+\)\s*$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build_sample")


def strip_tag(s: str) -> str:
    return SEMANTIC_TAG_RE.sub("", s).strip()


def descendants(g: nx.MultiDiGraph, root: str) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for u, v, d in g.edges(data=True):
        if d.get("type_id") == IS_A:
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


def per_concept_attrs(g: nx.MultiDiGraph, sctids: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for u, v, d in g.edges(data=True):
        if u not in sctids:
            continue
        tid = d.get("type_id")
        e = out.setdefault(u, {})
        if tid == METHOD and "method_id" not in e:
            e["method_id"] = v
            e["method_fsn"] = g.nodes[v].get("fsn", "")
        elif tid == DIRECT_SITE and "site_id" not in e:
            e["site_id"] = v
            e["site_fsn"] = g.nodes[v].get("fsn", "")
    return out


def stratify_and_sample(candidates: list[dict], seed: int = 42) -> list[dict]:
    rng = random.Random(seed)

    # Sort by stratum priority. Within stratum, random.
    A = [c for c in candidates if c["stratum"] == "A"]
    B = [c for c in candidates if c["stratum"] == "B"]
    C = [c for c in candidates if c["stratum"] == "C"]
    D = [c for c in candidates if c["stratum"] == "D"]
    E = [c for c in candidates if c["stratum"] == "E"]

    target = {"A": 30, "B": 20, "C": 20, "D": 20, "E": 10}
    pools = {"A": A, "B": B, "C": C, "D": D, "E": E}
    chosen: list[dict] = []
    for s, n in target.items():
        pool = pools[s]
        rng.shuffle(pool)
        if len(pool) < n:
            log.warning("stratum %s underfilled: %d available, %d requested", s, len(pool), n)
        chosen.extend(pool[:n])

    # Within strata that need it, ensure modality diversity.
    # (Light constraint — don't enforce, just log distribution.)
    return chosen


def main() -> None:
    log.info("Loading SNOMED graph...")
    g = nx.read_gml(GRAPH_PATH, label="label")
    log.info("  %d nodes", g.number_of_nodes())

    log.info("Enumerating imaging descendants...")
    imaging = descendants(g, IMAGING_ROOT)
    log.info("  %d imaging concepts (International Edition)", len(imaging))

    translated = {r["sctid"] for r in csv.DictReader(TRANSLATED_EVAL.open(encoding="utf-8"))}
    untranslated = imaging - translated
    log.info("  %d untranslated", len(untranslated))

    log.info("Collecting attributes for both translated + untranslated...")
    trans_attrs = per_concept_attrs(g, translated)
    untrans_attrs = per_concept_attrs(g, untranslated)

    # Sites that appear as Direct site on any translated concept
    translated_sites = {a["site_id"] for a in trans_attrs.values() if "site_id" in a}
    log.info("  translated set has %d distinct direct sites", len(translated_sites))

    # Build candidate list with metadata
    candidates: list[dict] = []
    for sctid in untranslated:
        a = untrans_attrs.get(sctid, {})
        site_id = a.get("site_id", "")
        site_fsn = a.get("site_fsn", "")
        method_id = a.get("method_id", "")
        method_fsn = a.get("method_fsn", "")
        fsn = g.nodes[sctid].get("fsn", "")
        en_term = strip_tag(fsn)
        novel_site = bool(site_id) and site_id not in translated_sites
        common_modality = method_id in COMMON_MODALITY_IDS
        # Need a site_id to be in stratum A/B/C; D allows familiar site
        # Determine stratum
        stratum = None
        if novel_site and common_modality:
            stratum = "A"
        elif novel_site and not common_modality and method_id:
            stratum = "B"
        elif (not novel_site) and (not common_modality) and method_id and site_id:
            stratum = "C"
        elif (not novel_site) and common_modality and site_id and len(en_term) > 80:
            stratum = "D"
        else:
            stratum = "E"  # everything else, including FSN-only or attribute-sparse

        candidates.append({
            "sctid": sctid,
            "en_fsn": fsn,
            "preferred_term": en_term,
            "hierarchy": "procedure",
            "ko_reference": "",  # long tail — no reference exists
            "stratum": stratum,
            "method_id": method_id,
            "method_fsn": method_fsn,
            "site_id": site_id,
            "site_fsn": site_fsn,
            "novel_site": str(novel_site),
            "common_modality": str(common_modality),
            "fsn_length": str(len(en_term)),
        })

    # Stratum distribution
    counts = defaultdict(int)
    for c in candidates:
        counts[c["stratum"]] += 1
    log.info("Stratum availability: %s", dict(counts))

    chosen = stratify_and_sample(candidates)
    log.info("Sampled %d concepts", len(chosen))

    # Modality distribution within the chosen set (sanity check)
    mod_counts = defaultdict(int)
    for c in chosen:
        mod_counts[c["method_fsn"] or "(no method)"] += 1
    log.info("Modality breakdown of the 100-concept sample:")
    for mod, n in sorted(mod_counts.items(), key=lambda x: -x[1]):
        log.info("  %3d  %s", n, mod[:80])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sctid", "preferred_term", "en_fsn", "hierarchy", "ko_reference",
        "stratum", "method_id", "method_fsn", "site_id", "site_fsn",
        "novel_site", "common_modality", "fsn_length",
    ]
    with OUT_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        # Sort output by stratum then sctid for stability
        chosen.sort(key=lambda c: (c["stratum"], c["sctid"]))
        w.writerows(chosen)
    log.info("Wrote %s", OUT_PATH.relative_to(ROOT_DIR))


if __name__ == "__main__":
    main()
