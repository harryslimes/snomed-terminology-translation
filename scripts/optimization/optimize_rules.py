#!/usr/bin/env python
"""
Iterative rule optimization pipeline for SNOMED CT EN→ET translation.

For each SNOMED hierarchy:
  1. Split EE extension terms into train / holdout
  2. Start with empty (or existing) rules
  3. Loop:
     a. Translate train batch using current rules
     b. Score against references (chrF + BGE-M3 composite)
     c. Show Opus: current rules, worst translations, references
     d. Opus proposes improved general rules (not example-specific)
     e. Re-translate with new rules, score holdout
     f. Stop if holdout plateaus or max iterations reached
  4. Output: optimized rules YAML for this hierarchy

Usage:
    # Optimize rules for body structure
    python scripts/optimize_rules.py --hierarchy "body structure" --max-iter 5

    # Optimize all hierarchies
    python scripts/optimize_rules.py --all --max-iter 5
"""
import argparse
import asyncio
import csv
import json
import logging
import random
import re
import sys
import time
import yaml
from pathlib import Path

import aiohttp
import numpy as np
import requests
import sacrebleu
from FlagEmbedding import BGEM3FlagModel

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("optimize_rules")

TOOLS_SERVER = "http://localhost:8008"
VLLM_URL = "http://localhost:8085"
VLLM_MODEL = "cyankiwi/Qwen3-Next-80B-A3B-Instruct-AWQ-4bit"
RULES_DIR = Path("data/rules")
SPLITS_DIR = Path("data/evals/splits")

SAMPLING_PARAMS = {"temperature": 0, "top_p": 1.0, "repetition_penalty": 1.0}
DEBUG_DIR = Path("data/rules/debug")

# Rule suggestion model: "opus" (via Agent SDK) or "vllm" (use the same vLLM model)
RULE_SUGGESTER = "opus"

# ── Data Loading ─────────────────────────────────────────────────────────


def load_ee_extension() -> list[dict]:
    """Load all active Estonian descriptions from the SNOMED EE extension."""
    ext_path = Path("data/SNOMED_EE_national_extension/xsct2_Description_Snapshot-et_EE1000181_20250530.txt")
    with ext_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = [r for r in reader if r["active"] == "1"]
    # Group by concept: collect all terms
    concepts = {}
    for r in rows:
        cid = r["conceptId"]
        if cid not in concepts:
            concepts[cid] = {"sctid": cid, "terms": []}
        concepts[cid]["terms"].append(r["term"])
    return list(concepts.values())


def resolve_hierarchy(sctid: str) -> dict | None:
    """Get hierarchy and English preferred term from tools server."""
    try:
        r = requests.get(f"{TOOLS_SERVER}/snomed_graph", params={"sctid": int(sctid)}, timeout=10)
        if r.ok:
            data = r.json()
            return {
                "preferred_term": data.get("preferred_term", ""),
                "hierarchy": data.get("hierarchy", ""),
                "synonyms": data.get("synonyms", []),
                "parent_concepts": data.get("parent_concepts", []),
                "related_concepts": data.get("related_concepts", []),
            }
    except Exception:
        pass
    return None


