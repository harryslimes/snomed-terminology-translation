#!/usr/bin/env python3
"""Imaging-resources ablation translation runner.

Translates imaging-eval concepts under one of two arms:

  A (baseline)    base style guide + BGE-M3 exemplar lookup (current pipeline)
  B (with_extras) A + radiology editorial addendum
                    + KAA body-site dictionary injection (when site known)
                    + KARP radiation-term dictionary injection (token matches)

Reuses the lookup cache produced by translate_korean_with_lookup.py so BGE-M3
embedding work is not repeated. The cache is keyed by sctid; if a concept is
missing from it, we fall through with no exemplars for that concept.

Outputs:
  data/evals/korean/imaging_ablation/translations_<arm>_<tag>.csv

Design note: this script intentionally hard-codes the two-arm wiring. It is
NOT a generic manifest interpreter — that was ruled out in the design
discussion. If more resource types are added later, this script is a
reasonable starting point to generalise from.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ablate_imaging")

LOOKUP_CACHE = ROOT_DIR / "data" / "evals" / "korean" / "lookup_cache.json"
OUT_DIR = ROOT_DIR / "data" / "evals" / "korean" / "imaging_ablation"


# --- Prompt templates ---------------------------------------------------------

SYSTEM_TEMPLATE_BASE = """\
You are a medical terminology translator specialising in English to Korean translation \
of SNOMED CT clinical terms. You must follow the style guide below, which was derived \
from the official KHIS Korean SNOMED CT national extension (KR1000267). Return ONLY \
the Korean translation in Hangul (한글) — no explanation, no quotes, no romanisation, \
no English, no extra text.

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

USER_TEMPLATE_A = """\
Here are similar Korean SNOMED translations for reference:

{paired_translations}

Translate this SNOMED CT procedure term from English to Korean.
English: {english}
Korean:"""

USER_TEMPLATE_B = """\
Here are similar Korean SNOMED translations for reference:

{paired_translations}

{reference_block}\
Translate this SNOMED CT procedure term from English to Korean.
English: {english}
Korean:"""


# --- Dictionary lookup helpers ------------------------------------------------

SEMANTIC_TAG_RE = re.compile(r"\s*\([^)]+\)\s*$")
NON_ALPHA_RE = re.compile(r"[^a-z0-9 ]+")


def strip_semantic_tag(fsn: str) -> str:
    return SEMANTIC_TAG_RE.sub("", fsn).strip()


def normalize_key(s: str) -> str:
    s = s.lower().strip()
    s = NON_ALPHA_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_kaa(path: Path) -> dict[str, str]:
    """Build normalized-English -> Korean preferred term map.

    Includes variants on the key to improve hit rate: "foo structure" and
    "structure of foo" are also indexed against the entry for "foo" where
    applicable.
    """
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
            # Variants: e.g. "Kidney" → also index "kidney structure"
            if " structure" not in key:
                variant = f"{key} structure"
                if variant not in table:
                    table[variant] = ko
                variant2 = f"structure of {key}"
                if variant2 not in table:
                    table[variant2] = ko
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


def lookup_body_site(
    kaa: dict[str, str],
    attr: dict,
) -> tuple[str, str] | None:
    """Look up a body-site reference in KAA.

    Tries direct site first, falls back to indirect / generic / finding.
    Returns (english_site_fsn, korean_term) or None on miss.
    """
    for site_key in ("procedure_site_direct",
                     "procedure_site_indirect",
                     "procedure_site",
                     "finding_site"):
        fsn_field = f"{site_key}_fsn"
        fsn = attr.get(fsn_field)
        if not fsn:
            continue
        stripped = strip_semantic_tag(fsn)
        key = normalize_key(stripped)
        ko = kaa.get(key)
        if ko:
            return stripped, ko
        # Try "structure" suffix stripping
        if key.endswith(" structure"):
            ko = kaa.get(key[:-len(" structure")])
            if ko:
                return stripped, ko
    return None


def lookup_karp_tokens(karp: dict[str, str], english: str, max_hits: int = 6) -> list[tuple[str, str]]:
    """Match KARP glossary entries inside the English FSN.

    Checks each KARP key's presence as a substring of the normalized English.
    Only returns the longer / more specific hits (filters single common words
    that are too short).
    """
    text = " " + normalize_key(english) + " "
    hits: list[tuple[str, str, int]] = []
    for key, ko in karp.items():
        if len(key) < 4:
            continue
        if " " + key + " " in text:
            hits.append((key, ko, len(key)))
    # Sort longest key first (more specific)
    hits.sort(key=lambda x: -x[2])
    # Dedupe sub-matches: if a longer key already matched and a shorter key is
    # a substring of the longer one, drop the shorter.
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


