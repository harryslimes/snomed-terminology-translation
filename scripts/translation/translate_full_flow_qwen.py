#!/usr/bin/env python
"""
Run the full agentic translation flow (initial → enrichment → reflection → revision)
using Qwen 3.5 35B via vLLM instead of Claude Sonnet/Opus.

Mirrors the LangGraph agent flow in agent/agent.py but calls vLLM directly.
Skips Cohere reranking and web search (no API keys required).

Usage:
    python scripts/translate_full_flow_qwen.py \
        --input data/evals/sample/100_concepts.csv \
        --output data/evals/sample/100_translations_qwen35b_fullflow.csv
"""
import argparse
import csv
import json
import logging
import re
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("full_flow_qwen")

TOOLS_SERVER = "http://localhost:8008"

# ── Prompt templates (adapted from agent/prompt_templates.py) ────────────

INITIAL_TRANSLATION_PROMPT = """\
# Task
Translate the following SNOMED CT preferred term from English into Estonian: '{preferred_term}'.

# Context
- Hierarchy: {hierarchy}
- Synonyms: {synonyms}
- Parent concepts: {parent_concepts}
- Related concepts: {related_concepts}

# Paired Translation Hints
The following paired translations from medical sources may help you translate this term:

{en_to_ee_paired_translations}

# Style Guidelines
Be sure to follow these guidelines to ensure that your translation is clinically accurate.

{style_guidelines}

# Instructions
Translate the SNOMED CT preferred term '{preferred_term}' into Estonian.
Use clinical/medical register. Always prefer the precise medical term over a colloquial synonym.

Your response MUST be a JSON object with exactly these keys:
{{
    "reasoning": "brief description of your translation rationale",
    "translation": "the Estonian translation",
    "confident": "YES or NO",
    "changed": "YES",
    "unverified_words": "comma-separated list of unverified Estonian words, or empty string"
}}

Output ONLY the JSON object, nothing else."""

REFLECTION_PROMPT = """\
# Task
Consider the following translation of a SNOMED CT preferred term from English into Estonian: '{preferred_term}' -> '{estonian_term}'.
Your job is to improve the translation based on the following additional sources.

# Style Guidelines
{style_guidelines}

# Source 1: Estonian clinical dictionary
{dictionary_hints}

# Source 2: Passages from Estonian medical documents
{extracts}

# Source 3: EE→EN paired translations
{ee_to_en_paired_translations}

In light of these sources, can you improve the translation?
If there are no material improvements, return the existing translation ('{estonian_term}') as is.
Use clinical/medical register throughout.

Your response MUST be a JSON object with exactly these keys:
{{
    "reasoning": "brief description of what you changed and why",
    "translation": "the Estonian translation",
    "confident": "YES or NO",
    "changed": "YES or NO",
    "unverified_words": "comma-separated list of unverified Estonian words, or empty string"
}}

Output ONLY the JSON object, nothing else."""

FORCED_REVISION_PROMPT = """\
# Task
Consider the following translation of a SNOMED CT preferred term from English into Estonian: '{preferred_term}' -> '{estonian_term}'.
The following words in the translation may not be clinically accurate: {unverified_words}.

English context:
- Hierarchy: {hierarchy}
- Synonyms: {synonyms}
- Parent concepts: {parent_concepts}
- Related concepts: {related_concepts}

Please suggest an improved translation for '{preferred_term}'.
Use clinical/medical register throughout.

Your response MUST be a JSON object with exactly these keys:
{{
    "reasoning": "brief description of what you changed and why",
    "translation": "the Estonian translation",
    "confident": "NO",
    "changed": "YES",
    "unverified_words": "comma-separated list of new words you added"
}}

Output ONLY the JSON object, nothing else."""


# ── vLLM API call ────────────────────────────────────────────────────────

