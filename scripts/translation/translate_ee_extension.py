#!/usr/bin/env python
"""
Translate all EE SNOMED extension terms using Qwen 35B, applying hierarchy
rules where available. Compare translation embeddings against official
Estonian translations.

Usage:
    CUDA_VISIBLE_DEVICES="" .venv/bin/python scripts/translate_ee_extension.py
    CUDA_VISIBLE_DEVICES="" .venv/bin/python scripts/translate_ee_extension.py --hierarchy "body structure"
    CUDA_VISIBLE_DEVICES="" .venv/bin/python scripts/translate_ee_extension.py --skip-translate  # just re-plot
"""
import asyncio
import csv
import json
import logging
import re
import sys
from pathlib import Path

import aiohttp
import numpy as np
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("translate_ee")

VLLM_URL = "http://localhost:8000"
VLLM_MODEL = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
EMBEDDINGS_CSV = Path("data/evals/ee_extension_embeddings.csv")
RULES_DIR = Path("data/rules/qwen35b_35b")
OUTPUT_DIR = Path("data/evals/ee_extension_translations")
EE_EXTENSION_PATH = Path("data/SNOMED_EE_national_extension/xsct2_Description_Snapshot-et_EE1000181_20250530.txt")
SNOMED_GRAPH_PATH = Path("data/snomed_graph/full_concept_graph.gml")

SYSTEM_PROMPT_BASE = """\
You are a medical terminology translator for SNOMED CT (English → Estonian).

STRICT RULES:
1. Output ONLY the Estonian translation — one term, nothing else.
2. Do NOT add explanations, alternatives, qualifiers, or surrounding context.
3. Translate EXACTLY the given term — do not broaden scope, do not prepend \
related diagnoses, do not add anatomical context that is absent from the source.
4. Use clinical/medical register. Always prefer the precise medical or \
histological term over a colloquial or general-language synonym.
5. Prefer Estonian medical compound words over multi-word phrases where a \
recognised compound exists.
6. For international terms (drug names, chemical compounds, organisms): apply \
standard Estonian phonetic adaptation rules consistently.
7. Match the grammatical number and case of the source term faithfully.
8. Start the translation with an uppercase letter."""

SAMPLING_PARAMS = {"temperature": 0, "top_p": 1.0, "repetition_penalty": 1.0}


def load_rules() -> dict[str, list[str]]:
    """Load all hierarchy rules from YAML files."""
    rules = {}
    for path in RULES_DIR.glob("*.yaml"):
        with path.open() as f:
            data = yaml.safe_load(f)
        if data and data.get("rules"):
            rules[data["hierarchy"]] = data["rules"]
    return rules


def build_system_prompt(hierarchy: str, rules: dict[str, list[str]]) -> str:
    """Build system prompt, adding rules if available for this hierarchy."""
    if hierarchy in rules:
        rules_text = "\n".join(f"- {r}" for r in rules[hierarchy])
        return f"{SYSTEM_PROMPT_BASE}\n\n# Hierarchy-specific translation rules\n{rules_text}"
    return SYSTEM_PROMPT_BASE


def load_items() -> list[dict]:
    """Load EE extension items with EN terms, ET references, and hierarchy."""
    items = []
    with EMBEDDINGS_CSV.open() as f:
        for r in csv.DictReader(f):
            items.append({
                "sctid": r["sctid"],
                "en_term": r["en_term"],
                "et_primary": r["et_primary"],
                "hierarchy": r["hierarchy"],
                "en_et_cosine": float(r["en_et_cosine"]),
                "str_sim": float(r["str_sim_en_et"]),
                "likely_latin": int(r["likely_latin"]),
            })
    return items


def load_ee_all_terms() -> dict[str, list[str]]:
    """Load all Estonian terms per concept (for multi-reference scoring)."""
    with EE_EXTENSION_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = [r for r in reader if r["active"] == "1"]
    ee = {}
    for r in rows:
        cid = r["conceptId"]
        if cid not in ee:
            ee[cid] = []
        ee[cid].append(r["term"])
    return ee


def clean_translation(text: str) -> str:
    """Strip think tags and any extra output from translation."""
    if "<think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Take first non-empty line only
    for line in text.strip().split("\n"):
        line = line.strip()
        if line:
            return line
    return text.strip()


