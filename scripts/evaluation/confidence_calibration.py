#!/usr/bin/env python
"""
Test whether Qwen 35B can self-assess translation confidence, and how well
that confidence correlates with actual translation quality (composite score).

Translates terms asking for a 1-5 confidence rating alongside the translation,
then compares confidence vs composite score to find a useful cutoff for
deciding when to trigger a RAG enrichment loop.

Usage:
    CUDA_VISIBLE_DEVICES="" .venv/bin/python scripts/confidence_calibration.py
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
import sacrebleu
from FlagEmbedding import BGEM3FlagModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("confidence_calibration")

VLLM_URL = "http://localhost:8000"
VLLM_MODEL = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
EVAL_PATH = Path("data/evals/sample/concepts/500_eval_concepts.csv")
OUT_DIR = Path("data/evals/sample/confidence_calibration")

PROMPTS = {
    "original": """\
You are a medical terminology translator for SNOMED CT (English → Estonian).

Translate the term and rate your confidence in the translation.

Output EXACTLY two lines, nothing else:
Translation: <Estonian translation>
Confidence: <1-5>

Confidence scale:
1 = Very uncertain — guessing, unfamiliar term
2 = Low confidence — partially familiar, unsure about specific Estonian medical term
3 = Moderate — know the general meaning but not certain of the exact Estonian medical term
4 = High confidence — fairly certain this is the correct Estonian medical term
5 = Very high confidence — certain this is the standard Estonian medical term""",

    "checklist": """\
You are a medical terminology translator for SNOMED CT (English → Estonian).

Translate the term, then answer these three YES/NO questions honestly:
1. Do I know the SPECIFIC Estonian medical term (not a literal translation or Latin borrowing)?
2. Would an Estonian medical terminologist accept this without corrections?
3. Am I translating from knowledge, or constructing a plausible guess?

Output EXACTLY this format, nothing else:
Translation: <Estonian translation>
Know specific term: <YES/NO>
Terminologist would accept: <YES/NO>
From knowledge not guessing: <YES/NO>
Confidence: <1-5>

Score 5 only if all three are YES. Score 1-2 if any answer is NO and you're uncertain.""",

    "premortem": """\
You are a medical terminology translator for SNOMED CT (English → Estonian).

Translate the term, then imagine an Estonian medical terminology expert reviewing your translation. What would they likely say is wrong with it?

Output EXACTLY this format, nothing else:
Translation: <Estonian translation>
Likely criticism: <what an expert would correct, or "None - this is the standard term">
Confidence: <1-5>

Be HARSH with confidence. Most translations have issues. Score 5 only if you are certain the expert would have zero corrections. Score 3-4 if there's any chance you used a Latin borrowing where an Estonian native term exists, or constructed a compound word that might not be standard.""",

    "decompose": """\
You are a medical terminology translator for SNOMED CT (English → Estonian).

Translate the term. Then for EACH word in your translation, rate whether you are certain it is the correct Estonian medical term.

Output EXACTLY this format, nothing else:
Translation: <Estonian translation>
Word certainty: <word1>=<sure/unsure>, <word2>=<sure/unsure>, ...
Confidence: <1-5>

Score 5 only if ALL words are "sure". Score 1 if more than half are "unsure". Be honest — if you're using a Latin/Greek borrowing because you don't know the Estonian native term, mark it "unsure".""",
}

SAMPLING_PARAMS = {"temperature": 0, "top_p": 1.0, "repetition_penalty": 1.0}


def load_eval_set() -> list[dict]:
    """Load the 500-concept eval set."""
    with EVAL_PATH.open() as f:
        reader = csv.DictReader(f)
        items = []
        for r in reader:
            items.append({
                "sctid": r["sctid"],
                "preferred_term": r["preferred_term"],
                "hierarchy": r["hierarchy"],
                "ee_reference": r["ee_reference"],
                "ee_all": r["ee_all"].split("|"),
            })
    return items


def build_user_prompt(item: dict) -> str:
    sections = [f"Translate the following SNOMED CT medical term from English to Estonian."]
    if item.get("hierarchy"):
        sections.append(f"Hierarchy: {item['hierarchy']}")
    sections.append(f"English: {item['preferred_term']}")
    return "\n\n".join(sections)


def parse_response(text: str) -> tuple[str, int]:
    """Parse translation and confidence from model output."""
    # Strip think tags
    if "<think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    translation = ""
    confidence = 3  # default

    for line in text.strip().split("\n"):
        line = line.strip()
        if line.lower().startswith("translation:"):
            translation = line.split(":", 1)[1].strip()
        elif line.lower().startswith("confidence:"):
            try:
                confidence = int(line.split(":", 1)[1].strip().split()[0])
                confidence = max(1, min(5, confidence))
            except (ValueError, IndexError):
                pass

    # Fallback: if no "Translation:" prefix, take the first non-empty line
    if not translation:
        for line in text.strip().split("\n"):
            line = line.strip()
            if line and not line.lower().startswith("confidence"):
                translation = line
                break

    return translation, confidence


