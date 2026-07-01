"""Phase 3 of universalisation: GEPA seeds from a store template and writes its
evolved result back as a gepa-provenance CHILD template (lineage), guarding
required slots. The GEPA compile itself needs a served model + BGE-M3 lookup
cache (infra), so here we test the store-write + slot-guard logic that
`optimize.run` performs at the end, in isolation."""
from __future__ import annotations

from pipelines.prompts import (
    PromptTemplate,
    load_template,
    missing_required,
    save_template,
)
from snomed_translation.stages.optimize import _prompts_dir, _slug


def test_gepa_child_written_with_provenance_and_parent(tmp_path):
    seed = save_template(tmp_path, PromptTemplate(
        id="translate_system", kind="translate_system",
        body="Rules... {{style_guide}}",
        variables=[{"name": "style_guide", "required": True}]))
    evolved = "Better rules... {{style_guide}}"          # kept the required slot
    assert missing_required(evolved, seed.required_var_names()) == []

    child_id = _slug(f"{seed.id}__gepa_run1")
    save_template(tmp_path, PromptTemplate(
        id=child_id, kind=seed.kind, body=evolved, provenance="gepa",
        parent=seed.id, tags=list(seed.tags)))

    child = load_template(tmp_path, child_id)
    assert child.provenance == "gepa"
    assert child.parent == "translate_system"      # lineage edge
    assert child.body == evolved


def test_guard_flags_evolved_body_that_dropped_a_required_slot():
    seed = PromptTemplate(
        id="translate_system", kind="translate_system", body="{{style_guide}}",
        variables=[{"name": "style_guide", "required": True}])
    evolved_bad = "Rules with the slot removed"          # dropped {{style_guide}}
    assert missing_required(evolved_bad, seed.required_var_names()) == ["style_guide"]


def test_prompts_dir_prefers_env(monkeypatch):
    monkeypatch.setenv("WIZARD_PROMPTS_DIR", "/some/dir")
    assert _prompts_dir() == "/some/dir"
    monkeypatch.delenv("WIZARD_PROMPTS_DIR")
    assert _prompts_dir() == "configs/prompts"
