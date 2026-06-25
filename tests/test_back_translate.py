"""The KO->EN back-translation node (LLM mocked)."""
from __future__ import annotations

from pathlib import Path

from pipelines.context import RunContext
from snomed_translation import back_translate as bt
from snomed_translation import functions


def test_chat_takes_first_line(monkeypatch):
    class _R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": '"Heart attack"\nextra'}}]}
    monkeypatch.setattr(bt.requests, "post", lambda *a, **k: _R())
    assert bt.chat("http://x", "m", "sys", "심장마비") == "Heart attack"


def test_back_translate_node(tmp_path, monkeypatch):
    q = tmp_path / "q.csv"
    q.write_text("sctid,korean\n22298006,심장마비\n73211009,당뇨병\n", encoding="utf-8")
    monkeypatch.setattr("snomed_translation.back_translate.back_translate_terms",
                        lambda terms, **k: ["Heart attack", "Diabetes mellitus"])
    ctx = RunContext(run_id="t", log_dir=tmp_path / "run")
    res = functions.back_translate(
        ctx, {"queries": str(q)},
        {"model_id": "m", "source_col": "korean", "id_col": "sctid"})
    assert res.ok and res.metrics["n"] == 2.0
    out = Path(res.outputs["translations"])
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "sctid,query"
    assert rows[1] == "22298006,Heart attack"

    # clean failures
    assert functions.back_translate(ctx, {}, {"model_id": "m"}).ok is False
    assert "model_id" in functions.back_translate(ctx, {"queries": str(q)}, {}).message


def test_registered():
    s = next((s for s in functions.specs() if s.name == "back_translate"), None)
    assert s is not None and [o.name for o in s.outputs] == ["translations"]