def build_split(hierarchy: str, train_ratio: float = 0.8, max_total: int = 300, seed: int = 42) -> tuple[list, list]:
    """Build or load train/holdout split for a hierarchy.

    Returns (train, holdout) where each item is:
    {sctid, preferred_term, hierarchy, ee_all: [list], ee_reference}
    """
    split_path = SPLITS_DIR / f"{hierarchy.replace(' ', '_').replace('/', '_')}_split.json"
    if split_path.exists():
        with split_path.open() as f:
            data = json.load(f)
        logger.info("Loaded existing split: %d train, %d holdout", len(data["train"]), len(data["holdout"]))
        return data["train"], data["holdout"]

    logger.info("Building train/holdout split for '%s'...", hierarchy)
    extension = load_ee_extension()

    # Resolve hierarchies — this is slow (HTTP per concept)
    items = []
    for i, concept in enumerate(extension):
        if len(items) >= max_total * 2:  # resolve more than needed, filter later
            break
        info = resolve_hierarchy(concept["sctid"])
        if info and info["hierarchy"] == hierarchy and info["preferred_term"]:
            items.append({
                "sctid": concept["sctid"],
                "preferred_term": info["preferred_term"],
                "hierarchy": hierarchy,
                "ee_all": concept["terms"],
                "ee_reference": concept["terms"][0],
                "synonyms": info.get("synonyms", []),
                "parent_concepts": info.get("parent_concepts", []),
                "related_concepts": info.get("related_concepts", []),
            })
        if (i + 1) % 100 == 0:
            logger.info("  Resolved %d concepts, found %d for '%s'", i + 1, len(items), hierarchy)

    if len(items) > max_total:
        random.seed(seed)
        items = random.sample(items, max_total)

    random.seed(seed)
    random.shuffle(items)
    split = int(len(items) * train_ratio)
    train, holdout = items[:split], items[split:]

    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    with split_path.open("w") as f:
        json.dump({"train": train, "holdout": holdout}, f, ensure_ascii=False, indent=2)

    logger.info("Split: %d train, %d holdout (saved to %s)", len(train), len(holdout), split_path)
    return train, holdout


# ── Rules Management ─────────────────────────────────────────────────────


def load_rules(hierarchy: str) -> list[str]:
    """Load existing rules for a hierarchy, or return empty list."""
    path = RULES_DIR / f"{hierarchy.replace(' ', '_').replace('/', '_')}.yaml"
    if path.exists():
        with path.open() as f:
            data = yaml.safe_load(f)
        return data.get("rules", [])
    return []


def save_rules(hierarchy: str, rules: list[str], iteration: int):
    """Save rules to YAML."""
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    path = RULES_DIR / f"{hierarchy.replace(' ', '_').replace('/', '_')}.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(
            {"hierarchy": hierarchy, "iteration": iteration, "rules": rules},
            f, allow_unicode=True, default_flow_style=False, width=120,
        )
    logger.info("Saved %d rules to %s", len(rules), path)


# ── Translation ──────────────────────────────────────────────────────────


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


def build_system_prompt_with_rules(rules: list[str]) -> str:
    """Combine base system prompt with hierarchy-specific rules."""
    if not rules:
        return SYSTEM_PROMPT_BASE
    rules_text = "\n".join(f"- {r}" for r in rules)
    return f"{SYSTEM_PROMPT_BASE}\n\n# Hierarchy-specific translation rules\n{rules_text}"


def build_user_prompt(item: dict, paired_translations: list[dict] | None = None) -> str:
    """Build user prompt for a single term."""
    sections = ["Translate the following SNOMED CT medical term from English to Estonian."]

    graph_lines = []
    if item.get("hierarchy"):
        graph_lines.append(f"Hierarchy: {item['hierarchy']}")
    if item.get("parent_concepts"):
        graph_lines.append(f"Parents: {', '.join(item['parent_concepts'][:5])}")
    if item.get("synonyms"):
        graph_lines.append(f"Synonyms: {', '.join(item['synonyms'][:5])}")
    if graph_lines:
        sections.append(
            "# Context (for reference only — do not copy labels into output)\n"
            + "\n".join(graph_lines)
        )

    if paired_translations:
        short_pairs = [
            f"  {p['en']}  →  {p['ee']}"
            for p in paired_translations
            if p.get("en") and p.get("ee") and len(p["en"]) < 80
        ][:5]
        if short_pairs:
            sections.append(
                "# Similar existing translations (use as style reference)\n"
                + "\n".join(short_pairs)
            )

    sections.append(
        f"English: {item['preferred_term']}\n"
        "Respond with ONLY the Estonian translation (one term, no extras).\n"
        "Estonian:"
    )
    return "\n\n".join(sections)


def get_paired_translations(preferred_term: str) -> list[dict]:
    """Fetch paired translations from tools server."""
    try:
        r = requests.get(
            f"{TOOLS_SERVER}/paired_translations_en_to_ee",
            params={"preferred_term": preferred_term, "max_results": 3},
            timeout=10,
        )
        if r.ok:
            return r.json()
    except Exception:
        pass
    return []


