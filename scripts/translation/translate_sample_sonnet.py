#!/usr/bin/env python
"""
Translate SNOMED CT concepts EN→ET using Claude Sonnet via Claude Agent SDK.
Uses the same prompt structure as the Qwen 35B single-step translation
for a fair comparison. Authenticates through Claude Code (no API key needed).

Usage:
    python scripts/translate_sample_sonnet.py \
        --input data/evals/sample/500_eval_concepts.csv \
        --output data/evals/sample/500_translations_sonnet.csv

    # With forced enrichment + reflection step:
    python scripts/translate_sample_sonnet.py --force-reflection \
        --output data/evals/sample/500_translations_sonnet_reflect.csv
"""
import argparse
import asyncio
import csv
import importlib
import logging
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("translate_sonnet")

TOOLS_SERVER = "http://localhost:8008"


REFLECTION_SYSTEM = """\
You are a medical terminology translator for SNOMED CT (English → Estonian).
You are reviewing and improving an initial translation using additional sources.

STRICT RULES:
1. Output ONLY the Estonian translation — one term, nothing else.
2. Do NOT add explanations, alternatives, qualifiers, or surrounding context.
3. Use clinical/medical register. Always prefer the precise medical or \
histological term over a colloquial or general-language synonym.
4. If the initial translation is already correct, return it unchanged.
5. Start the translation with an uppercase letter."""


REFLECTION_USER = """\
An initial translation of the SNOMED CT term '{preferred_term}' produced: '{estonian_term}'.

Review this translation using the following additional Estonian-language sources:

# Source 1: Estonian clinical dictionary (Sõnaveeb)
{dictionary_hints}

# Source 2: Passages from Estonian medical documents
{extracts}

# Source 3: EE→EN paired translations
{ee_to_en_paired_translations}

# Style guidelines
{style_guidelines}

Based on these sources, provide the best Estonian translation of '{preferred_term}'.
If the initial translation is already correct, return it unchanged.
Respond with ONLY the Estonian translation (one term, no extras).
Estonian:"""


def get_pipeline_context(sctid: int, preferred_term: str, hierarchy: str) -> dict:
    """Fetch context from tools server."""
    ctx = {"snomed": {}, "paired_translations": [], "style_guide": {}}
    try:
        r = requests.get(f"{TOOLS_SERVER}/snomed_graph", params={"sctid": sctid}, timeout=10)
        if r.ok:
            ctx["snomed"] = r.json()
    except Exception:
        pass

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/paired_translations_en_to_ee",
            params={"preferred_term": preferred_term, "max_results": 3},
            timeout=10,
        )
        if r.ok:
            ctx["paired_translations"] = r.json()
    except Exception:
        pass

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/style_guide",
            params={"hierarchy": hierarchy},
            timeout=10,
        )
        if r.ok:
            ctx["style_guide"] = r.json()
    except Exception:
        pass

    return ctx


def get_enrichment(estonian_term: str) -> dict:
    """Fetch enrichment sources using the initial Estonian translation."""
    enrichment = {"dictionary": [], "extracts": [], "ee_to_en_pairs": []}

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/sonaveeb",
            params={"estonian_term": estonian_term, "max_results": 3},
            timeout=10,
        )
        if r.ok:
            enrichment["dictionary"] = r.json()
    except Exception as e:
        logger.debug("Sonaveeb failed: %s", e)

    for source in ["eesti_arst", "kliinikum", "haiglateliit"]:
        try:
            r = requests.get(
                f"{TOOLS_SERVER}/{source}",
                params={"estonian_term": estonian_term, "max_results": 3},
                timeout=10,
            )
            if r.ok:
                enrichment["extracts"].extend(r.json())
        except Exception as e:
            logger.debug("%s failed: %s", source, e)

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/paired_translations_ee_to_en",
            params={"preferred_term": estonian_term, "max_results": 3},
            timeout=10,
        )
        if r.ok:
            enrichment["ee_to_en_pairs"] = r.json()
    except Exception as e:
        logger.debug("EE→EN pairs failed: %s", e)

    return enrichment


def render_paired_translations(pairs: list) -> str:
    if not pairs:
        return "No paired translations available."
    md = "|Estonian|English|\n|---|---|\n"
    for p in pairs:
        if p and isinstance(p, dict):
            md += f"|{p.get('ee', '')}|{p.get('en', '')}|\n"
    return md


