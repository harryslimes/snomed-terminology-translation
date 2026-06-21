#!/usr/bin/env python3
"""Synthetic long-tail translation runner.

Translates an eval CSV, but at prompt-build time filters the cached BGE-M3
exemplar pairs to simulate the conditions a truly novel concept would
face — the concept's own pair (and optionally its attribute-neighbours)
are stripped from the retrieval results before the LLM sees them.

Exclusion modes:
  none          No filtering (equivalent to translate_imaging_ablation baseline).
  self          Drop pairs whose SCTID == target SCTID.
  site          self + drop pairs whose SCTID shares any body-site attribute
                (procedure_site_direct / indirect / generic / finding).
  method        self + drop pairs whose SCTID shares the Method attribute.
  site+method   Union of site and method.

Requires:
  data/cache/fsn_to_sctid.json   Reverse FSN→SCTID map (one-off build).
  --attributes JSON              Per-SCTID attribute map (build_eval_attributes.py).
  --lookup-cache JSON            Existing BGE-M3 lookup cache (unchanged).

Outputs the same CSV schema as translate_imaging_ablation so downstream
scoring / judging works without modification.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("synth_longtail")

SEMANTIC_TAG_RE = re.compile(r"\s*\([^)]+\)\s*$")


# ---- Prompt templates (match translate_imaging_ablation for fairness) ----

SYSTEM_TEMPLATE_BASE = """\
You are a medical terminology translator specialising in English to Korean translation \
of SNOMED CT clinical terms in the **Procedure** hierarchy. You must follow the style \
guide below, which was derived from the official KHIS Korean SNOMED CT national \
extension (KR1000267). Return ONLY the Korean translation in Hangul (한글) — no \
explanation, no quotes, no romanisation, no English, no extra text.

# Korean SNOMED CT translation style guide

{style_guide}"""

SYSTEM_TEMPLATE_WITH_ADDENDUM = """\
You are a medical terminology translator specialising in English to Korean translation \
of SNOMED CT clinical terms in the radiology / imaging domain. You must follow the \
style guide below, which combines the general KHIS Korean style guide with a \
radiology-specific editorial addendum. Return ONLY the Korean translation in Hangul \
(한글) — no explanation, no quotes, no romanisation, no English, no extra text.

# Korean SNOMED CT translation style guide

{style_guide}

---

# Radiology editorial addendum (applies to this concept)

{addendum}"""

USER_TEMPLATE_BASE = """\
Here are similar Korean SNOMED translations for reference:

{paired_translations}

Translate this SNOMED CT procedure term from English to Korean.
English: {english}
Korean:"""

USER_TEMPLATE_WITH_REFS = """\
Here are similar Korean SNOMED translations for reference:

{paired_translations}

{reference_block}\
Translate this SNOMED CT procedure term from English to Korean.
English: {english}
Korean:"""


# ---- Dictionary helpers (ported from translate_imaging_ablation) ----

NON_ALPHA_RE = re.compile(r"[^a-z0-9 ]+")


def strip_semantic_tag(fsn: str) -> str:
    return SEMANTIC_TAG_RE.sub("", fsn).strip()


def normalize_key(s: str) -> str:
    s = s.lower().strip()
    s = NON_ALPHA_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_kaa(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            en = row["en"]
            ko = row["ko_preferred"]
            if not en or not ko:
                continue
            key = normalize_key(en)
            if key and key not in table:
                table[key] = ko
            if " structure" not in key:
                for variant in (f"{key} structure", f"structure of {key}"):
                    if variant not in table:
                        table[variant] = ko
    return table


def load_karp(path: Path) -> dict[str, str]:
    table: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            en = row["en"]
            ko = row["ko"]
            if not en or not ko:
                continue
            key = normalize_key(en)
            if key and key not in table:
                table[key] = ko
    return table


def lookup_body_site(kaa: dict[str, str], attr: dict) -> tuple[str, str] | None:
    for site_key in SITE_KEYS:
        fsn = attr.get(f"{site_key}_fsn")
        if not fsn:
            continue
        stripped = strip_semantic_tag(fsn)
        key = normalize_key(stripped)
        ko = kaa.get(key)
        if ko:
            return stripped, ko
        if key.endswith(" structure"):
            ko = kaa.get(key[:-len(" structure")])
            if ko:
                return stripped, ko
    return None


def lookup_karp_tokens(karp: dict[str, str], english: str, max_hits: int = 6) -> list[tuple[str, str]]:
    text = " " + normalize_key(english) + " "
    hits: list[tuple[str, str, int]] = []
    for key, ko in karp.items():
        if len(key) < 4:
            continue
        if " " + key + " " in text:
            hits.append((key, ko, len(key)))
    hits.sort(key=lambda x: -x[2])
    kept: list[tuple[str, str]] = []
    kept_keys: list[str] = []
    for key, ko, _ in hits:
        if any(key in kk for kk in kept_keys):
            continue
        kept.append((key, ko))
        kept_keys.append(key)
        if len(kept) >= max_hits:
            break
    return kept


def build_reference_block(english: str, attr: dict | None,
                          kaa: dict[str, str] | None,
                          karp: dict[str, str] | None) -> str:
    parts: list[str] = []
    if kaa and attr:
        site = lookup_body_site(kaa, attr)
        if site:
            en_site, ko_site = site
            parts.append(f"Authoritative body-site reference: {en_site} → {ko_site}")
    if karp:
        karp_hits = lookup_karp_tokens(karp, english)
        if karp_hits:
            lines = ["Radiation / imaging terminology references (Korean Association for Radiation Protection):"]
            for en, ko in karp_hits:
                lines.append(f"- {en} → {ko}")
            parts.append("\n".join(lines))
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"


# ---- Pair→SCTID resolution ----

def load_fsn_sctid(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["fsn_to_sctid"], data["pt_to_sctid"]


def pair_sctid(en_text: str, fsn_map: dict[str, str], pt_map: dict[str, str]) -> str | None:
    """Resolve the SCTID that a cached pair's EN text came from, if known."""
    en = en_text.strip()
    if en in fsn_map:
        return fsn_map[en]
    stripped = SEMANTIC_TAG_RE.sub("", en).strip().lower()
    return pt_map.get(stripped)