def call_llm(base_url: str, model: str, prompt: str, max_tokens: int = 512) -> str:
    """Call vLLM chat completions and return raw content."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": (
                "You are a medical terminology translator for SNOMED CT "
                "(English → Estonian). Always respond with valid JSON only."
            )},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    resp = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=120)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    # Strip thinking blocks if any
    if "<think>" in content:
        content = content.split("</think>")[-1]
    return content.strip()


def parse_json_response(raw: str) -> dict:
    """Robustly parse JSON from LLM output."""
    # Strip markdown code fences
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Last resort: try ast.literal_eval
    try:
        from ast import literal_eval
        return literal_eval(raw)
    except Exception:
        pass

    # Return a fallback with raw content as translation
    logger.warning("Failed to parse JSON, using raw content: %s", raw[:100])
    return {
        "reasoning": "JSON parse failed",
        "translation": raw.split("\n")[0].strip('"').strip("'"),
        "confident": "NO",
        "changed": "YES",
        "unverified_words": "",
    }


# ── Tools server helpers ─────────────────────────────────────────────────

def render_paired_translations(pairs: list) -> str:
    md = "|English|Estonian|\n|---|---|\n"
    for p in pairs:
        if p and isinstance(p, dict):
            md += f"|{p.get('en', '')}|{p.get('ee', '')}|\n"
    return md


def get_pipeline_context(sctid: int) -> dict:
    """Fetch SNOMED graph, style guide, and paired translations."""
    ctx = {"snomed": {}, "paired_translations": [], "style_guide": {}}
    try:
        r = requests.get(f"{TOOLS_SERVER}/snomed_graph", params={"sctid": sctid}, timeout=10)
        if r.ok:
            ctx["snomed"] = r.json()
    except Exception as e:
        logger.warning("SNOMED graph failed for %d: %s", sctid, e)

    preferred = ctx["snomed"].get("preferred_term", "")
    hierarchy = ctx["snomed"].get("hierarchy", "")

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/paired_translations_en_to_ee",
            params={"preferred_term": preferred, "max_results": 3}, timeout=10,
        )
        if r.ok:
            ctx["paired_translations"] = r.json()
    except Exception as e:
        logger.warning("Paired translations failed: %s", e)

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/style_guide",
            params={"hierarchy": hierarchy}, timeout=10,
        )
        if r.ok:
            sg = r.json()
            ctx["style_guide"] = sg.get("general", "") + "\n\n" + sg.get("specific", "")
    except Exception as e:
        logger.warning("Style guide failed: %s", e)

    return ctx


def get_enrichment(estonian_term: str) -> dict:
    """Fetch enrichment sources: dictionary, clinical docs, reverse pairs."""
    enrichment = {"dictionary": [], "extracts": [], "ee_to_en_pairs": []}

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/sonaveeb",
            params={"estonian_term": estonian_term, "max_results": 3}, timeout=10,
        )
        if r.ok:
            enrichment["dictionary"] = r.json()
    except Exception as e:
        logger.warning("Sonaveeb failed: %s", e)

    for source in ["eesti_arst", "kliinikum", "haiglateliit"]:
        try:
            r = requests.get(
                f"{TOOLS_SERVER}/{source}",
                params={"estonian_term": estonian_term, "max_results": 3}, timeout=10,
            )
            if r.ok:
                enrichment["extracts"].extend(r.json())
        except Exception as e:
            logger.warning("%s failed: %s", source, e)

    try:
        r = requests.get(
            f"{TOOLS_SERVER}/paired_translations_ee_to_en",
            params={"preferred_term": estonian_term, "max_results": 3}, timeout=10,
        )
        if r.ok:
            enrichment["ee_to_en_pairs"] = r.json()
    except Exception as e:
        logger.warning("EE→EN pairs failed: %s", e)

    return enrichment


# ── Full agentic flow ────────────────────────────────────────────────────

def translate_full_flow(
    base_url: str,
    model: str,
    sctid: int,
    max_reflection_steps: int = 3,
) -> dict:
    """Run the full translation flow for one concept."""
    # Step 1: Prepare context
    ctx = get_pipeline_context(sctid)
    snomed = ctx["snomed"]
    preferred_term = snomed.get("preferred_term", "")
    hierarchy = snomed.get("hierarchy", "")

    result = {
        "sctid": sctid,
        "preferred_term": preferred_term,
        "hierarchy": hierarchy,
        "steps": [],
    }

    # Step 2: Initial translation
    prompt = INITIAL_TRANSLATION_PROMPT.format(
        preferred_term=preferred_term,
        hierarchy=hierarchy,
        synonyms=" | ".join(snomed.get("synonyms", [])[:5]),
        parent_concepts=" | ".join(snomed.get("parent_concepts", [])[:5]),
        related_concepts=" | ".join(snomed.get("related_concepts", [])[:5]),
        en_to_ee_paired_translations=render_paired_translations(ctx["paired_translations"]),
        style_guidelines=ctx["style_guide"][:1000],
    )

    raw = call_llm(base_url, model, prompt)
    initial = parse_json_response(raw)
    result["steps"].append({"step": "initial", **initial})

    logger.info("  Initial (confident=%s): %s", initial.get("confident"), initial.get("translation"))

    current = initial

    # Step 3: Reflection loop
    for i in range(max_reflection_steps):
        if current.get("confident", "").upper() == "YES":
            break

        # Enrichment
        estonian_term = current.get("translation", "")
        enrichment = get_enrichment(estonian_term)

        dict_hints = " | ".join(
            f"{h.get('term', '')}: {h.get('definition', '')}"
            for h in enrichment["dictionary"]
        ) or "No dictionary hints available."

        extracts_str = "\n---\n".join(
            f"**{e.get('source', '')}**\n{e.get('passage', '')}"
            for e in enrichment["extracts"][:5]
        ) or "No extracts available."

        ee_pairs_str = render_paired_translations(enrichment["ee_to_en_pairs"])

        # Reflection
        prompt = REFLECTION_PROMPT.format(
            preferred_term=preferred_term,
            estonian_term=estonian_term,
            style_guidelines=ctx["style_guide"][:1000],
            dictionary_hints=dict_hints,
            extracts=extracts_str,
            ee_to_en_paired_translations=ee_pairs_str,
        )

        raw = call_llm(base_url, model, prompt)
        reflection = parse_json_response(raw)
        result["steps"].append({"step": f"reflection_{i+1}", **reflection})

        logger.info(
            "  Reflection %d (confident=%s): %s",
            i + 1, reflection.get("confident"), reflection.get("translation"),
        )

        current = reflection

        # If still not confident and not at max iterations, do forced revision
        if current.get("confident", "").upper() != "YES" and i < max_reflection_steps - 1:
            prompt = FORCED_REVISION_PROMPT.format(
                preferred_term=preferred_term,
                estonian_term=current.get("translation", ""),
                hierarchy=hierarchy,
                synonyms=" | ".join(snomed.get("synonyms", [])[:5]),
                parent_concepts=" | ".join(snomed.get("parent_concepts", [])[:5]),
                related_concepts=" | ".join(snomed.get("related_concepts", [])[:5]),
                unverified_words=current.get("unverified_words", ""),
            )

            raw = call_llm(base_url, model, prompt)
            revision = parse_json_response(raw)
            result["steps"].append({"step": f"forced_revision_{i+1}", **revision})

            logger.info(
                "  Forced revision %d: %s",
                i + 1, revision.get("translation"),
            )

            current = revision

    result["final_translation"] = current.get("translation", "")
    result["num_steps"] = len(result["steps"])
    result["final_confident"] = current.get("confident", "NO")
    return result


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Full agentic flow with Qwen via vLLM")
    parser.add_argument("--input", type=Path, default=Path("data/evals/sample/100_concepts.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/evals/sample/100_translations_qwen35b_fullflow.csv"))
    parser.add_argument("--base-url", default="http://localhost:8085")
    parser.add_argument("--model", default="cyankiwi/Qwen3.5-35B-A3B-AWQ-4bit")
    parser.add_argument("--max-reflection-steps", type=int, default=3)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")

    # Wait for vLLM
    logger.info("Waiting for vLLM server...")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{args.base_url}/v1/models", timeout=5)
            if r.ok:
                break
        except requests.ConnectionError:
            pass
        time.sleep(5)
    else:
        raise RuntimeError("vLLM not ready")

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    logger.info("Running full flow on %d concepts", len(rows))
    results = []
    start = time.monotonic()

    for row in rows:
        sctid = int(row["sctid"])
        logger.info("Translating [%s] %s", sctid, row["preferred_term"])

        try:
            result = translate_full_flow(
                args.base_url, args.model, sctid, args.max_reflection_steps,
            )
        except Exception as e:
            logger.error("Failed %s: %s", row["preferred_term"], e)
            result = {
                "sctid": sctid,
                "preferred_term": row["preferred_term"],
                "hierarchy": row.get("hierarchy", ""),
                "final_translation": f"ERROR: {e}",
                "num_steps": 0,
                "final_confident": "NO",
                "steps": [],
            }

        results.append(result)

    elapsed = time.monotonic() - start
    logger.info("Finished %d concepts in %.1fs", len(results), elapsed)

    # Write CSV
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sctid", "preferred_term", "hierarchy", "translation",
            "num_steps", "confident", "context_used",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "sctid": r["sctid"],
                "preferred_term": r["preferred_term"],
                "hierarchy": r.get("hierarchy", ""),
                "translation": r["final_translation"],
                "num_steps": r["num_steps"],
                "confident": r["final_confident"],
                "context_used": "full_flow",
            })

    logger.info("Wrote %d translations to %s", len(results), args.output)


if __name__ == "__main__":
    main()