# --- Prompt assembly ----------------------------------------------------------

def format_pairs_table(pairs: list[list[str]]) -> str:
    if not pairs:
        return "(no similar translations found)"
    lines = ["|English|Korean|", "|---|---|"]
    for en, ko in pairs:
        lines.append(f"|{en}|{ko}|")
    return "\n".join(lines)


def build_reference_block(
    english: str,
    attr: dict | None,
    kaa: dict[str, str] | None,
    karp: dict[str, str] | None,
) -> str:
    """Compose the deterministic-reference block.

    Only the dictionaries that are passed in (truthy) contribute. Returns
    empty string if neither fires.
    """
    parts: list[str] = []
    if kaa and attr:
        site = lookup_body_site(kaa, attr)
        if site:
            en_site, ko_site = site
            parts.append(
                f"Authoritative body-site reference: {en_site} → {ko_site}"
            )
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


# --- LLM call ----------------------------------------------------------------

def wait_for_server(base_url: str, timeout: int = 900) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                log.info("vLLM ready: %s", models)
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise SystemExit(f"vLLM not ready within {timeout}s")


def translate_one(
    base_url: str,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    llm_params: dict,
) -> str:
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
    if "<think>" in content:
        content = content.split("</think>")[-1]
    return content.strip().strip('"').strip("'").strip()


