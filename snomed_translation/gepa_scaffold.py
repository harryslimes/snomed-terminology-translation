"""Make GEPA optimise inside PRODUCTION's exact prompt scaffold (design §13, Phase
3b — close the last fidelity gap).

By default GEPA/DSPy wraps the evolvable guide in DSPy's own auto-scaffold
("Given the fields …, produce …"), which differs from what the translate stage
sends. A custom DSPy adapter fixes that: GEPA still mutates the guide
(``signature.instructions``), but every LM call during optimisation renders the
**same** system/user turns production does — via the one shared
``pipelines.prompts.render`` — so the guide is tuned in the context it runs.

The message-construction is a plain function (``scaffold_messages``) with no DSPy
dependency, so it's unit-testable byte-identical to the production render; the
thin ``dspy.Adapter`` subclass is built lazily in :func:`make_production_adapter`.
"""
from __future__ import annotations

from typing import Any


def scaffold_messages(system_body: str, user_body: str, *, language_name: str,
                      language_script_name: str, style_guide: str,
                      exemplars: str, english: str) -> list[dict[str, str]]:
    """The production chat turns: system = the instruction template with the guide
    slotted in; user = the data envelope. Identical to the translate stage's
    render, so GEPA optimises the exact production prompt."""
    from pipelines.prompts import render
    system = render(system_body, {
        "language_name": language_name,
        "language_script_name": language_script_name,
        "style_guide": style_guide,
    })
    user = render(user_body, {
        "paired_translations": exemplars,
        "english": english,
        "language_name": language_name,
    })
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_korean(completion: str) -> dict[str, str]:
    """Extract the translation the way the production translator does."""
    ko = (completion or "").strip().strip('"').strip("'").strip()
    return {"korean": ko}


def make_production_adapter(system_body: str, user_body: str, *,
                            language_name: str, language_script_name: str):
    """A ``dspy.Adapter`` that renders production's exact scaffold. ``dspy`` is
    imported lazily (only present in the optimise venv). The evolvable guide is
    ``signature.instructions`` (what GEPA mutates); the exemplars + term come from
    the DSPy input fields (``exemplars`` / ``english_term``)."""
    import dspy

    class ProductionScaffoldAdapter(dspy.Adapter):
        def format(self, signature, demos, inputs: dict[str, Any]
                   ) -> list[dict[str, Any]]:
            return scaffold_messages(
                system_body, user_body,
                language_name=language_name,
                language_script_name=language_script_name,
                style_guide=signature.instructions or "",
                exemplars=inputs.get("exemplars", ""),
                english=inputs.get("english_term", ""))

        def parse(self, signature, completion: str) -> dict[str, Any]:
            return parse_korean(completion)

    return ProductionScaffoldAdapter()