async def translate_batch(
    items: list[dict],
    rules: dict[str, list[str]],
    concurrency: int = 32,
) -> list[dict]:
    """Translate all items via vLLM."""
    sem = asyncio.Semaphore(concurrency)

    # Pre-build system prompts per hierarchy
    sys_prompts = {}
    for item in items:
        h = item["hierarchy"]
        if h not in sys_prompts:
            sys_prompts[h] = build_system_prompt(h, rules)

    async def translate_one(session: aiohttp.ClientSession, item: dict) -> dict:
        user_prompt = f"Translate the following SNOMED CT medical term from English to Estonian.\n\nHierarchy: {item['hierarchy']}\n\nEnglish: {item['en_term']}"
        payload = {
            "model": VLLM_MODEL,
            "messages": [
                {"role": "system", "content": sys_prompts[item["hierarchy"]]},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 256,
            "chat_template_kwargs": {"enable_thinking": False},
            **SAMPLING_PARAMS,
        }

        async with sem:
            try:
                async with session.post(
                    f"{VLLM_URL}/v1/chat/completions",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                translation = clean_translation(content)
                return {**item, "translation": translation}
            except Exception as e:
                logger.error("Failed for %s: %s", item["en_term"], e)
                return {**item, "translation": f"ERROR: {e}"}

    async with aiohttp.ClientSession() as session:
        tasks = [translate_one(session, item) for item in items]
        results = []
        # Process in chunks to show progress
        chunk_size = 500
        for i in range(0, len(tasks), chunk_size):
            chunk = tasks[i : i + chunk_size]
            chunk_results = await asyncio.gather(*chunk)
            results.extend(chunk_results)
            errors = sum(1 for r in chunk_results if r["translation"].startswith("ERROR"))
            logger.info("  Translated %d/%d (chunk errors: %d)", min(i + chunk_size, len(tasks)), len(tasks), errors)
        return results


def compute_embeddings_and_scores(results: list[dict]):
    """Compute EN↔Translation cosine using BGE-M3."""
    from FlagEmbedding import BGEM3FlagModel

    logger.info("Loading BGE-M3...")
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True, device="cuda")

    en_terms = [r["en_term"] for r in results]
    translations = [r["translation"] for r in results]
    et_refs = [r["et_primary"] for r in results]

    logger.info("Encoding %d strings (EN + translations + ET refs)...", len(en_terms) * 3)
    all_strings = en_terms + translations + et_refs
    vecs = model.encode(all_strings, batch_size=512, max_length=512)["dense_vecs"]

    n = len(results)
    en_vecs = vecs[:n]
    tr_vecs = vecs[n : 2 * n]
    et_vecs = vecs[2 * n :]

    for i, r in enumerate(results):
        en_n = np.linalg.norm(en_vecs[i]) + 1e-9
        tr_n = np.linalg.norm(tr_vecs[i]) + 1e-9
        et_n = np.linalg.norm(et_vecs[i]) + 1e-9
        r["en_tr_cos"] = float(np.dot(en_vecs[i], tr_vecs[i]) / (en_n * tr_n))
        r["tr_et_cos"] = float(np.dot(tr_vecs[i], et_vecs[i]) / (tr_n * et_n))
        # en_et_cosine already loaded from CSV

    return results


def save_results(results: list[dict]):
    """Save full results CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "translations.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "sctid", "en_term", "et_primary", "translation", "hierarchy",
            "en_et_cosine", "en_tr_cos", "tr_et_cos",
            "str_sim", "likely_latin", "has_rules",
        ])
        for r in results:
            has_rules = 1 if r.get("has_rules") else 0
            w.writerow([
                r["sctid"], r["en_term"], r["et_primary"], r["translation"],
                r["hierarchy"], f"{r['en_et_cosine']:.4f}",
                f"{r.get('en_tr_cos', 0):.4f}", f"{r.get('tr_et_cos', 0):.4f}",
                f"{r['str_sim']:.3f}", r["likely_latin"], has_rules,
            ])
    logger.info("Results saved to %s", out_path)


def generate_plots(results: list[dict]):
    """Generate comparison histograms."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    hierarchies_ordered = [
        "body structure", "specimen", "substance", "physical object", "person",
        "observable entity", "finding", "disorder", "morphologic abnormality",
        "procedure", "regime/therapy", "qualifier value", "event", "organism",
    ]
    hierarchies_ordered = [h for h in hierarchies_ordered if sum(1 for r in results if r["hierarchy"] == h) >= 10]

    bins = np.linspace(0, 1, 51)

    # ── Figure 1: Per-hierarchy, EN↔Official vs EN↔Translation ──
    fig, axes = plt.subplots(4, 4, figsize=(20, 16))
    axes = axes.flatten()

    for idx, h in enumerate(hierarchies_ordered):
        ax = axes[idx]
        group = [r for r in results if r["hierarchy"] == h]
        ref_cos = [r["en_et_cosine"] for r in group]
        tr_cos = [r["en_tr_cos"] for r in group]

        ax.hist(ref_cos, bins=bins, alpha=0.6, color="steelblue", label=f"Official ET ({len(ref_cos)})", edgecolor="white", linewidth=0.3)
        ax.hist(tr_cos, bins=bins, alpha=0.6, color="coral", label=f"Qwen 35B ({len(tr_cos)})", edgecolor="white", linewidth=0.3)

        ax.axvline(np.mean(ref_cos), color="steelblue", linestyle="--", linewidth=1.5)
        ax.axvline(np.mean(tr_cos), color="coral", linestyle="--", linewidth=1.5)

        has_rules = any(r.get("has_rules") for r in group)
        title_suffix = " [RULES]" if has_rules else ""
        ax.set_title(f"{h}{title_suffix}\n(n={len(group)}, off={np.mean(ref_cos):.3f}, qwen={np.mean(tr_cos):.3f})", fontsize=9)
        ax.set_xlim(0, 1.05)
        ax.legend(fontsize=7, loc="upper left")
        ax.set_xlabel("EN↔X cosine", fontsize=8)

    for idx in range(len(hierarchies_ordered), len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle("EN↔ET Cosine: Official Estonian vs Qwen 35B Translation\n(Blue=Official, Red=Qwen)", fontsize=14)
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "cosine_official_vs_qwen_by_hierarchy.png", dpi=150, bbox_inches="tight")
    logger.info("Saved cosine_official_vs_qwen_by_hierarchy.png")

    # ── Figure 2: Translation↔Reference cosine (actual quality) ──
    fig2, axes2 = plt.subplots(4, 4, figsize=(20, 16))
    axes2 = axes2.flatten()

    for idx, h in enumerate(hierarchies_ordered):
        ax = axes2[idx]
        group = [r for r in results if r["hierarchy"] == h]
        native = [r["tr_et_cos"] for r in group if not r["likely_latin"]]
        latin = [r["tr_et_cos"] for r in group if r["likely_latin"]]

        ax.hist(native, bins=bins, alpha=0.7, color="steelblue", label=f"Native ({len(native)})", edgecolor="white", linewidth=0.3)
        if latin:
            ax.hist(latin, bins=bins, alpha=0.7, color="coral", label=f"Latin ({len(latin)})", edgecolor="white", linewidth=0.3)

        all_cos = [r["tr_et_cos"] for r in group]
        has_rules = any(r.get("has_rules") for r in group)
        title_suffix = " [RULES]" if has_rules else ""
        ax.set_title(f"{h}{title_suffix}\n(n={len(group)}, mean={np.mean(all_cos):.3f})", fontsize=9)
        ax.set_xlim(0, 1.05)
        ax.legend(fontsize=7, loc="upper left")
        ax.set_xlabel("Translation↔Reference cosine", fontsize=8)

    for idx in range(len(hierarchies_ordered), len(axes2)):
        axes2[idx].set_visible(False)

    fig2.suptitle("Translation Quality: Qwen 35B Translation ↔ Official Estonian Reference\n(Higher = closer to official)", fontsize=14)
    plt.tight_layout()
    fig2.savefig(OUTPUT_DIR / "translation_quality_by_hierarchy.png", dpi=150, bbox_inches="tight")
    logger.info("Saved translation_quality_by_hierarchy.png")

    # ── Figure 3: Summary bar chart ──
    fig3, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6))

    h_labels = []
    en_et_means = []
    en_tr_means = []
    tr_et_means = []
    counts = []
    for h in hierarchies_ordered:
        group = [r for r in results if r["hierarchy"] == h]
        h_labels.append(h)
        en_et_means.append(np.mean([r["en_et_cosine"] for r in group]))
        en_tr_means.append(np.mean([r["en_tr_cos"] for r in group]))
        tr_et_means.append(np.mean([r["tr_et_cos"] for r in group]))
        counts.append(len(group))

    x = np.arange(len(h_labels))
    w = 0.35
    ax1.bar(x - w / 2, en_et_means, w, label="EN↔Official ET", color="steelblue", alpha=0.8)
    ax1.bar(x + w / 2, en_tr_means, w, label="EN↔Qwen Translation", color="coral", alpha=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(h_labels, rotation=45, ha="right", fontsize=8)
    ax1.set_ylabel("Mean Cosine Similarity")
    ax1.set_title("EN↔ET: Official vs Qwen Translation")
    ax1.legend()
    ax1.grid(axis="y", alpha=0.3)

    ax2.bar(x, tr_et_means, color="seagreen", alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(h_labels, rotation=45, ha="right", fontsize=8)
    ax2.set_ylabel("Mean Cosine Similarity")
    ax2.set_title("Translation Quality (Qwen↔Official ET)")
    ax2.grid(axis="y", alpha=0.3)
    for i, (v, c) in enumerate(zip(tr_et_means, counts)):
        ax2.text(i, v + 0.005, f"n={c}", ha="center", fontsize=7)

    plt.tight_layout()
    fig3.savefig(OUTPUT_DIR / "summary_comparison.png", dpi=150, bbox_inches="tight")
    logger.info("Saved summary_comparison.png")


async def main():
    global VLLM_URL, VLLM_MODEL, OUTPUT_DIR
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hierarchy", type=str, default=None, help="Translate only this hierarchy")
    parser.add_argument("--skip-translate", action="store_true", help="Skip translation, just re-plot from saved CSV")
    parser.add_argument("--from-raw", action="store_true", help="Load raw translations, compute embeddings and plots")
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--vllm-url", type=str, default=VLLM_URL, help="vLLM base URL")
    parser.add_argument("--model", type=str, default=VLLM_MODEL, help="Model name for vLLM")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory override")
    parser.add_argument("--label", type=str, default=None, help="Label for plot titles")
    args = parser.parse_args()

    VLLM_URL = args.vllm_url
    VLLM_MODEL = args.model
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir)

    if args.from_raw:
        logger.info("Loading raw translations...")
        results = []
        with (OUTPUT_DIR / "translations_raw.csv").open() as f:
            for r in csv.DictReader(f):
                r["en_et_cosine"] = float(r["en_et_cosine"])
                r["str_sim"] = float(r["str_sim"])
                r["likely_latin"] = int(r["likely_latin"])
                r["has_rules"] = int(r["has_rules"])
                results.append(r)
        logger.info("Loaded %d raw translations, computing embeddings...", len(results))
        results = compute_embeddings_and_scores(results)
        save_results(results)
        generate_plots(results)
        return

    if args.skip_translate:
        logger.info("Loading saved results...")
        results = []
        with (OUTPUT_DIR / "translations.csv").open() as f:
            for r in csv.DictReader(f):
                r["en_et_cosine"] = float(r["en_et_cosine"])
                r["en_tr_cos"] = float(r["en_tr_cos"])
                r["tr_et_cos"] = float(r["tr_et_cos"])
                r["str_sim"] = float(r["str_sim"])
                r["likely_latin"] = int(r["likely_latin"])
                r["has_rules"] = int(r["has_rules"])
                results.append(r)
        logger.info("Loaded %d results", len(results))
        generate_plots(results)
        return

    items = load_items()
    rules = load_rules()
    logger.info("Loaded %d items, rules for: %s", len(items), list(rules.keys()))

    if args.hierarchy:
        items = [i for i in items if i["hierarchy"] == args.hierarchy]
        logger.info("Filtered to %d items for hierarchy '%s'", len(items), args.hierarchy)

    # Tag items with whether rules are applied
    for item in items:
        item["has_rules"] = item["hierarchy"] in rules

    logger.info("Translating %d terms...", len(items))
    results = await translate_batch(items, rules, concurrency=args.concurrency)

    errors = sum(1 for r in results if r["translation"].startswith("ERROR"))
    logger.info("Translation complete: %d errors out of %d", errors, len(results))

    # Save raw translations immediately so they survive if embedding crashes
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUTPUT_DIR / "translations_raw.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sctid", "en_term", "et_primary", "translation", "hierarchy",
                     "en_et_cosine", "str_sim", "likely_latin", "has_rules"])
        for r in results:
            w.writerow([r["sctid"], r["en_term"], r["et_primary"], r["translation"],
                        r["hierarchy"], f"{r['en_et_cosine']:.4f}", f"{r['str_sim']:.3f}",
                        r["likely_latin"], int(r.get("has_rules", 0))])
    logger.info("Raw translations saved to %s", raw_path)

    results = compute_embeddings_and_scores(results)
    save_results(results)
    generate_plots(results)

    # Print summary table
    hierarchies = sorted(set(r["hierarchy"] for r in results))
    logger.info("\n%-35s %6s %8s %8s %8s %6s", "Hierarchy", "Count", "EN↔Off", "EN↔Qwen", "Qwen↔Off", "Rules")
    logger.info("-" * 75)
    for h in hierarchies:
        group = [r for r in results if r["hierarchy"] == h]
        has_rules = "YES" if any(r.get("has_rules") for r in group) else ""
        logger.info("%-35s %6d %8.3f %8.3f %8.3f %6s",
                     h, len(group),
                     np.mean([r["en_et_cosine"] for r in group]),
                     np.mean([r["en_tr_cos"] for r in group]),
                     np.mean([r["tr_et_cos"] for r in group]),
                     has_rules)


if __name__ == "__main__":
    asyncio.run(main())