async def translate_batch(
    items: list[dict],
    rules: list[str],
    concurrency: int = 16,
    debug_label: str = "",
) -> list[dict]:
    """Translate a batch of items using vLLM with current rules."""
    system_prompt = build_system_prompt_with_rules(rules)
    sem = asyncio.Semaphore(concurrency)

    # Debug: save system prompt and a sample user prompt
    if debug_label:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        debug_path = DEBUG_DIR / f"{debug_label}_system_prompt.txt"
        with debug_path.open("w", encoding="utf-8") as f:
            f.write(system_prompt)
        if items:
            sample_pairs = get_paired_translations(items[0]["preferred_term"])
            sample_user = build_user_prompt(items[0], sample_pairs)
            sample_path = DEBUG_DIR / f"{debug_label}_sample_user_prompt.txt"
            with sample_path.open("w", encoding="utf-8") as f:
                f.write(f"# Term: {items[0]['preferred_term']}\n\n{sample_user}")
        logger.info("Debug prompts saved to %s", DEBUG_DIR / f"{debug_label}_*")

    async def translate_one(session: aiohttp.ClientSession, item: dict) -> dict:
        pairs = get_paired_translations(item["preferred_term"])
        user_prompt = build_user_prompt(item, pairs)

        payload = {
            "model": VLLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 256,
            "stop": ["\n\n", "\n"],
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
                if "<think>" in content:
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                return {**item, "translation": content}
            except Exception as e:
                logger.error("Translation failed for %s: %s", item["preferred_term"], e)
                return {**item, "translation": f"ERROR: {e}"}

    async with aiohttp.ClientSession() as session:
        tasks = [translate_one(session, item) for item in items]
        return await asyncio.gather(*tasks)


# ── Scoring ──────────────────────────────────────────────────────────────


def score_translations(
    results: list[dict],
    bgem3: BGEM3FlagModel,
) -> list[dict]:
    """Score translations with chrF + BGE-M3 cosine + exact match."""
    candidates = [r["translation"] for r in results]
    ref_groups = [r["ee_all"] for r in results]

    # chrF + exact
    for r in results:
        cand = r["translation"]
        refs = r["ee_all"]
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
        cand_vec = embeddings[i]
        best_sim = 0.0
        for j in range(offset, offset + count):
            ref_vec = embeddings[j]
            sim = float(np.dot(cand_vec, ref_vec) / (np.linalg.norm(cand_vec) * np.linalg.norm(ref_vec) + 1e-9))
            best_sim = max(best_sim, sim)
        results[i]["cosine"] = best_sim

    for r in results:
        r["composite"] = 0.5 * (r["chrf"] / 100) + 0.3 * r["cosine"] + 0.2 * r["exact"]

    return results


# ── Opus Rule Generation ─────────────────────────────────────────────────

RULE_GENERATION_SYSTEM = """\
You are a senior linguistic consultant specialising in medical terminology translation \
(English → Estonian) for SNOMED CT.

Your task is to analyse translation attempts and their reference translations, then \
propose NEW translation rules to address the remaining errors.

IMPORTANT CONSTRAINTS:
1. Generate RULES, not a prompt. Each rule should be a clear, actionable principle.
2. Rules must be GENERAL — they should apply to many terms in this category, not fix one specific example.
3. AVOID example-heavy rules. A rule may include ONE brief example for clarity if absolutely needed, but the rule itself must stand without it.
4. Focus on PATTERNS you see in the errors — systematically wrong conventions, missing affixes, wrong word choices for a category, etc.
5. Be CONCISE. Each rule should be 1-2 sentences max.
6. Propose 1 to 3 NEW rules that address errors NOT already covered by the existing rules.
7. Do NOT repeat or rephrase existing rules — only propose rules that address NEW patterns.
8. Output as a YAML list under a 'new_rules' key. Nothing else."""

RULE_GENERATION_USER = """\
# Hierarchy: {hierarchy}

# Existing rules (DO NOT repeat these — they are already applied)
{current_rules}

# Translation results (sorted worst-first)
The following translations were attempted WITH the existing rules above. For each, \
the 'candidate' is what our system produced and 'reference' is the accepted Estonian translation.

{worst_examples}

# Summary statistics
- Mean chrF: {mean_chrf:.1f}/100
- Mean cosine similarity: {mean_cosine:.3f}
- Exact match rate: {exact_pct:.1f}%
- Mean composite: {mean_composite:.3f}

# Common error patterns observed
{error_patterns}

Based on these REMAINING errors (not already addressed by existing rules), propose 1-3 NEW rules \
for the '{hierarchy}' hierarchy. Focus on the most impactful patterns not yet covered.
Remember: general principles only, not fixes for individual terms."""


def analyse_error_patterns(scored: list[dict]) -> str:
    """Simple heuristic analysis of common errors."""
    patterns = []

    # Check for systematic issues
    wrong_prefix = 0
    wrong_suffix = 0
    too_long = 0
    too_short = 0
    latin_kept = 0

    for r in scored:
        cand = r["translation"]
        ref = r["ee_reference"]
        if cand.startswith("ERROR"):
            continue

        cand_words = cand.lower().split()
        ref_words = ref.lower().split()

        if len(cand_words) > len(ref_words) + 1:
            too_long += 1
        if len(cand_words) < len(ref_words) - 1:
            too_short += 1

        # Check if candidate kept Latin/English where ref uses Estonian
        latin_chars = set("abcdefghijklmnopqrstuvwxyz")
        estonian_chars = set("äöüõšž")
        if any(c in estonian_chars for c in ref.lower()) and not any(c in estonian_chars for c in cand.lower()):
            latin_kept += 1

    total = len([r for r in scored if not r["translation"].startswith("ERROR")])
    if total == 0:
        return "No valid translations to analyse."

    if too_long > total * 0.2:
        patterns.append(f"- Translations are often TOO LONG ({too_long}/{total} have more words than reference)")
    if too_short > total * 0.2:
        patterns.append(f"- Translations are often TOO SHORT ({too_short}/{total} have fewer words than reference)")
    if latin_kept > total * 0.15:
        patterns.append(f"- Latin/English terms kept where Estonian equivalents exist ({latin_kept}/{total})")

    # Check if first word often differs
    first_word_match = sum(
        1 for r in scored
        if not r["translation"].startswith("ERROR")
        and r["translation"].lower().split()[0] == r["ee_reference"].lower().split()[0]
    )
    if first_word_match < total * 0.4:
        patterns.append(f"- First word frequently differs from reference ({first_word_match}/{total} match)")

    if not patterns:
        patterns.append("- No strong systematic pattern detected; errors appear term-specific.")

    return "\n".join(patterns)


def _build_rule_gen_prompt(
    hierarchy: str,
    current_rules: list[str],
    scored_results: list[dict],
) -> str:
    """Build the user prompt for rule generation (shared by all backends)."""
    sorted_results = sorted(scored_results, key=lambda r: r["composite"])
    valid = [r for r in sorted_results if not r["translation"].startswith("ERROR")]

    worst = valid[:30]
    best = valid[-10:] if len(valid) > 10 else []

    examples_lines = []
    for r in worst:
        examples_lines.append(
            f"  - english: \"{r['preferred_term']}\"\n"
            f"    candidate: \"{r['translation']}\"\n"
            f"    reference: \"{r['ee_reference']}\"\n"
            f"    chrf: {r['chrf']:.0f}  cosine: {r['cosine']:.3f}"
        )
    if best:
        examples_lines.append("\n# Well-translated examples (for contrast):")
        for r in best:
            examples_lines.append(
                f"  - english: \"{r['preferred_term']}\"\n"
                f"    candidate: \"{r['translation']}\"\n"
                f"    reference: \"{r['ee_reference']}\"\n"
                f"    chrf: {r['chrf']:.0f}  cosine: {r['cosine']:.3f}"
            )

    rules_text = yaml.dump(current_rules, allow_unicode=True) if current_rules else "No rules yet (first iteration)."

    valid_scored = [r for r in scored_results if not r["translation"].startswith("ERROR")]
    return RULE_GENERATION_USER.format(
        hierarchy=hierarchy,
        current_rules=rules_text,
        worst_examples="\n".join(examples_lines),
        mean_chrf=np.mean([r["chrf"] for r in valid_scored]),
        mean_cosine=np.mean([r["cosine"] for r in valid_scored]),
        exact_pct=np.mean([r["exact"] for r in valid_scored]) * 100,
        mean_composite=np.mean([r["composite"] for r in valid_scored]),
        error_patterns=analyse_error_patterns(valid_scored),
    )


def _parse_rules_yaml(raw: str, fallback: list[str]) -> list[str]:
    """Parse YAML rules list from raw LLM output.

    Accepts either 'new_rules' or 'rules' key, or a bare list.
    """
    text = raw
    try:
        if "```" in text:
            match = re.search(r"```(?:yaml)?\s*\n(.*?)```", text, re.DOTALL)
            if match:
                text = match.group(1)
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            if "new_rules" in parsed:
                rules = parsed["new_rules"]
            elif "rules" in parsed:
                rules = parsed["rules"]
            else:
                logger.warning("Unexpected YAML structure, keeping previous rules")
                return fallback
        elif isinstance(parsed, list):
            rules = parsed
        else:
            logger.warning("Unexpected YAML structure, keeping previous rules")
            return fallback
    except Exception as e:
        logger.error("Failed to parse rules YAML: %s\nRaw:\n%s", e, raw[:500])
        return fallback

    rules = [str(r) for r in rules if r]
    return rules


async def _call_opus(system: str, user: str) -> str:
    """Call Opus via Claude Agent SDK."""
    from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
    result = ""
    async for message in query(
        prompt=user,
        options=ClaudeAgentOptions(
            system_prompt=system,
            model="opus",
            allowed_tools=[],
            max_turns=1,
        ),
    ):
        if isinstance(message, ResultMessage):
            result = message.result.strip()
    return result


async def _call_vllm(system: str, user: str) -> str:
    """Call the vLLM model for rule generation."""
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 4096,
        "temperature": 0,
        "top_p": 1.0,
        "repetition_penalty": 1.0,
    }
    # Add no-think for Qwen models
    payload["chat_template_kwargs"] = {"enable_thinking": False}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{VLLM_URL}/v1/chat/completions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=300),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

    content = data["choices"][0]["message"]["content"]
    if "<think>" in content:
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return content.strip()


