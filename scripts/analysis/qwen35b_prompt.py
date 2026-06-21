"""
Prompt template for Qwen 3.5 35B-A3B EN→ET SNOMED CT translation.

Designed to mitigate known failure modes of the 35B MoE model
(3B active params) in non-thinking (instruct) mode:
  - Medical register: defaults to colloquial/general Estonian vocabulary
    instead of clinical terminology (e.g. general "cancer" rather than
    the specific histological term)
  - Untranslated terms: sometimes leaves English or Latin terms in the
    output instead of translating or adapting them to Estonian
  - Compound word fragmentation: breaks apart what should be single
    Estonian medical compound words into separate words
  - Phonetic adaptation: inconsistent at adapting international
    scientific/chemical terms to Estonian phonetic conventions
  - Literal translation: translates word-by-word rather than using
    established Estonian medical terms or constructions
  - Semantic errors: occasionally picks the wrong meaning of a
    polysemous English word

Strengths to preserve:
  - Good word order on pathology terms (often places location first)
  - Handles simpler, shorter terms well
  - Generally readable and natural Estonian phrasing
  - Competent at standard medical vocabulary when not uncertain
"""

import re

# Import shared style-guide extraction from the 122B prompt module
from qwen122b_prompt import extract_matching_rules

SYSTEM_PROMPT = """\
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


def build_system_prompt() -> str:
    """Return the system prompt for Qwen 35B translation."""
    return SYSTEM_PROMPT


def build_user_prompt(
    english_term: str,
    hierarchy: str = "",
    synonyms: list[str] | None = None,
    parent_concepts: list[str] | None = None,
    related_concepts: list[str] | None = None,
    paired_translations: list[dict] | None = None,
    style_guide_general: str = "",
    style_guide_specific: str = "",
) -> str:
    """Return the user-turn prompt for a single term translation.

    All context sections are optional; when absent they are omitted
    so the prompt stays focused and avoids giving the model material
    to over-generate from.
    """
    sections: list[str] = []

    # ── 1. Task statement ─────────────────────────────────────────
    sections.append(
        "Translate the following SNOMED CT medical term from English to Estonian."
    )

    # ── 2. SNOMED graph context ───────────────────────────────────
    graph_lines: list[str] = []
    if hierarchy:
        graph_lines.append(f"Hierarchy: {hierarchy}")
    if parent_concepts:
        graph_lines.append(f"Parents: {', '.join(parent_concepts[:5])}")
    if synonyms:
        graph_lines.append(f"Synonyms: {', '.join(synonyms[:5])}")
    if related_concepts:
        graph_lines.append(f"Related: {', '.join(related_concepts[:5])}")
    if graph_lines:
        sections.append(
            "# Context (for reference only — do not copy labels into output)\n"
            + "\n".join(graph_lines)
        )

    # ── 3. Paired-translation hints ──────────────────────────────
    if paired_translations:
        short_pairs = [
            f"  {p['en']}  →  {p['ee']}"
            for p in paired_translations
            if p.get("en") and p.get("ee") and len(p["en"]) < 80
        ]
        if short_pairs:
            sections.append(
                "# Similar existing translations (use as style reference, "
                "do not copy verbatim)\n" + "\n".join(short_pairs[:5])
            )

    # ── 4. Style-guide rules ─────────────────────────────────────
    if style_guide_specific and style_guide_specific != "No specific guidance required.":
        matched_rules = extract_matching_rules(style_guide_specific, english_term)
        if matched_rules:
            sections.append(
                f"# Style rules for this term (from {hierarchy} style guide)\n"
                + matched_rules
            )

    if style_guide_general:
        trimmed = style_guide_general[:300].rsplit("\n", 1)[0]
        sections.append(f"# General style guidance\n{trimmed}")

    # ── 5. The term + output anchor ──────────────────────────────
    sections.append(
        f"English: {english_term}\n"
        "Respond with ONLY the Estonian translation (one term, no extras). "
        "Use medical register, not colloquial language.\n"
        "Estonian:"
    )

    return "\n\n".join(sections)