async def translate_batch(items: list[dict], system_prompt: str, concurrency: int = 16) -> list[dict]:
    """Translate all items with confidence rating."""
    sem = asyncio.Semaphore(concurrency)

    async def translate_one(session: aiohttp.ClientSession, item: dict) -> dict:
        user_prompt = build_user_prompt(item)
        payload = {
            "model": VLLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 512,
            **SAMPLING_PARAMS,
        }
        # Qwen models need explicit thinking mode control
        if "qwen" in VLLM_MODEL.lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}

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
                translation, confidence = parse_response(content)
                return {**item, "translation": translation, "confidence": confidence, "raw": content}
            except Exception as e:
                logger.error("Failed for %s: %s", item["preferred_term"], e)
                return {**item, "translation": f"ERROR: {e}", "confidence": 0, "raw": ""}

    async with aiohttp.ClientSession() as session:
        tasks = [translate_one(session, item) for item in items]
        return await asyncio.gather(*tasks)


def score_translations(results: list[dict], bgem3: BGEM3FlagModel) -> list[dict]:
    """Score with chrF + BGE-M3 cosine + exact match."""
    candidates = [r["translation"] for r in results]
    ref_groups = [r["ee_all"] for r in results]

    for r in results:
        cand = r["translation"]
        refs = r["ee_all"]
        if cand.startswith("ERROR"):
            r["chrf"] = 0.0
            r["exact"] = 0.0
            r["cosine"] = 0.0
            r["composite"] = 0.0
            continue
        r["chrf"] = max(sacrebleu.sentence_chrf(cand, [ref]).score for ref in refs)
        r["exact"] = 1.0 if cand.lower() in {ref.lower() for ref in refs} else 0.0

    # BGE-M3 cosine (batch)
    all_strings = list(candidates)
    ref_offsets = []
    for refs in ref_groups:
        ref_offsets.append((len(all_strings), len(refs)))
        all_strings.extend(refs)

    embeddings = bgem3.encode(all_strings, batch_size=256, max_length=512)["dense_vecs"]

    for i, (offset, count) in enumerate(ref_offsets):
        if results[i]["translation"].startswith("ERROR"):
            continue
        cand_vec = embeddings[i]
        best_sim = 0.0
        for j in range(offset, offset + count):
            ref_vec = embeddings[j]
            sim = float(np.dot(cand_vec, ref_vec) / (np.linalg.norm(cand_vec) * np.linalg.norm(ref_vec) + 1e-9))
            best_sim = max(best_sim, sim)
        results[i]["cosine"] = best_sim

    for r in results:
        if not r["translation"].startswith("ERROR"):
            r["composite"] = 0.5 * (r["chrf"] / 100) + 0.3 * r["cosine"] + 0.2 * r["exact"]

    return results


