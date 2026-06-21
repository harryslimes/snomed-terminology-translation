#!/usr/bin/env python
"""
Translate a sample subset of SNOMED CT concepts from English to Estonian
using Qwen 3.5 122B-A10B served via llama.cpp (OpenAI-compatible API).

Uses the full pipeline context from the tools server: SNOMED graph,
paired translations, and style guide.

Usage:
    # Start the model server and tools server first:
    docker compose up -d llamacpp-qwen qdrant
    python agent/tools.py  # port 8008

    # Run translation:
    python scripts/translate_sample_qwen122b.py

    # Custom input/output:
    python scripts/translate_sample_qwen122b.py \
        --input data/evals/sample/100_concepts.csv \
        --output data/evals/sample/100_translations_qwen122b.csv
"""
import argparse
import asyncio
import csv
import logging
import re
import time
from pathlib import Path

import aiohttp
import requests

import importlib

# ── Reflection prompt (plain-text output, not JSON) ──────────────────────

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("translate_sample_qwen122b")

DEFAULT_BASE_URL = "http://localhost:8082"
TOOLS_SERVER_URL = "http://localhost:8008"
DEFAULT_INPUT = "data/evals/sample/100_concepts.csv"
DEFAULT_OUTPUT = "data/evals/sample/100_translations_qwen122b.csv"

# Qwen 3.5 recommended: instruct (non-thinking) mode for general tasks
SAMPLING_PARAMS = {
    "temperature": 0.7,
    "top_p": 0.8,
    "top_k": 20,
    "min_p": 0.0,
    "presence_penalty": 1.5,
    "repetition_penalty": 1.0,
}


def wait_for_server(base_url: str, timeout: int = 600, vllm: bool = False) -> None:
    """Block until the server health endpoint responds."""
    endpoint = f"{base_url}/v1/models" if vllm else f"{base_url}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(endpoint, timeout=5)
            if resp.status_code == 200:
                logger.info("llama.cpp server is ready")
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise RuntimeError(f"llama.cpp server at {base_url} not ready within {timeout}s")


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


def get_enrichment(estonian_term: str) -> dict:
    """Fetch enrichment sources using the initial Estonian translation."""
    enrichment = {"dictionary": [], "extracts": [], "ee_to_en_pairs": []}
    try:
        r = requests.get(
            f"{TOOLS_SERVER_URL}/sonaveeb",
            params={"estonian_term": estonian_term, "max_results": 3}, timeout=10,
        )
        if r.ok:
            enrichment["dictionary"] = r.json()
    except Exception:
        pass

    for source in ["eesti_arst", "kliinikum", "haiglateliit"]:
        try:
            r = requests.get(
                f"{TOOLS_SERVER_URL}/{source}",
                params={"estonian_term": estonian_term, "max_results": 3}, timeout=10,
            )
            if r.ok:
                enrichment["extracts"].extend(r.json())
        except Exception:
            pass

    try:
        r = requests.get(
            f"{TOOLS_SERVER_URL}/paired_translations_ee_to_en",
            params={"preferred_term": estonian_term, "max_results": 3}, timeout=10,
        )
        if r.ok:
            enrichment["ee_to_en_pairs"] = r.json()
    except Exception:
        pass

    return enrichment


def render_paired_translations(pairs: list) -> str:
    if not pairs:
        return "No paired translations available."
    md = "|Estonian|English|\n|---|---|\n"
    for p in pairs:
        if p and isinstance(p, dict):
            md += f"|{p.get('ee', '')}|{p.get('en', '')}|\n"
    return md


# Module-level flag for force-reflection
_force_reflection: bool = False


# Prompt module — set by --prompt CLI arg, defaults to qwen122b_prompt
_prompt_mod = None


def _load_prompt_module(name: str):
    global _prompt_mod
    _prompt_mod = importlib.import_module(name)


def build_prompt_from_context(english_term: str, ctx: dict) -> str:
    """Build user prompt from pipeline context using the specialised template."""
    snomed = ctx.get("snomed", {})
    style = ctx.get("style_guide", {})

    return _prompt_mod.build_user_prompt(
        english_term=english_term,
        hierarchy=snomed.get("hierarchy", ""),
        synonyms=snomed.get("synonyms"),
        parent_concepts=snomed.get("parent_concepts"),
        related_concepts=snomed.get("related_concepts"),
        paired_translations=ctx.get("paired_translations"),
        style_guide_general=style.get("general", ""),
        style_guide_specific=style.get("specific", ""),
    )


# Module-level config set by CLI args
_vllm_model: str | None = None
_no_think_prefix: bool = False


