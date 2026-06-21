#!/usr/bin/env python
"""
Translate a sample subset of SNOMED CT concepts from English to Estonian
using Qwen 3.5 35B served via vLLM (OpenAI-compatible API).

Uses the full pipeline context from the tools server: SNOMED graph,
paired translations, and style guide.

Usage:
    # Start the model server and tools server first:
    docker compose up -d vllm qdrant
    python agent/tools.py  # port 8008

    # Run translation:
    python scripts/translate_sample_qwen.py

    # Custom input/output:
    python scripts/translate_sample_qwen.py \
        --input data/evals/sample/100_concepts.csv \
        --output data/evals/sample/100_translations_qwen.csv
"""
import argparse
import csv
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("translate_sample_qwen")

DEFAULT_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8000")
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4")
TOOLS_SERVER_URL = "http://localhost:8008"
DEFAULT_INPUT = "data/evals/sample/100_concepts.csv"
DEFAULT_OUTPUT = "data/evals/sample/100_translations_qwen.csv"

SYSTEM_PROMPT = """\
You are a medical terminology translator specialising in English to Estonian translation \
of SNOMED CT clinical terms. Return ONLY the Estonian translation — no explanation, \
no quotes, no extra text, no thinking. If the term is a well-known international word \
(e.g. a drug name), use the standard Estonian phonetic adaptation."""


def wait_for_server(base_url: str, timeout: int = 600) -> None:
    """Block until the vLLM server health endpoint responds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{base_url}/v1/models", timeout=5)
            if resp.status_code == 200:
                logger.info("vLLM server is ready")
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise RuntimeError(f"vLLM server at {base_url} not ready within {timeout}s")


def get_pipeline_context(sctid: int, preferred_term: str, hierarchy: str) -> dict:
    """Fetch full pipeline context from the tools server."""
    context = {
        "snomed": {},
        "paired_translations": [],
        "style_guide": {},
    }
    try:
        resp = requests.get(
            f"{TOOLS_SERVER_URL}/snomed_graph",
            params={"sctid": sctid},
            timeout=10,
        )
        if resp.status_code == 200:
            context["snomed"] = resp.json()
    except Exception as exc:
        logger.warning("SNOMED graph lookup failed for %d: %s", sctid, exc)

    try:
        resp = requests.get(
            f"{TOOLS_SERVER_URL}/paired_translations_en_to_ee",
            params={"preferred_term": preferred_term, "max_results": 3},
            timeout=10,
        )
        if resp.status_code == 200:
            context["paired_translations"] = resp.json()
    except Exception as exc:
        logger.warning("Paired translations lookup failed: %s", exc)

    try:
        resp = requests.get(
            f"{TOOLS_SERVER_URL}/style_guide",
            params={"hierarchy": hierarchy},
            timeout=10,
        )
        if resp.status_code == 200:
            context["style_guide"] = resp.json()
    except Exception as exc:
        logger.warning("Style guide lookup failed: %s", exc)

    return context


def format_context_for_prompt(ctx: dict) -> str:
    """Format pipeline context into a prompt string."""
    parts = []

    snomed = ctx.get("snomed", {})
    if snomed:
        if snomed.get("hierarchy"):
            parts.append(f"Hierarchy: {snomed['hierarchy']}")
        if snomed.get("parent_concepts"):
            parts.append(f"Parent concepts: {', '.join(snomed['parent_concepts'][:5])}")
        if snomed.get("synonyms"):
            parts.append(f"Synonyms: {', '.join(snomed['synonyms'][:5])}")
        if snomed.get("related_concepts"):
            parts.append(f"Related concepts: {', '.join(snomed['related_concepts'][:5])}")

    paired = ctx.get("paired_translations", [])
    if paired:
        pairs_str = "\n".join(
            f"  {p['en']} -> {p['ee']}" for p in paired if len(p.get("en", "")) < 100
        )
        if pairs_str:
            parts.append(f"Paired translation hints:\n{pairs_str}")

    style = ctx.get("style_guide", {})
    if style.get("general"):
        parts.append(f"General style guidelines:\n{style['general'][:500]}")
    if style.get("specific") and style["specific"] != "No specific guidance required.":
        parts.append(f"Hierarchy-specific style guidelines:\n{style['specific'][:500]}")

    return "\n\n".join(parts)


def translate_term(
    base_url: str,
    model: str,
    english_term: str,
    context: str = "",
    max_tokens: int = 256,
    temperature: float = 0.1,
) -> str:
    """Translate an English term to Estonian using Qwen via vLLM."""
    if context:
        user_content = (
            f"Translate the following SNOMED CT medical term from English to Estonian.\n\n"
            f"# Context\n{context}\n\n"
            f"English: {english_term}\n"
            f"Estonian:"
        )
    else:
        user_content = (
            f"Translate the following SNOMED CT medical term from English to Estonian.\n"
            f"English: {english_term}\n"
            f"Estonian:"
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stop": ["\n\n"],
        "chat_template_kwargs": {"enable_thinking": False},
    }

    resp = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content", "")
    # Strip any thinking blocks that might leak through
    if "<think>" in content:
        content = content.split("</think>")[-1]
    return content.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Translate SNOMED CT concepts EN->ET using Qwen 3.5 35B via vLLM"
    )
    parser.add_argument(
        "--input", type=Path, default=Path(DEFAULT_INPUT),
        help="Input CSV with columns: sctid, preferred_term",
    )
    parser.add_argument(
        "--output", type=Path, default=Path(DEFAULT_OUTPUT),
        help="Output CSV with translations",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument(
        "--wait-for-server", type=int, default=600, metavar="SECONDS",
        help="Wait up to N seconds for the vLLM server to become healthy",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    wait_for_server(args.base_url, args.wait_for_server)

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    logger.info("Translating %d concepts with Qwen 3.5 35B", len(rows))
    results = []

    for row in rows:
        sctid = row["sctid"]
        preferred_term = row["preferred_term"]
        hierarchy = row.get("hierarchy", "")

        ctx = get_pipeline_context(int(sctid), preferred_term, hierarchy)
        context_str = format_context_for_prompt(ctx)

        logger.info("Translating [%s] %s", sctid, preferred_term)
        try:
            translation = translate_term(
                base_url=args.base_url,
                model=args.model,
                english_term=preferred_term,
                context=context_str,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
        except Exception as exc:
            logger.error("Failed to translate %s: %s", preferred_term, exc)
            translation = f"ERROR: {exc}"

        results.append({
            "sctid": sctid,
            "preferred_term": preferred_term,
            "hierarchy": hierarchy,
            "translation": translation,
            "context_used": "full_pipeline",
        })
        logger.info("  -> %s", translation)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["sctid", "preferred_term", "hierarchy", "translation", "context_used"]
        )
        writer.writeheader()
        writer.writerows(results)

    logger.info("Wrote %d translations to %s", len(results), args.output)


if __name__ == "__main__":
    main()