async def sdk_query(prompt: str, system_prompt: str, model: str) -> str:
    """Single-turn query via Claude Agent SDK."""
    from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

    result = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            allowed_tools=[],
            max_turns=1,
        ),
    ):
        if isinstance(message, ResultMessage):
            result = message.result.strip()
    return result


async def translate_one(
    sem: asyncio.Semaphore,
    prompt_mod,
    model: str,
    row: dict,
    force_reflection: bool,
) -> dict:
    """Translate a single concept, optionally with enrichment + reflection."""
    sctid = int(row["sctid"])
    preferred_term = row["preferred_term"]
    hierarchy = row.get("hierarchy", "")

    ctx = get_pipeline_context(sctid, preferred_term, hierarchy)
    snomed = ctx["snomed"]

    user_prompt = prompt_mod.build_user_prompt(
        english_term=preferred_term,
        hierarchy=snomed.get("hierarchy", hierarchy),
        synonyms=snomed.get("synonyms"),
        parent_concepts=snomed.get("parent_concepts"),
        related_concepts=snomed.get("related_concepts"),
        paired_translations=ctx["paired_translations"],
        style_guide_general=ctx["style_guide"].get("general", ""),
        style_guide_specific=ctx["style_guide"].get("specific", ""),
    )
    system_prompt = prompt_mod.build_system_prompt()

    async with sem:
        logger.info("Translating [%s] %s", sctid, preferred_term)
        try:
            # Step 1: Initial translation
            initial = await sdk_query(user_prompt, system_prompt, model)
            logger.info("  [%s] initial -> %s", sctid, initial)

            translation = initial
            context_used = "full_pipeline"

            # Step 2: Forced enrichment + reflection
            if force_reflection and not initial.startswith("ERROR"):
                enrichment = get_enrichment(initial)

                dict_hints = " | ".join(
                    f"{h.get('term', '')}: {h.get('definition', '')}"
                    for h in enrichment["dictionary"]
                ) or "No dictionary hints available."

                extracts_str = "\n---\n".join(
                    f"**{e.get('source', '')}**\n{e.get('passage', '')}"
                    for e in enrichment["extracts"][:5]
                ) or "No extracts available."

                ee_pairs_str = render_paired_translations(enrichment["ee_to_en_pairs"])

                style_text = ctx["style_guide"].get("general", "")
                specific = ctx["style_guide"].get("specific", "")
                if specific and specific != "No specific guidance required.":
                    style_text += "\n\n" + specific

                reflection_prompt = REFLECTION_USER.format(
                    preferred_term=preferred_term,
                    estonian_term=initial,
                    dictionary_hints=dict_hints,
                    extracts=extracts_str,
                    ee_to_en_paired_translations=ee_pairs_str,
                    style_guidelines=style_text[:1000],
                )

                translation = await sdk_query(reflection_prompt, REFLECTION_SYSTEM, model)
                logger.info("  [%s] reflected -> %s", sctid, translation)
                context_used = "full_pipeline+reflection"

        except Exception as e:
            logger.error("Failed %s: %s", preferred_term, e)
            translation = f"ERROR: {e}"
            context_used = "error"

    return {
        "sctid": str(sctid),
        "preferred_term": preferred_term,
        "hierarchy": hierarchy,
        "translation": translation,
        "context_used": context_used,
    }


async def main_async(args):
    prompt_mod = importlib.import_module(args.prompt)

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    mode = "initial + reflection" if args.force_reflection else "initial only"
    logger.info(
        "Translating %d concepts with %s (%s, concurrency=%d)",
        len(rows), args.model, mode, args.concurrency,
    )

    sem = asyncio.Semaphore(args.concurrency)

    start = time.monotonic()
    tasks = [
        translate_one(sem, prompt_mod, args.model, row, args.force_reflection)
        for row in rows
    ]
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start

    logger.info("Finished %d concepts in %.1fs", len(results), elapsed)

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
    parser.add_argument("--input", type=Path, default=Path("data/evals/sample/500_eval_concepts.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/evals/sample/500_translations_sonnet.csv"))
    parser.add_argument("--model", default="sonnet", help="Model: sonnet, opus, haiku")
    parser.add_argument("--prompt", default="qwen35b_prompt", help="Prompt module to use")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--force-reflection", action="store_true",
        help="Force one enrichment + reflection step (ignore initial confidence)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