async def generate_rules(
    hierarchy: str,
    current_rules: list[str],
    scored_results: list[dict],
    iteration: int = 0,
) -> list[str]:
    """Generate improved rules using configured RULE_SUGGESTER backend."""
    prompt = _build_rule_gen_prompt(hierarchy, current_rules, scored_results)

    # Debug: save prompts
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    debug_prefix = f"{hierarchy.replace(' ', '_').replace('/', '_')}_iter{iteration}_{RULE_SUGGESTER}"
    with (DEBUG_DIR / f"{debug_prefix}_system.txt").open("w", encoding="utf-8") as f:
        f.write(RULE_GENERATION_SYSTEM)
    with (DEBUG_DIR / f"{debug_prefix}_user.txt").open("w", encoding="utf-8") as f:
        f.write(prompt)
    logger.info("Debug: rule gen prompts saved to %s", DEBUG_DIR / f"{debug_prefix}_*")

    logger.info("Asking %s to generate rules for '%s'...", RULE_SUGGESTER, hierarchy)

    if RULE_SUGGESTER == "opus":
        result = await _call_opus(RULE_GENERATION_SYSTEM, prompt)
    elif RULE_SUGGESTER == "vllm":
        result = await _call_vllm(RULE_GENERATION_SYSTEM, prompt)
    else:
        raise ValueError(f"Unknown RULE_SUGGESTER: {RULE_SUGGESTER}")

    # Debug: save raw response
    with (DEBUG_DIR / f"{debug_prefix}_response.txt").open("w", encoding="utf-8") as f:
        f.write(result)

    new_rules = _parse_rules_yaml(result, [])
    logger.info("%s proposed %d new rules", RULE_SUGGESTER, len(new_rules))
    for i, r in enumerate(new_rules, 1):
        logger.info("  New rule %d: %s", i, r[:100])

    return new_rules


