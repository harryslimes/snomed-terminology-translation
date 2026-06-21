"""
Prompt template for TranslateGemma EN→ET SNOMED CT translation.

Designed to mitigate known failure modes of the 12B quantised model:
  - Language-label prefix artefacts ("Eesti: …")
  - Over-fitting to structural patterns in context (echoing hierarchy
    labels like "Kehaosa" instead of translating the actual anatomy)
  - Format contamination from style-guide examples (colon-separated
    patterns leaking into the translation)
  - Incomplete phonetic adaptation of international terms
"""


def build_prompt(
    english_term: str,
    hierarchy: str = "",
    synonyms: list[str] | None = None,
    parent_concepts: list[str] | None = None,
    related_concepts: list[str] | None = None,
    paired_translations: list[dict] | None = None,
    style_guide_specific: str = "",
) -> str:
    """Return a single user-turn prompt string for TranslateGemma.

    All context sections are optional; when absent they are omitted
    entirely so the prompt stays short and focused.
    """
    sections: list[str] = []

    # ── 1. Task framing ─────────────────────────────────────────────
    #   Emphasise output format up-front so the model anchors on it
    #   before it sees any reference material.
    sections.append(
        "Tõlgi järgnev ingliskeelne SNOMED CT meditsiinitermin eesti keelde.\n"
        "Väljasta AINULT eestikeelne tõlge — ilma seletuste, jutumärkide, "
        "keeleprefiksite ja muude lisadeta.\n"
        "Ära kopeeri hierarhia silte ega näidiskujundeid — tõlgi termin ise."
    )

    # ── 2. The term itself ──────────────────────────────────────────
    sections.append(f"Termin: {english_term}")

    # ── 3. SNOMED graph context ─────────────────────────────────────
    #   Presented as bullet-style factual context, not as a template
    #   to copy from.  Keep labels in English so they cannot bleed
    #   into the Estonian output.
    graph_lines: list[str] = []
    if hierarchy:
        graph_lines.append(f"- Hierarchy: {hierarchy}")
    if synonyms:
        graph_lines.append(f"- Synonyms: {', '.join(synonyms[:5])}")
    if parent_concepts:
        graph_lines.append(f"- Parents: {', '.join(parent_concepts[:5])}")
    if related_concepts:
        graph_lines.append(f"- Related: {', '.join(related_concepts[:5])}")
    if graph_lines:
        sections.append(
            "Kontekst (ainult taustinfoks, ära kopeeri neid silte tõlkesse):\n"
            + "\n".join(graph_lines)
        )

    # ── 4. Paired-translation hints ────────────────────────────────
    #   Only short, directly relevant pairs.  Long passages are
    #   truncated because they overwhelm the small model.
    if paired_translations:
        short_pairs = [
            f"  {p['en']}  →  {p['ee']}"
            for p in paired_translations
            if p.get("en") and p.get("ee") and len(p["en"]) < 80
        ]
        if short_pairs:
            sections.append(
                "Sarnaste terminite olemasolevad tõlked (kasuta viidetena, "
                "ära kopeeri tervikuna):\n" + "\n".join(short_pairs[:5])
            )

    # ── 5. Style-guide excerpt ──────────────────────────────────────
    #   Feed only the hierarchy-specific section and trim it hard.
    #   The general section is omitted because TranslateGemma tends to
    #   parrot formatting patterns rather than internalise rules.
    if style_guide_specific and style_guide_specific != "No specific guidance required.":
        # Strip the section down hard to keep within llama.cpp's 4096
        # context window.  Only the opening paragraph matters for a 12B
        # model — detailed examples cause more harm than good.
        trimmed = style_guide_specific[:250].rsplit("\n", 1)[0]
        sections.append(f"Stiilijuhised sellele hierarhiale:\n{trimmed}")

    # ── 6. Output anchor ───────────────────────────────────────────
    #   Re-state the task and end with "Tõlge:" so the model
    #   continues directly with the Estonian term.
    sections.append(
        f"Tõlgi '{english_term}' eesti keelde. "
        "Rahvusvaheliste sõnade (ravimid, ained) puhul kasuta eesti foneetilist kohandust.\n"
        "Tõlge:"
    )

    return "\n\n".join(sections)
