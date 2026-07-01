"""Phase 2 of universalisation: the translate stage renders via the shared
`pipelines.prompts.render` (double-brace {{token}}), sourcing system/user bodies
from the prompt store (by id) with a safe fallback to the inline config default.
Locks the byte-identical behaviour the migration was proven against."""
from __future__ import annotations

from snomed_translation.config import PromptTemplates
from snomed_translation.stages.translate import _template_body, render_user


def test_render_user_fills_the_data_envelope():
    body = "ex:\n{{paired_translations}}\nEN: {{english}} ({{language_name}})"
    out = render_user(body, paired_translations="P", english="E",
                      language_name="Korean")
    assert out == "ex:\nP\nEN: E (Korean)"


def test_template_body_falls_back_to_default_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("WIZARD_PROMPTS_DIR", str(tmp_path))
    assert _template_body("missing", "DEFAULT") == "DEFAULT"
    assert _template_body(None, "DEFAULT") == "DEFAULT"


def test_template_body_loads_from_store_when_present(tmp_path, monkeypatch):
    (tmp_path / "t.md").write_text("STORE BODY", encoding="utf-8")
    monkeypatch.setenv("WIZARD_PROMPTS_DIR", str(tmp_path))
    assert _template_body("t", "DEFAULT") == "STORE BODY"


def test_config_defaults_use_double_brace_tokens():
    pt = PromptTemplates()
    for tok in ("{{language_name}}", "{{style_guide}}"):
        assert tok in pt.system
    for tok in ("{{paired_translations}}", "{{english}}"):
        assert tok in pt.user
    # default ids point at the seeded store templates
    assert pt.system_template_id == "translate_system"
    assert pt.user_template_id == "translate_user"