def analyse_calibration(results: list[dict], prompt_name: str = "default"):
    """Analyse correlation between confidence and actual quality."""
    valid = [r for r in results if not r["translation"].startswith("ERROR") and r["confidence"] > 0]

    logger.info("\n" + "=" * 70)
    logger.info("CONFIDENCE CALIBRATION: %s (%d valid translations)", prompt_name, len(valid))
    logger.info("=" * 70)

    # Per-confidence-level stats
    logger.info("\n%-12s %5s %8s %8s %8s %8s", "Confidence", "Count", "Comp.", "chrF", "Cosine", "Exact%")
    logger.info("-" * 60)
    for conf in range(1, 6):
        group = [r for r in valid if r["confidence"] == conf]
        if not group:
            logger.info("%-12d %5d %8s %8s %8s %8s", conf, 0, "-", "-", "-", "-")
            continue
        mean_comp = np.mean([r["composite"] for r in group])
        mean_chrf = np.mean([r["chrf"] for r in group])
        mean_cos = np.mean([r["cosine"] for r in group])
        exact_pct = np.mean([r["exact"] for r in group]) * 100
        logger.info("%-12d %5d %8.3f %8.1f %8.3f %8.1f%%", conf, len(group), mean_comp, mean_chrf, mean_cos, exact_pct)

    # Overall correlation
    confidences = np.array([r["confidence"] for r in valid])
    composites = np.array([r["composite"] for r in valid])
    correlation = np.corrcoef(confidences, composites)[0, 1]
    logger.info("\nPearson correlation (confidence vs composite): %.3f", correlation)

    # Per-hierarchy breakdown
    hierarchies = sorted(set(r["hierarchy"] for r in valid))
    logger.info("\n%-30s %5s %8s %8s", "Hierarchy", "Count", "Mean Conf", "Mean Comp")
    logger.info("-" * 55)
    for h in hierarchies:
        group = [r for r in valid if r["hierarchy"] == h]
        logger.info("%-30s %5d %8.1f %8.3f", h, len(group),
                     np.mean([r["confidence"] for r in group]),
                     np.mean([r["composite"] for r in group]))

    # Cutoff analysis: for each confidence threshold, what % would go to RAG
    # and what's the quality of those that don't
    logger.info("\n%-10s %8s %8s %8s %8s", "Cutoff <=", "To RAG", "RAG Comp", "Keep", "Keep Comp")
    logger.info("-" * 50)
    for cutoff in range(1, 5):
        rag = [r for r in valid if r["confidence"] <= cutoff]
        keep = [r for r in valid if r["confidence"] > cutoff]
        rag_comp = np.mean([r["composite"] for r in rag]) if rag else 0
        keep_comp = np.mean([r["composite"] for r in keep]) if keep else 0
        logger.info("%-10d %7d %8.3f %7d %8.3f",
                     cutoff, len(rag), rag_comp, len(keep), keep_comp)

    # Show worst translations at high confidence (miscalibrated)
    logger.info("\n--- Worst translations at confidence 4-5 (miscalibrated) ---")
    high_conf_bad = sorted(
        [r for r in valid if r["confidence"] >= 4],
        key=lambda r: r["composite"]
    )[:10]
    for r in high_conf_bad:
        logger.info("  conf=%d comp=%.3f | %s → %s (ref: %s)",
                     r["confidence"], r["composite"],
                     r["preferred_term"], r["translation"], r["ee_reference"])

    # Show best translations at low confidence
    logger.info("\n--- Best translations at confidence 1-2 (unnecessarily cautious) ---")
    low_conf_good = sorted(
        [r for r in valid if r["confidence"] <= 2],
        key=lambda r: -r["composite"]
    )[:10]
    for r in low_conf_good:
        logger.info("  conf=%d comp=%.3f | %s → %s (ref: %s)",
                     r["confidence"], r["composite"],
                     r["preferred_term"], r["translation"], r["ee_reference"])

    # Save results to CSV
    out_path = OUT_DIR / f"500_confidence_{prompt_name}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sctid", "preferred_term", "hierarchy", "translation",
                          "confidence", "ee_reference", "composite", "chrf", "cosine", "exact", "raw"])
        for r in results:
            writer.writerow([
                r["sctid"], r["preferred_term"], r["hierarchy"], r["translation"],
                r["confidence"], r["ee_reference"], f"{r.get('composite', 0):.3f}",
                f"{r.get('chrf', 0):.1f}", f"{r.get('cosine', 0):.3f}", r.get("exact", 0),
                r.get("raw", ""),
            ])
    logger.info("\nResults saved to %s", out_path)


async def main():
    global VLLM_URL, VLLM_MODEL, OUT_DIR
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, default="all",
                        choices=list(PROMPTS.keys()) + ["all"])
    parser.add_argument("--model", type=str, default=VLLM_MODEL,
                        help="Model name for vLLM (as registered in the server)")
    parser.add_argument("--vllm-url", type=str, default=VLLM_URL,
                        help="vLLM server URL")
    parser.add_argument("--model-label", type=str, default=None,
                        help="Short label for output filenames (default: derived from model name)")
    parser.add_argument("--concurrency", type=int, default=16,
                        help="Max concurrent translation requests")
    args = parser.parse_args()

    VLLM_URL = args.vllm_url
    VLLM_MODEL = args.model

    # Derive a short label for output dirs/files
    model_label = args.model_label or args.model.split("/")[-1].lower().replace(" ", "_")
    OUT_DIR = Path(f"data/evals/sample/confidence_calibration/{model_label}")

    logger.info("Model: %s at %s", VLLM_MODEL, VLLM_URL)
    logger.info("Output dir: %s", OUT_DIR)

    logger.info("Loading eval set...")
    items = load_eval_set()
    logger.info("Loaded %d concepts", len(items))

    logger.info("Loading BGE-M3 (CPU)...")
    bgem3 = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, device="cpu")

    prompt_names = list(PROMPTS.keys()) if args.prompt == "all" else [args.prompt]

    for name in prompt_names:
        logger.info("\n" + "#" * 70)
        logger.info("PROMPT VARIANT: %s", name)
        logger.info("#" * 70)

        results = await translate_batch(items, PROMPTS[name], concurrency=args.concurrency)

        errors = sum(1 for r in results if r["translation"].startswith("ERROR"))
        logger.info("Translations complete (%d errors)", errors)

        logger.info("Scoring translations...")
        results = score_translations(results, bgem3)

        analyse_calibration(results, prompt_name=name)


if __name__ == "__main__":
    asyncio.run(main())
