#!/usr/bin/env python
"""
Translate a sample subset of SNOMED CT concepts from English to Estonian
using Claude Sonnet via the Claude Agent SDK.

Uses the full pipeline context from the tools server: SNOMED graph,
paired translations, and style guide.

Usage:
    # Start tools server first:
    docker compose up -d qdrant
    python agent/tools.py  # port 8008

    # Run translation:
    python scripts/translate_sample_claude.py

    # Custom input/output:
    python scripts/translate_sample_claude.py \
        --input data/evals/sample/sample_concepts.csv \
        --output data/evals/sample/translations_claude.csv
"""
import argparse
import asyncio
import csv
import logging
import os
from pathlib import Path

import requests
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("translate_sample_claude")

TOOLS_SERVER_URL = "http://localhost:8008"
DEFAULT_INPUT = "data/evals/sample/sample_concepts.csv"
DEFAULT_OUTPUT = "data/evals/sample/translations_claude.csv"

SYSTEM_PROMPT = """\
You are a medical terminology translator specialising in English to Estonian translation \
of SNOMED CT clinical terms. Return ONLY the Estonian translation — no explanation, \
no quotes, no extra text. If the term is a well-known international word (e.g. a drug \
name), use the standard Estonian phonetic adaptation."""


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


def format_context_for_prompt(ctx: dict) -> str:
    """Format pipeline context into a prompt string for Claude."""
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


async def translate_term(english_term: str, context: str = "") -> str:
    """Translate an English term to Estonian using Claude Sonnet via the Agent SDK."""
    if context:
        prompt = (
            f"Translate the following SNOMED CT medical term from English to Estonian.\n\n"
            f"# Context\n{context}\n\n"
            f"English: {english_term}\n"
            f"Estonian:"
        )
    else:
        prompt = (
            f"Translate the following SNOMED CT medical term from English to Estonian.\n"
            f"English: {english_term}\n"
            f"Estonian:"
        )

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-6",
        system_prompt=SYSTEM_PROMPT,
        max_turns=1,
        permission_mode="bypassPermissions",
        tools=[],
        allowed_tools=[],
    )

    result_text = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            if message.result:
                result_text = message.result.strip()
        elif isinstance(message, AssistantMessage) and not result_text:
            for block in message.content:
                if isinstance(block, TextBlock):
                    result_text = block.text.strip()

    translation = result_text
    # Clean up common artefacts
    for prefix in ["Estonian:", "Estonian: "]:
        if translation.startswith(prefix):
            translation = translation[len(prefix):].strip()
    return translation


async def main_async(args: argparse.Namespace) -> None:
    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    logger.info("Translating %d concepts with Claude Sonnet", len(rows))
    results = []

    for row in rows:
        sctid = row["sctid"]
        preferred_term = row["preferred_term"]
        hierarchy = row.get("hierarchy", "")

        ctx = get_pipeline_context(int(sctid), preferred_term, hierarchy)
        context_str = format_context_for_prompt(ctx)

        logger.info("Translating [%s] %s", sctid, preferred_term)
        try:
            translation = await translate_term(
                english_term=preferred_term,
                context=context_str,
            )
        except Exception as exc:
            logger.error("Failed to translate %s: %s", preferred_term, exc)
            translation = f"ERROR: {exc}"

        results.append({
            "sctid": sctid,
            "preferred_term": preferred_term,
            "hierarchy": hierarchy,
            "translation": translation,
            "context_used": context_str,
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


def main():
    parser = argparse.ArgumentParser(
        description="Translate SNOMED CT concepts EN->ET using Claude Sonnet via Agent SDK"
    )
    parser.add_argument(
        "--input", type=Path, default=Path(DEFAULT_INPUT),
        help="Input CSV with columns: sctid, preferred_term",
    )
    parser.add_argument(
        "--output", type=Path, default=Path(DEFAULT_OUTPUT),
        help="Output CSV with translations",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