# ---- Exclusion set construction ----

SITE_KEYS = ("procedure_site_direct", "procedure_site_indirect",
             "procedure_site", "finding_site")


def build_neighbour_indices(attrs: dict[str, dict]) -> dict[str, dict[str, set[str]]]:
    """Reverse indices: attribute_target_id → {sctid, ...}."""
    site_idx: dict[str, set[str]] = defaultdict(set)
    method_idx: dict[str, set[str]] = defaultdict(set)
    for sctid, a in attrs.items():
        for k in SITE_KEYS:
            tid = a.get(f"{k}_id")
            if tid:
                site_idx[tid].add(sctid)
        mid = a.get("method_id")
        if mid:
            method_idx[mid].add(sctid)
    return {"site": dict(site_idx), "method": dict(method_idx)}


def exclusion_sctids(target_sctid: str, target_attrs: dict,
                     indices: dict[str, dict[str, set[str]]],
                     mode: str) -> set[str]:
    excl: set[str] = {target_sctid}
    if "none" in mode:
        return set()  # caller should not even call us for 'none', but safe
    if "site" in mode:
        for k in SITE_KEYS:
            tid = target_attrs.get(f"{k}_id")
            if tid:
                excl |= indices["site"].get(tid, set())
    if "method" in mode:
        mid = target_attrs.get("method_id")
        if mid:
            excl |= indices["method"].get(mid, set())
    return excl


# ---- Pair filtering and table formatting ----

def filter_pairs(pairs: list[list[str]], excl: set[str],
                 fsn_map: dict[str, str], pt_map: dict[str, str],
                 top_k: int) -> tuple[list[list[str]], int]:
    """Return (kept_pairs, removed_count). Pairs are expected to be pre-sorted."""
    kept: list[list[str]] = []
    removed = 0
    for pair in pairs:
        en = pair[0] if pair else ""
        ps = pair_sctid(en, fsn_map, pt_map)
        if ps and ps in excl:
            removed += 1
            continue
        kept.append(pair)
        if len(kept) >= top_k:
            break
    return kept, removed


def format_pairs_table(pairs: list[list[str]]) -> str:
    if not pairs:
        return "(no similar translations found)"
    lines = ["|English|Korean|", "|---|---|"]
    for en, ko in pairs:
        lines.append(f"|{en}|{ko}|")
    return "\n".join(lines)


# ---- LLM ----

def wait_for_server(base_url: str, timeout: int = 300) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise SystemExit(f"vLLM not ready within {timeout}s")


def translate_one(base_url: str, model_id: str, system_prompt: str,
                  user_prompt: str, llm_params: dict) -> str:
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **llm_params,
    }
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=180)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    if "<think>" in (content or ""):
        content = content.split("</think>")[-1]
    return (content or "").strip().strip('"').strip("'").strip()


