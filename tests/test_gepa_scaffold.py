"""Phase 3b: GEPA renders through production's EXACT scaffold. The message
construction is dspy-free and must be byte-identical to the translate stage's
render (that's the whole point — closing the fidelity gap)."""
from __future__ import annotations

import pytest

from pipelines.prompts import render
from snomed_translation.config import PromptTemplates
from snomed_translation.gepa_scaffold import parse_korean, scaffold_messages
from snomed_translation.stages.translate import script_name


def test_scaffold_messages_match_production_render():
    pt = PromptTemplates()
    guide, exemplars, english = "STYLE RULES", "PAIRS-TABLE", "Echography of kidney"
    lang, code = "Korean", "ko"
    msgs = scaffold_messages(
        pt.system, pt.user, language_name=lang,
        language_script_name=script_name(code, lang), style_guide=guide,
        exemplars=exemplars, english=english)
    # exactly what the translate stage builds:
    prod_system = render(pt.system, {
        "language_name": lang, "language_script_name": script_name(code, lang),
        "style_guide": guide})
    prod_user = render(pt.user, {
        "paired_translations": exemplars, "english": english,
        "language_name": lang})
    assert msgs == [{"role": "system", "content": prod_system},
                    {"role": "user", "content": prod_user}]


def test_parse_korean_strips_like_production():
    assert parse_korean('  "신장 초음파 검사" ') == {"korean": "신장 초음파 검사"}
    assert parse_korean("") == {"korean": ""}


def test_production_adapter_builds_and_formats_under_dspy():
    dspy = pytest.importorskip("dspy")  # only in the optimise venv
    from snomed_translation.gepa_scaffold import make_production_adapter
    adapter = make_production_adapter(
        "sys {{style_guide}} ({{language_name}}/{{language_script_name}})",
        "u {{paired_translations}} {{english}}",
        language_name="Korean", language_script_name="Hangul")
    assert isinstance(adapter, dspy.Adapter)
    sig = type("Sig", (), {"instructions": "GUIDE"})()
    msgs = adapter.format(sig, [], {"exemplars": "P", "english_term": "E"})
    assert msgs[0]["role"] == "system" and "GUIDE" in msgs[0]["content"]
    assert msgs[1]["content"] == "u P E"
    assert adapter.parse(sig, ' "X" ') == {"korean": "X"}