# ── Main Optimization Loop ───────────────────────────────────────────────


MAX_RULES = 20
ABLATION_INTERVAL = 4


async def ablate_rules(
    rules: list[str],
    holdout: list[dict],
    bgem3: BGEM3FlagModel,
    baseline_score: float,
    concurrency: int,
    h_slug: str,
) -> list[str]:
    """Remove rules that don't contribute positively.

    Tests each rule by removing it; if the score doesn't drop, the rule is dead weight.
    """
    if len(rules) <= 1:
        return rules

    logger.info("--- Ablation: testing %d rules ---", len(rules))
    keep = []
    for i, rule in enumerate(rules):
        without = rules[:i] + rules[i + 1:]
        results = await translate_batch(holdout, without, concurrency, debug_label="")
        scored = score_translations(results, bgem3)
        valid = [r for r in scored if not r["translation"].startswith("ERROR")]
        score = np.mean([r["composite"] for r in valid]) if valid else 0.0

        if score < baseline_score - 0.003:
            # Removing this rule hurts — keep it
            keep.append(rule)
            logger.info("  Rule %d: KEEP (without=%.3f, baseline=%.3f)", i + 1, score, baseline_score)
        else:
            logger.info("  Rule %d: DROP (without=%.3f, baseline=%.3f) — %s",
                         i + 1, score, baseline_score, rule[:80])

    logger.info("Ablation: kept %d/%d rules", len(keep), len(rules))
    return keep


