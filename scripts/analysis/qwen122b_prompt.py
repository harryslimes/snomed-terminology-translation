"""
Prompt template for Qwen 3.5 122B-A10B EN→ET SNOMED CT translation.

Designed to mitigate known failure modes of the 122B MoE model in
non-thinking (instruct) mode:
  - Over-generation: adding unrequested prefixes, qualifiers, or
    paraphrases beyond the single term asked for
  - Verbosity: expanding compact concepts into full descriptive phrases
    instead of a concise clinical term
  - Anatomical hallucination: inserting broader anatomical context
    (e.g. adding "skull and facial bone fracture" before an orbital
    floor fracture) that was not in the source term
  - Occasional misspellings in inflected Estonian word forms
  - Inconsistent capitalisation (sometimes lowercase start)

Strengths to preserve:
  - Prefers native Estonian anatomical vocabulary over Latin borrowings
  - Strong phonetic adaptation of international chemical/drug names
  - Good grasp of Estonian medical compound-word formation
  - Accurate use of paired-translation context when available
"""

import re

SYSTEM_PROMPT = """\
You are a medical terminology translator for SNOMED CT (English → Estonian).

STRICT RULES:
1. Output ONLY the Estonian translation — one term, nothing else.
2. Do NOT add explanations, alternatives, qualifiers, or surrounding context.
3. Translate EXACTLY the given term — do not broaden scope, do not prepend \
related diagnoses, do not add anatomical context that is absent from the source.
4. Keep translations concise. Prefer established Estonian medical compound words \
over verbose descriptive phrases. If a single compound word exists, use it.
5. Prefer native Estonian anatomical terms over Latin borrowings when a standard \
Estonian equivalent is widely used (e.g. väikeaju > tserebellaarne, roidevagu > sulcus costae).
6. For international terms (drug names, chemical compounds, organisms): apply \
standard Estonian phonetic adaptation rules consistently.
7. Match the grammatical number and case of the source term faithfully.
8. Start the translation with an uppercase letter."""


# ── Style-guide rule extraction ─────────────────────────────────────────
#
# The style guide contains hierarchy-specific translation rules under
# "Kokkulepitud reeglid ja erandid" sections.  Each rule starts with a
# bold keyword pattern (**keyword**) followed by guidance and optional
# examples.  We parse these into individual rules and match them against
# keywords found in the English source term so only relevant rules reach
# the model — avoiding noise and the old 400-char truncation bug that
# cut off the rules table entirely.

_STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "and", "or", "is", "to",
    "for", "with", "by", "at", "from", "as", "it", "its",
    "x", "y", "term", "smth",
    # Meta-words from procedure rule descriptions (not term keywords)
    "first", "second", "third", "action", "method", "object",
    # Hierarchy names that would match everything in their category
    "procedure", "finding", "disorder", "substance", "structure",
    "applicable",
})

# Match bold at start of line: **keyword** or list-nested *   **keyword:**
_BOLD_RE = re.compile(r"^(?:\*\s+)?\*\*([^*]+)\*\*", re.MULTILINE)

_SKIP_HEADERS = frozenset({
    "parimad allikad", "arutelu ja otsuse ootel",
    "üldised põhimõtted", "kokkulepitud reeglid ja erandid",
    "nb!", "näide:", "otsus:",
})

# Parenthesised hierarchy markers that indicate a full SNOMED concept name
_HIERARCHY_MARKERS = re.compile(
    r"\((disorder|procedure|finding|body structure|substance|organism"
    r"|observable entity|qualifier value|situation|product)\)",
    re.IGNORECASE,
)


def _is_example_line(text: str) -> bool:
    """Return True if bold text is an example, not a rule keyword."""
    if not text:
        return True
    # SCTID examples start with digits
    if text[0].isdigit():
        return True
    # Full concept names contain hierarchy markers
    if _HIERARCHY_MARKERS.search(text):
        return True
    # RHK reference headers
    if text.lower().startswith("rhk-"):
        return True
    # Very long text is likely an example concept name, not a keyword
    if len(text) > 60:
        return True
    return False


def _keyword_to_triggers(keyword: str) -> list[str]:
    """Convert a rule keyword pattern into trigger phrases for matching."""
    cleaned = keyword.lower()
    cleaned = re.sub(r"[…()\[\]]", "", cleaned).strip()

    triggers: list[str] = []

    # Full phrase as a trigger (e.g. "co-occurrent and due to")
    full = re.sub(r"\s+", " ", cleaned).strip()
    if len(full) > 3 and full not in _STOPWORDS:
        triggers.append(full)

    # Handle slash alternatives: "with/without" -> each part
    if "/" in cleaned:
        for part in cleaned.split("/"):
            part = part.strip()
            if len(part) > 3 and part not in _STOPWORDS:
                triggers.append(part)

    # Individual meaningful words
    for w in re.split(r"[\s/,]+", cleaned):
        w = w.strip().strip(".")
        if len(w) > 3 and w not in _STOPWORDS:
            triggers.append(w)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in triggers:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _parse_style_rules(style_text: str) -> list[tuple[list[str], str]]:
    """Parse style guide text into (trigger_phrases, full_rule_text) pairs."""
    matches = list(_BOLD_RE.finditer(style_text))
    rules: list[tuple[list[str], str]] = []

    for i, m in enumerate(matches):
        keyword = m.group(1).strip()
        kw_lower = keyword.lower()

        # Skip examples and section headers
        if _is_example_line(keyword):
            continue
        if any(kw_lower.startswith(h) for h in _SKIP_HEADERS):
            continue

        # Extent: until the next non-example bold keyword OR a section header
        start = m.start()
        end = len(style_text)
        for j in range(i + 1, len(matches)):
            nxt = matches[j].group(1).strip()
            if not nxt:
                continue
            # Section headers end the current rule even though they're skipped
            if any(nxt.lower().startswith(h) for h in _SKIP_HEADERS):
                end = matches[j].start()
                break
            # Next real keyword also ends the current rule
            if not _is_example_line(nxt):
                end = matches[j].start()
                break

        rule_text = style_text[start:end].strip()
        triggers = _keyword_to_triggers(keyword)
        if triggers:
            rules.append((triggers, rule_text))

    return rules


def extract_matching_rules(style_text: str, english_term: str) -> str:
    """Extract only the style guide rules whose keywords match the English term.

    Returns the concatenated rule texts, or empty string if nothing matches.
    """
    if not style_text or not english_term:
        return ""

    rules = _parse_style_rules(style_text)
    term_lower = english_term.lower()

    matched = []
    for triggers, rule_text in rules:
        if any(t in term_lower for t in triggers):
            matched.append(rule_text)

    return "\n\n".join(matched)


# ── Prompt builders ─────────────────────────────────────────────────────


def build_system_prompt() -> str:
    """Return the system prompt for Qwen 122B translation."""
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
    #   Keep labels in English to prevent them bleeding into output.
    #   Presented as concise reference, not a template.
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
    #   Short, directly relevant pairs only. These anchor the model
    #   on existing terminology conventions.
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

    # ── 4. Style-guide excerpt ────────────────────────────────────
    #   The old 400-char limit cut off before the rules table.
    #   Use keyword matching to inject only relevant rules, keeping
    #   the prompt focused.  Fall back to a longer excerpt if no
    #   rules match (so the model still gets some guidance).
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
    #   End with "Estonian:" so the model continues directly with
    #   the translation. Remind conciseness one final time.
    sections.append(
        f"English: {english_term}\n"
        "Respond with ONLY the Estonian translation (one term, no extras).\n"
        "Estonian:"
    )

    return "\n\n".join(sections)
