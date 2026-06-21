#!/usr/bin/env python
"""
Translate a sample subset of SNOMED CT concepts from English to Estonian
using the TranslateGemma model served via llama.cpp (OpenAI-compatible API).

Uses the full pipeline context from the tools server: SNOMED graph,
paired translations, and style guide.

Usage:
    # Start the model server and tools server first:
    docker compose up -d llamacpp qdrant
    python agent/tools.py  # port 8008

    # Run translation:
    python scripts/translate_sample.py

    # With custom options:
    python scripts/translate_sample.py \
        --input data/evals/sample/sample_concepts.csv \
        --output data/evals/sample/translations_gemma.csv \
        --base-url http://localhost:8081
"""
import argparse
import csv
import logging
import time
from pathlib import Path

import requests

from translategemma_prompt import build_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("translate_sample")

DEFAULT_BASE_URL = "http://localhost:8081"
TOOLS_SERVER_URL = "http://localhost:8008"
DEFAULT_INPUT = "data/evals/sample/sample_concepts.csv"
DEFAULT_OUTPUT = "data/evals/sample/translations_gemma.csv"


def wait_for_server(base_url: str, timeout: int = 120) -> None:
    """Block until the llama.cpp server health endpoint responds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=5)
            if resp.status_code == 200:
                logger.info("Model server is ready")
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)
    raise RuntimeError(f"Model server at {base_url} not ready within {timeout}s")


def get_pipeline_context(sctid: int, preferred_term: str, hierarchy: str) -> dict:
    """Fetch full pipeline context from the tools server."""
    context = {
        "snomed": {},
        "paired_translations": [],
        "style_guide": {},
    }

    # 1. SNOMED graph context
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

    # 2. Paired translations (EN->EE)
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

    # 3. Style guide
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


def translate_term(
    base_url: str,
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.1,
) -> str:
    """Send the prompt to TranslateGemma and return the completion."""
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stop": ["\n", "<end_of_turn>", "<|im_end|>"],
    }

    resp = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content", "")
    return content.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Translate SNOMED CT concepts EN->ET using TranslateGemma via llama.cpp"
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
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument(
        "--wait-for-server", type=int, default=60, metavar="SECONDS",
        help="Wait up to N seconds for the model server to become healthy",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    wait_for_server(args.base_url, args.wait_for_server)

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    logger.info("Translating %d concepts", len(rows))
    results = []

    for row in rows:
        sctid = row["sctid"]
        preferred_term = row["preferred_term"]
        hierarchy = row.get("hierarchy", "")

        ctx = get_pipeline_context(int(sctid), preferred_term, hierarchy)
        snomed = ctx.get("snomed", {})
        style = ctx.get("style_guide", {})

        prompt = build_prompt(
            english_term=preferred_term,
            hierarchy=hierarchy,
            synonyms=snomed.get("synonyms"),
            parent_concepts=snomed.get("parent_concepts"),
            related_concepts=snomed.get("related_concepts"),
            paired_translations=ctx.get("paired_translations"),
            style_guide_specific=style.get("specific", ""),
        )

        logger.info("Translating [%s] %s", sctid, preferred_term)
        try:
            translation = translate_term(
                base_url=args.base_url,
                prompt=prompt,
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