# ---- Main ----

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exclusion", choices=["none", "self", "site", "method", "site+method"],
                        default="self",
                        help="Exemplar exclusion policy at retrieval time.")
    parser.add_argument("--top-k", type=int, default=5,
                        help="Keep this many pairs after filtering.")
    parser.add_argument("--model", type=str, default=None,
                        help="Model key from configs/models.json.")
    parser.add_argument("--tag", type=str, default=None,
                        help="Output tag; defaults to <model>_<exclusion>.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--eval-set", type=Path,
                        default=ROOT_DIR / "data" / "evals" / "korean" / "procedure_eval_set.csv")
    parser.add_argument("--attributes", type=Path,
                        default=ROOT_DIR / "data" / "evals" / "korean" / "synthetic_long_tail" / "procedure_attributes.json")
    parser.add_argument("--lookup-cache", type=Path,
                        default=ROOT_DIR / "data" / "evals" / "korean" / "lookup_cache.json")
    parser.add_argument("--fsn-sctid", type=Path,
                        default=ROOT_DIR / "data" / "cache" / "fsn_to_sctid.json")
    parser.add_argument("--style-guide", type=Path,
                        default=ROOT_DIR / "style_guide" / "style_guide_ko_v3.md")
    parser.add_argument("--use-addendum", action="store_true",
                        help="Append the radiology editorial addendum to the system prompt.")
    parser.add_argument("--addendum", type=Path,
                        default=ROOT_DIR / "style_guide" / "addenda" / "radiology_editorial_guide_ko.md")
    parser.add_argument("--use-kaa", action="store_true",
                        help="Inject KAA body-site references in the user prompt.")
    parser.add_argument("--kaa", type=Path,
                        default=ROOT_DIR / "data" / "korean" / "dictionaries" / "kaa_anatomy.tsv")
    parser.add_argument("--use-karp", action="store_true",
                        help="Inject KARP radiation-term matches in the user prompt.")
    parser.add_argument("--karp", type=Path,
                        default=ROOT_DIR / "data" / "korean" / "dictionaries" / "karp_radiation.tsv")
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT_DIR / "data" / "evals" / "korean" / "synthetic_long_tail")
    args = parser.parse_args()

    cfg = json.loads((ROOT_DIR / "configs" / "models.json").read_text())
    job_cfg = cfg["jobs"]["translate_korean_lookup"]
    model_key = args.model or job_cfg["default_model"]
    model_cfg = cfg["models"][model_key]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]
    concurrency = args.concurrency or job_cfg.get("concurrency", 16)
    llm_params = job_cfg.get("llm_params", {})

    extras_tag = "".join([
        "+add" if args.use_addendum else "",
        "+kaa" if args.use_kaa else "",
        "+karp" if args.use_karp else "",
    ]) or "base"
    tag = args.tag or f"{model_key}_{args.exclusion.replace('+','_')}_{extras_tag}"

    # ---- Load resources ----
    guide = args.style_guide.read_text(encoding="utf-8")
    if args.use_addendum:
        addendum = args.addendum.read_text(encoding="utf-8")
        system_prompt = SYSTEM_TEMPLATE_WITH_ADDENDUM.format(
            style_guide=guide, addendum=addendum,
        )
    else:
        system_prompt = SYSTEM_TEMPLATE_BASE.format(style_guide=guide)

    kaa: dict[str, str] | None = load_kaa(args.kaa) if args.use_kaa else None
    karp: dict[str, str] | None = load_karp(args.karp) if args.use_karp else None
    use_reference_block = args.use_kaa or args.use_karp

    log.info(
        "Arm: exclusion=%s, addendum=%s, kaa=%s (%d keys), karp=%s (%d keys)",
        args.exclusion, args.use_addendum,
        args.use_kaa, len(kaa) if kaa else 0,
        args.use_karp, len(karp) if karp else 0,
    )

    log.info("Loading lookup cache + attributes + FSN map...")
    lookup = json.loads(args.lookup_cache.read_text(encoding="utf-8"))
    attrs = json.loads(args.attributes.read_text(encoding="utf-8"))
    fsn_map, pt_map = load_fsn_sctid(args.fsn_sctid)
    log.info("  lookup=%d, attrs=%d, fsn_map=%d, pt_map=%d",
             len(lookup), len(attrs), len(fsn_map), len(pt_map))

    indices = build_neighbour_indices(attrs) if args.exclusion not in ("none", "self") else {"site": {}, "method": {}}

    rows = list(csv.DictReader(args.eval_set.open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"translations_{tag}.csv"

    done_sctids: set[str] = set()
    if args.resume and out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done_sctids.add(row["sctid"])
        log.info("Resuming: %d already done in %s", len(done_sctids), out_path.name)

    remaining = [r for r in rows if r["sctid"] not in done_sctids]
    log.info("Exclusion=%s | top_k=%d | model=%s | eval=%d | remaining=%d | concurrency=%d",
             args.exclusion, args.top_k, model_key, len(rows), len(remaining), concurrency)

    wait_for_server(base_url)

    mode = "a" if done_sctids else "w"
    outf = out_path.open(mode, encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf,
        fieldnames=["sctid", "preferred_term", "ko_reference", "translation",
                    "n_pairs_kept", "n_pairs_removed", "kaa_hit", "karp_hits"],
    )
    if mode == "w":
        writer.writeheader()

    lock = Lock()
    completed = [0]
    errors = [0]
    total_removed = [0]
    zero_pair = [0]
    kaa_fires = [0]
    karp_fires = [0]
    t0 = time.monotonic()

    def process_row(row: dict) -> dict:
        sctid = row["sctid"]
        english = row["preferred_term"]
        cached = lookup.get(sctid, [])

        if args.exclusion == "none":
            kept = cached[: args.top_k]
            removed = 0
        else:
            tgt_attrs = attrs.get(sctid, {})
            excl = exclusion_sctids(sctid, tgt_attrs, indices, args.exclusion)
            kept, removed = filter_pairs(cached, excl, fsn_map, pt_map, args.top_k)

        pairs_table = format_pairs_table(kept)

        kaa_hit = ""
        karp_hits: list[tuple[str, str]] = []
        if use_reference_block:
            tgt_attrs = attrs.get(sctid, {}) if args.use_kaa else None
            if args.use_kaa and tgt_attrs:
                site = lookup_body_site(kaa, tgt_attrs)
                if site:
                    kaa_hit = f"{site[0]} → {site[1]}"
            if args.use_karp:
                karp_hits = lookup_karp_tokens(karp, english)
            ref_block = build_reference_block(english, tgt_attrs, kaa, karp)
            user_prompt = USER_TEMPLATE_WITH_REFS.format(
                paired_translations=pairs_table,
                reference_block=ref_block,
                english=english,
            )
        else:
            user_prompt = USER_TEMPLATE_BASE.format(
                paired_translations=pairs_table,
                english=english,
            )

        try:
            t = translate_one(base_url, model_id, system_prompt, user_prompt, llm_params)
        except Exception as exc:
            log.error("%s -> ERROR %s", english[:40], exc)
            t = f"ERROR: {exc}"

        return {
            "sctid": sctid,
            "preferred_term": english,
            "ko_reference": row["ko_reference"],
            "translation": t,
            "n_pairs_kept": len(kept),
            "n_pairs_removed": removed,
            "kaa_hit": kaa_hit,
            "karp_hits": "; ".join(f"{en}→{ko}" for en, ko in karp_hits),
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(process_row, row): row for row in remaining}
        for fut in as_completed(futures):
            result = fut.result()
            with lock:
                writer.writerow(result)
                outf.flush()
                completed[0] += 1
                if result["translation"].startswith("ERROR"):
                    errors[0] += 1
                total_removed[0] += result["n_pairs_removed"]
                if result["n_pairs_kept"] == 0:
                    zero_pair[0] += 1
                if result["kaa_hit"]:
                    kaa_fires[0] += 1
                if result["karp_hits"]:
                    karp_fires[0] += 1
                if completed[0] % 200 == 0:
                    elapsed = time.monotonic() - t0
                    rate = completed[0] / elapsed if elapsed > 0 else 0
                    eta = (len(remaining) - completed[0]) / rate if rate > 0 else 0
                    log.info(
                        "Progress: %d/%d | %.1f req/s | ETA %.0fs | errors=%d | zero-pair=%d | avg removed=%.1f",
                        completed[0], len(remaining), rate, eta, errors[0],
                        zero_pair[0], total_removed[0] / max(completed[0], 1),
                    )

    outf.close()
    elapsed = time.monotonic() - t0
    log.info("Done. Wrote %s (%d translations, %d errors, %.0fs)",
             out_path, completed[0], errors[0], elapsed)
    log.info("Exclusion stats: total pairs removed=%d, zero-pair after filter=%d/%d",
             total_removed[0], zero_pair[0], completed[0])
    if args.use_kaa or args.use_karp:
        log.info("Extras fire rates: KAA %d/%d (%.0f%%), KARP %d/%d (%.0f%%)",
                 kaa_fires[0], completed[0], 100 * kaa_fires[0] / max(completed[0], 1),
                 karp_fires[0], completed[0], 100 * karp_fires[0] / max(completed[0], 1))


if __name__ == "__main__":
    main()