async def optimize_hierarchy(
    hierarchy: str,
    max_iter: int = 5,
    plateau_threshold: float = 0.005,
    concurrency: int = 16,
    smoke_test: bool = False,
):
    """Run the optimization loop for one hierarchy.

    Uses incremental rule building: each iteration proposes 1-3 new rules that are
    added to the existing set. Acceptance is based on train improvement with holdout
    as a safety check against regression.
    """
    logger.info("=" * 60)
    logger.info("Optimizing rules for: %s%s", hierarchy, " [SMOKE TEST]" if smoke_test else "")
    logger.info("=" * 60)

    # Load BGE-M3 for scoring
    logger.info("Loading BGE-M3 (CPU)...")
    bgem3 = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, device="cpu")

    # Build or load split
    train, holdout = build_split(hierarchy)

    if smoke_test:
        train = train[:10]
        holdout = holdout[:5]
        logger.info("SMOKE TEST: trimmed to %d train, %d holdout", len(train), len(holdout))
    logger.info("Train: %d terms, Holdout: %d terms", len(train), len(holdout))

    # Load existing rules or start fresh
    rules = load_rules(hierarchy)
    if rules:
        logger.info("Starting with %d existing rules", len(rules))
    else:
        logger.info("Starting with no rules")

    best_holdout_score = 0.0
    best_train_score = 0.0
    no_improvement_count = 0
    history = []
    h_slug = hierarchy.replace(" ", "_").replace("/", "_")

    # Step 0: baseline — score with current rules (or no rules)
    logger.info("\n--- Baseline (iteration 0) ---")
    logger.info("Translating %d holdout terms with starting rules...", len(holdout))
    baseline_results = await translate_batch(
        holdout, rules, concurrency,
        debug_label=f"{h_slug}_iter0_holdout",
    )
    logger.info("Scoring baseline holdout...")
    baseline_scored = score_translations(baseline_results, bgem3)
    baseline_valid = [r for r in baseline_scored if not r["translation"].startswith("ERROR")]
    if baseline_valid:
        best_holdout_score = np.mean([r["composite"] for r in baseline_valid])
        logger.info("Baseline holdout composite: %.3f", best_holdout_score)
    else:
        logger.info("Baseline holdout: no valid translations")

    # Also score baseline train
    logger.info("Translating %d train terms for baseline...", len(train))
    baseline_train_results = await translate_batch(
        train, rules, concurrency,
        debug_label=f"{h_slug}_iter0_train",
    )
    baseline_train_scored = score_translations(baseline_train_results, bgem3)
    baseline_train_valid = [r for r in baseline_train_scored if not r["translation"].startswith("ERROR")]
    if baseline_train_valid:
        best_train_score = np.mean([r["composite"] for r in baseline_train_valid])
        logger.info("Baseline train composite: %.3f", best_train_score)

    for iteration in range(1, max_iter + 1):
        logger.info("\n--- Iteration %d/%d (rules: %d) ---", iteration, max_iter, len(rules))

        # Periodic ablation to prune dead rules
        if iteration > 1 and len(rules) > 1 and (iteration - 1) % ABLATION_INTERVAL == 0:
            # Re-score holdout with current rules for accurate baseline
            abl_results = await translate_batch(holdout, rules, concurrency, debug_label="")
            abl_scored = score_translations(abl_results, bgem3)
            abl_valid = [r for r in abl_scored if not r["translation"].startswith("ERROR")]
            abl_score = np.mean([r["composite"] for r in abl_valid]) if abl_valid else 0.0
            rules = await ablate_rules(rules, holdout, bgem3, abl_score, concurrency, h_slug)
            save_rules(hierarchy, rules, iteration)

        # Translate train set with current rules
        logger.info("Translating %d train terms...", len(train))
        train_results = await translate_batch(
            train, rules, concurrency,
            debug_label=f"{h_slug}_iter{iteration}_train",
        )

        # Score train set
        logger.info("Scoring train translations...")
        train_scored = score_translations(train_results, bgem3)
        train_valid = [r for r in train_scored if not r["translation"].startswith("ERROR")]
        train_composite = np.mean([r["composite"] for r in train_valid]) if train_valid else 0.0
        train_chrf = np.mean([r["chrf"] for r in train_valid]) if train_valid else 0.0
        train_exact = (np.mean([r["exact"] for r in train_valid]) * 100) if train_valid else 0.0

        logger.info("Train scores — composite: %.3f, chrF: %.1f, exact: %.1f%%",
                     train_composite, train_chrf, train_exact)

        # Generate NEW candidate rules (incremental — adds to existing)
        new_rules = await generate_rules(hierarchy, rules, train_scored, iteration)

        if not new_rules:
            logger.info("No new rules proposed — skipping this iteration")
            no_improvement_count += 1
            history.append({
                "iteration": iteration,
                "train_composite": train_composite,
                "holdout_composite": best_holdout_score,
                "holdout_chrf": 0, "holdout_exact": 0,
                "n_rules": len(rules),
                "accepted": False,
                "best_holdout": best_holdout_score,
            })
            if no_improvement_count >= 5:
                break
            continue

        # Combine existing rules + new candidates
        candidate_rules = rules + new_rules
        if len(candidate_rules) > MAX_RULES:
            logger.warning("Rule count (%d) exceeds max (%d), truncating oldest",
                           len(candidate_rules), MAX_RULES)
            candidate_rules = candidate_rules[-MAX_RULES:]

        # Translate holdout with candidate rules
        logger.info("Translating %d holdout terms with %d rules (%d existing + %d new)...",
                     len(holdout), len(candidate_rules), len(rules), len(new_rules))
        holdout_results = await translate_batch(
            holdout, candidate_rules, concurrency,
            debug_label=f"{h_slug}_iter{iteration}_holdout",
        )

        # Score holdout
        logger.info("Scoring holdout translations...")
        holdout_scored = score_translations(holdout_results, bgem3)
        holdout_valid = [r for r in holdout_scored if not r["translation"].startswith("ERROR")]
        holdout_composite = np.mean([r["composite"] for r in holdout_valid]) if holdout_valid else 0.0
        holdout_chrf = np.mean([r["chrf"] for r in holdout_valid]) if holdout_valid else 0.0
        holdout_exact = (np.mean([r["exact"] for r in holdout_valid]) * 100) if holdout_valid else 0.0

        logger.info("Holdout scores — composite: %.3f, chrF: %.1f, exact: %.1f%%",
                     holdout_composite, holdout_chrf, holdout_exact)

        # Acceptance criteria:
        # 1. Accept if train improved and holdout didn't regress badly
        # 2. Also accept if holdout itself clearly improved
        train_improved = train_composite > best_train_score + plateau_threshold
        holdout_regressed = holdout_composite < best_holdout_score - 0.015
        holdout_improved = holdout_composite > best_holdout_score + plateau_threshold

        accepted = False
        if holdout_improved:
            accepted = True
            reason = f"holdout improved: {holdout_composite:.3f} (+{holdout_composite - best_holdout_score:.3f})"
        elif train_improved and not holdout_regressed:
            accepted = True
            reason = (f"train improved: {train_composite:.3f} (+{train_composite - best_train_score:.3f}), "
                      f"holdout stable: {holdout_composite:.3f}")
        else:
            reason = (f"train {'improved' if train_improved else 'flat'}: {train_composite:.3f}, "
                      f"holdout {'regressed' if holdout_regressed else 'flat'}: {holdout_composite:.3f}")

        if accepted:
            rules = candidate_rules
            save_rules(hierarchy, rules, iteration)
            if train_composite > best_train_score:
                best_train_score = train_composite
            if holdout_composite > best_holdout_score:
                best_holdout_score = holdout_composite
            no_improvement_count = 0
            logger.info("ACCEPTED (%d rules) — %s", len(rules), reason)
        else:
            no_improvement_count += 1
            logger.info("REJECTED — %s (consecutive failures: %d)", reason, no_improvement_count)

        history.append({
            "iteration": iteration,
            "train_composite": train_composite,
            "holdout_composite": holdout_composite,
            "holdout_chrf": holdout_chrf,
            "holdout_exact": holdout_exact,
            "n_rules": len(candidate_rules),
            "accepted": accepted,
            "best_holdout": best_holdout_score,
        })

        # Stop after 5 consecutive failures
        if no_improvement_count >= 5:
            logger.info("No improvement for %d consecutive iterations — stopping.",
                         no_improvement_count)
            break

    # Final save
    save_rules(hierarchy, rules, iteration)

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("Optimization complete for '%s'", hierarchy)
    logger.info("=" * 60)
    logger.info("History:")
    for h in history:
        status = "ACCEPTED" if h["accepted"] else "rejected"
        logger.info(
            "  Iter %d: train=%.3f holdout=%.3f (chrF=%.1f exact=%.1f%%) rules=%d [%s] best_ho=%.3f",
            h["iteration"], h["train_composite"], h["holdout_composite"],
            h["holdout_chrf"], h["holdout_exact"], h["n_rules"],
            status, h["best_holdout"],
        )
    logger.info("Final rules (%d) saved to %s",
                 len(rules), RULES_DIR / f"{h_slug}.yaml")

    return history