# --- Main --------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm-name", required=True,
                        help="Label used in output filename and logs, e.g. 'baseline', 'all_extras', 'no_kaa'")
    parser.add_argument("--use-addendum", action="store_true",
                        help="Append the radiology editorial addendum to the system prompt")
    parser.add_argument("--use-kaa", action="store_true",
                        help="Inject KAA body-site references in the user prompt")
    parser.add_argument("--use-karp", action="store_true",
                        help="Inject KARP radiation-term matches in the user prompt")
    parser.add_argument("--model", type=str, default=None, help="Model key from configs/models.json")
    parser.add_argument("--tag", type=str, default=None, help="Output tag; defaults to model key")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for testing")
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--resume", action="store_true", help="Resume from existing output")
    parser.add_argument("--eval-set", type=Path,
                        default=OUT_DIR / "imaging_eval_set.csv")
    parser.add_argument("--attributes", type=Path,
                        default=OUT_DIR / "imaging_attributes.json")
    parser.add_argument("--style-guide", type=Path,
                        default=ROOT_DIR / "style_guide" / "style_guide_ko_v3.md")
    parser.add_argument("--addendum", type=Path,
                        default=ROOT_DIR / "style_guide" / "addenda" / "radiology_editorial_guide_ko.md")
    parser.add_argument("--kaa", type=Path,
                        default=ROOT_DIR / "data" / "korean" / "dictionaries" / "kaa_anatomy.tsv")
    parser.add_argument("--karp", type=Path,
                        default=ROOT_DIR / "data" / "korean" / "dictionaries" / "karp_radiation.tsv")
    args = parser.parse_args()

    cfg_path = ROOT_DIR / "configs" / "models.json"
    cfg = json.loads(cfg_path.read_text())
    job_cfg = cfg["jobs"]["translate_korean_lookup"]
    model_key = args.model or job_cfg["default_model"]
    model_cfg = cfg["models"][model_key]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]
    concurrency = args.concurrency or job_cfg.get("concurrency", 16)
    llm_params = job_cfg.get("llm_params", {})
    tag = args.tag or model_key

    # --- Load resources conditional on flags ---
    guide = args.style_guide.read_text(encoding="utf-8")

    if args.use_addendum:
        addendum = args.addendum.read_text(encoding="utf-8")
        system_prompt_template = SYSTEM_TEMPLATE_WITH_ADDENDUM.format(
            style_guide=guide, addendum=addendum,
        )
    else:
        system_prompt_template = SYSTEM_TEMPLATE_BASE.format(style_guide=guide)

    kaa: dict[str, str] | None = None
    if args.use_kaa:
        kaa = load_kaa(args.kaa)
    karp: dict[str, str] | None = None
    if args.use_karp:
        karp = load_karp(args.karp)

    log.info(
        "Arm '%s': addendum=%s, kaa=%s (%d keys), karp=%s (%d keys)",
        args.arm_name, args.use_addendum,
        args.use_kaa, len(kaa) if kaa else 0,
        args.use_karp, len(karp) if karp else 0,
    )

    # --- Load eval set and lookup cache ---
    rows = list(csv.DictReader(args.eval_set.open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]

    if not LOOKUP_CACHE.exists():
        log.error("Lookup cache missing: %s. Run translate_korean_with_lookup.py --prepare-lookups first.",
                  LOOKUP_CACHE)
        sys.exit(1)
    lookup_cache = json.loads(LOOKUP_CACHE.read_text(encoding="utf-8"))

    # Attributes are only needed for the KAA lookup path
    attributes: dict[str, dict] = {}
    if args.use_kaa:
        attributes = json.loads(args.attributes.read_text(encoding="utf-8"))

    # --- Output ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"translations_{args.arm_name}_{tag}.csv"

    done_sctids: set[str] = set()
    if args.resume and out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done_sctids.add(row["sctid"])
        log.info("Resuming: %d already done in %s", len(done_sctids), out_path.name)

    remaining = [r for r in rows if r["sctid"] not in done_sctids]
    log.info("Arm '%s' | model=%s | eval=%d | remaining=%d | concurrency=%d",
             args.arm_name, model_key, len(rows), len(remaining), concurrency)

    if not remaining:
        log.info("Nothing to do.")
        return

    # --- Server readiness ---
    wait_for_server(base_url)

    mode = "a" if done_sctids else "w"
    outf = out_path.open(mode, encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf,
        fieldnames=["sctid", "preferred_term", "ko_reference", "translation",
                    "kaa_hit", "karp_hits"],
    )
    if mode == "w":
        writer.writeheader()

    lock = Lock()
    completed = [0]
    errors = [0]
    t0 = time.monotonic()

    # Stats on resource fire rate (arm B only)
    kaa_fires = [0]
    karp_fires = [0]

    use_reference_block = args.use_kaa or args.use_karp

    def process_row(row: dict) -> dict:
        english = row["preferred_term"]
        sctid = row["sctid"]
        pairs = lookup_cache.get(sctid, [])
        pairs_table = format_pairs_table(pairs)

        kaa_hit = ""
        karp_hits: list[tuple[str, str]] = []

        if use_reference_block:
            attr = attributes.get(sctid) if args.use_kaa else None
            if args.use_kaa and attr:
                site = lookup_body_site(kaa, attr)
                if site:
                    kaa_hit = f"{site[0]} → {site[1]}"
            if args.use_karp:
                karp_hits = lookup_karp_tokens(karp, english)
            ref_block = build_reference_block(english, attr, kaa, karp)
            user_prompt = USER_TEMPLATE_B.format(
                paired_translations=pairs_table,
                reference_block=ref_block,
                english=english,
            )
        else:
            user_prompt = USER_TEMPLATE_A.format(
                paired_translations=pairs_table,
                english=english,
            )

        try:
            t = translate_one(base_url, model_id, system_prompt_template, user_prompt, llm_params)
        except Exception as exc:
            log.error("%s -> ERROR %s", english[:40], exc)
            t = f"ERROR: {exc}"

        return {
            "sctid": sctid,
            "preferred_term": english,
            "ko_reference": row["ko_reference"],
            "translation": t,
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
                if result["kaa_hit"]:
                    kaa_fires[0] += 1
                if result["karp_hits"]:
                    karp_fires[0] += 1
                if completed[0] % 50 == 0:
                    elapsed = time.monotonic() - t0
                    rate = completed[0] / elapsed if elapsed > 0 else 0
                    eta = (len(remaining) - completed[0]) / rate if rate > 0 else 0
                    log.info(
                        "Progress: %d/%d | %.1f req/s | ETA %.0fs | errors=%d | kaa=%d | karp=%d",
                        completed[0], len(remaining), rate, eta, errors[0],
                        kaa_fires[0], karp_fires[0],
                    )

    outf.close()
    elapsed = time.monotonic() - t0
    log.info("Done. Wrote %s (%d translations, %d errors, %.0fs)",
             out_path, completed[0], errors[0], elapsed)
    if args.use_kaa or args.use_karp:
        log.info("Resource fire rates: KAA %d/%d (%.0f%%), KARP %d/%d (%.0f%%)",
                 kaa_fires[0], completed[0], 100 * kaa_fires[0] / max(completed[0], 1),
                 karp_fires[0], completed[0], 100 * karp_fires[0] / max(completed[0], 1))


if __name__ == "__main__":
    main()
