"""Unit tests for the generate_text node's pure templating/assembly logic
(no Claude Agent SDK call — that's covered by a manual smoke run)."""
from __future__ import annotations

import pytest

from pipelines.context import RunContext
from snomed_translation.generate import (
    assemble_context,
    render_prompt,
    resolve_prompt,
)


def _write_template(d, tid, body, version="abc123"):
    (d / f"{tid}.md").write_text(body, encoding="utf-8")
    (d / f"{tid}.json").write_text(
        f'{{"id":"{tid}","kind":"induction","current_version":"{version}"}}',
        encoding="utf-8")


def test_assemble_concats_wired_inputs_and_files(tmp_path):
    f = tmp_path / "corpus.md"
    f.write_text("FILE_BODY", encoding="utf-8")
    block, per_port = assemble_context(
        {"context": "WIRED"}, [str(f), ""], max_chars=0)
    assert "WIRED" in block and "FILE_BODY" in block
    assert per_port["context"] == "WIRED"


def test_assemble_reads_path_valued_input(tmp_path):
    f = tmp_path / "in.txt"
    f.write_text("FROM_PATH", encoding="utf-8")
    block, per_port = assemble_context({"context": str(f)}, [], max_chars=0)
    assert per_port["context"] == "FROM_PATH"
    assert "FROM_PATH" in block


def test_assemble_truncates_to_max_chars():
    block, _ = assemble_context({"context": "x" * 1000}, [], max_chars=100)
    assert block.startswith("x" * 100)
    assert "truncated" in block


def test_assemble_missing_context_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        assemble_context({}, [str(tmp_path / "nope.md")], max_chars=0)


def test_render_substitutes_context_and_ports():
    out = render_prompt("A {{context}} B {{extra}}", "CTX", {"extra": "E"})
    assert out == "A CTX B E"


def test_render_unknown_token_raises():
    with pytest.raises(KeyError):
        render_prompt("{{nope}}", "CTX", {})


def test_resolve_prompt_inline_wins_when_no_template():
    tmpl, tid, ver = resolve_prompt({"prompt": "hi {{context}}"},
                                    RunContext(run_id="r"))
    assert tmpl == "hi {{context}}" and tid is None and ver is None


def test_resolve_prompt_from_env_dir(tmp_path, monkeypatch):
    _write_template(tmp_path, "ind", "BODY {{context}}", "v1")
    monkeypatch.setenv("WIZARD_PROMPTS_DIR", str(tmp_path))
    tmpl, tid, ver = resolve_prompt({"prompt_template": "ind"},
                                    RunContext(run_id="r"))
    assert tmpl == "BODY {{context}}" and tid == "ind" and ver == "v1"


def test_resolve_prompt_from_configs_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("WIZARD_PROMPTS_DIR", raising=False)
    pd = tmp_path / "prompts"
    pd.mkdir()
    _write_template(pd, "ind", "CFG BODY", "v2")
    tmpl, tid, ver = resolve_prompt(
        {"prompt_template": "ind"}, RunContext(run_id="r", configs_dir=tmp_path))
    assert tmpl == "CFG BODY" and tid == "ind" and ver == "v2"


def test_resolve_prompt_missing_template_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("WIZARD_PROMPTS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        resolve_prompt({"prompt_template": "nope"}, RunContext(run_id="r"))