async def main_async(args):
    if args.all:
        hierarchies = [
            "body structure", "procedure", "disorder", "finding",
            "morphologic abnormality", "substance", "organism",
            "observable entity", "physical object", "specimen",
        ]
    else:
        hierarchies = [args.hierarchy]

    for h in hierarchies:
        await optimize_hierarchy(
            hierarchy=h,
            max_iter=1 if args.smoke_test else args.max_iter,
            plateau_threshold=args.plateau_threshold,
            concurrency=args.concurrency,
            smoke_test=args.smoke_test,
        )


def main():
    parser = argparse.ArgumentParser(description="Iterative rule optimization for SNOMED CT translation")
    parser.add_argument("--hierarchy", type=str, default="body structure",
                        help="SNOMED hierarchy to optimize")
    parser.add_argument("--all", action="store_true",
                        help="Optimize all major hierarchies")
    parser.add_argument("--max-iter", type=int, default=5,
                        help="Maximum optimization iterations")
    parser.add_argument("--plateau-threshold", type=float, default=0.005,
                        help="Minimum improvement to avoid plateau detection")
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run with tiny subset (10 train, 5 holdout, 1 iteration) to test pipeline")
    parser.add_argument("--rule-suggester", type=str, choices=["opus", "vllm"], default="opus",
                        help="Model to use for rule generation: opus (Agent SDK) or vllm")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory for rules and debug files (e.g. data/rules/qwen35b_35b)")
    parser.add_argument("--vllm-model", type=str, default=None,
                        help="Override vLLM model name")
    args = parser.parse_args()

    # Wire CLI args to module-level config
    global RULE_SUGGESTER, RULES_DIR, DEBUG_DIR, VLLM_MODEL
    RULE_SUGGESTER = args.rule_suggester
    if args.output_dir:
        RULES_DIR = Path(args.output_dir)
        DEBUG_DIR = RULES_DIR / "debug"
    if args.vllm_model:
        VLLM_MODEL = args.vllm_model

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