async def translate_term(
    session: aiohttp.ClientSession,
    base_url: str,
    english_term: str,
    user_prompt: str,
    max_tokens: int = 256,
) -> str:
    """Translate an English term to Estonian via llama.cpp, vLLM, or Atlas."""
    payload = {
        "messages": [
            {"role": "system", "content": _prompt_mod.build_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        **({"stop": ["\n\n", "\n"]} if not _no_think_prefix else {}),
        **SAMPLING_PARAMS,
    }
    if _vllm_model:
        payload["model"] = _vllm_model
    if _no_think_prefix:
        payload["chat_template_kwargs"] = {"enable_thinking": False}

    async with session.post(
        f"{base_url}/v1/chat/completions", json=payload, timeout=aiohttp.ClientTimeout(total=300)
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()

    choices = data.get("choices", [])
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content", "")
    # Strip thinking blocks if they leak through despite --reasoning off
    if "<think>" in content:
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return content.strip()


async def translate_one(
    sem: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    base_url: str,
    row: dict,
    max_tokens: int,
) -> dict:
    """Translate a single concept with concurrency control."""
    sctid = row["sctid"]
    preferred_term = row["preferred_term"]
    hierarchy = row.get("hierarchy", "")

    ctx = get_pipeline_context(int(sctid), preferred_term, hierarchy)
    user_prompt = build_prompt_from_context(preferred_term, ctx)

    async with sem:
        logger.info("Translating [%s] %s", sctid, preferred_term)
        try:
            translation = await translate_term(
                session=session,
                base_url=base_url,
                english_term=preferred_term,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
            logger.info("  [%s] initial -> %s", sctid, translation)

            context_used = "full_pipeline"

            # Optional: enrichment + reflection step
            if _force_reflection and not translation.startswith("ERROR"):
                enrichment = get_enrichment(translation)

                dict_hints = " | ".join(
                    f"{h.get('term', '')}: {h.get('definition', '')}"
                    for h in enrichment["dictionary"]
                ) or "No dictionary hints available."

                extracts_str = "\n---\n".join(
                    f"**{e.get('source', '')}**\n{e.get('passage', '')}"
                    for e in enrichment["extracts"][:5]
                ) or "No extracts available."

                ee_pairs_str = render_paired_translations(enrichment["ee_to_en_pairs"])

                style = ctx.get("style_guide", {})
                style_text = style.get("general", "")
                specific = style.get("specific", "")
                if specific and specific != "No specific guidance required.":
                    style_text += "\n\n" + specific

                reflection_prompt = REFLECTION_USER.format(
                    preferred_term=preferred_term,
                    estonian_term=translation,
                    dictionary_hints=dict_hints[:500],
                    extracts=extracts_str[:800],
                    ee_to_en_paired_translations=ee_pairs_str[:400],
                    style_guidelines=style_text[:400],
                )

                # Call LLM again with reflection prompt
                payload = {
                    "messages": [
                        {"role": "system", "content": REFLECTION_SYSTEM},
                        {"role": "user", "content": reflection_prompt},
                    ],
                    "max_tokens": max_tokens,
                    **({"stop": ["\n\n", "\n"]} if not _no_think_prefix else {}),
                    **SAMPLING_PARAMS,
                }
                if _vllm_model:
                    payload["model"] = _vllm_model
                if _no_think_prefix:
                    payload["chat_template_kwargs"] = {"enable_thinking": False}

                try:
                    async with session.post(
                        f"{base_url}/v1/chat/completions", json=payload,
                        timeout=aiohttp.ClientTimeout(total=300),
                    ) as resp:
                        resp.raise_for_status()
                        data = await resp.json()

                    content = data["choices"][0]["message"]["content"]
                    if "<think>" in content:
                        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                    translation = content.strip()
                    context_used = "full_pipeline+reflection"
                    logger.info("  [%s] reflected -> %s", sctid, translation)
                except Exception as exc:
                    logger.warning("Reflection failed for %s, keeping initial: %s", preferred_term, exc)
                    context_used = "full_pipeline (reflection failed)"

        except Exception as exc:
            logger.error("Failed to translate %s: %s", preferred_term, exc)
            translation = f"ERROR: {exc}"
            context_used = "error"

    return {
        "sctid": sctid,
        "preferred_term": preferred_term,
        "hierarchy": hierarchy,
        "translation": translation,
        "context_used": context_used,
    }


async def main_async(args: argparse.Namespace) -> None:
    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    wait_for_server(args.base_url, args.wait_for_server, vllm=bool(_vllm_model))

    with args.input.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    logger.info("Translating %d concepts with Qwen 3.5 122B-A10B (concurrency=%d)", len(rows), args.concurrency)

    sem = asyncio.Semaphore(args.concurrency)
    async with aiohttp.ClientSession() as session:
        tasks = [
            translate_one(sem, session, args.base_url, row, args.max_tokens)
            for row in rows
        ]
        results = await asyncio.gather(*tasks)

    # Preserve original CSV order
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
        description="Translate SNOMED CT concepts EN->ET using Qwen 3.5 122B via llama.cpp"
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
    parser.add_argument(
        "--concurrency", type=int, default=8,
        help="Number of concurrent translation requests",
    )
    parser.add_argument("--temperature", type=float, default=None,
        help="Override sampling temperature (default: use SAMPLING_PARAMS)")
    parser.add_argument("--presence-penalty", type=float, default=None,
        help="Override presence penalty (default: use SAMPLING_PARAMS)")
    parser.add_argument(
        "--wait-for-server", type=int, default=600, metavar="SECONDS",
        help="Wait up to N seconds for the llama.cpp server to become healthy",
    )
    parser.add_argument(
        "--prompt", default="qwen122b_prompt",
        help="Prompt module to use (e.g. qwen122b_prompt, qwen35b_prompt)",
    )
    parser.add_argument(
        "--model", default=None,
        help="vLLM/Atlas model name (adds 'model' field to API payload)",
    )
    parser.add_argument(
        "--no-think", action="store_true",
        help="Prepend /no_think to system prompt (for Atlas Spark / Qwen thinking mode)",
    )
    parser.add_argument(
        "--force-reflection", action="store_true",
        help="Force one enrichment + reflection step after initial translation",
    )
    args = parser.parse_args()
    if args.temperature is not None:
        SAMPLING_PARAMS["temperature"] = args.temperature
    if args.presence_penalty is not None:
        SAMPLING_PARAMS["presence_penalty"] = args.presence_penalty
    _load_prompt_module(args.prompt)
    global _vllm_model, _no_think_prefix
    _vllm_model = args.model
    _no_think_prefix = args.no_think
    global _force_reflection
    _force_reflection = args.force_reflection
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
