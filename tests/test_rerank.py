"""Cross-encoder reranking (model mocked)."""
from __future__ import annotations

from pathlib import Path

from pipelines.context import RunContext
from snomed_translation import functions, rerank, snomed_index


class _FakeReranker:
    """Scores a (query, text) pair by whether the text marks the gold."""
    def score(self, pairs):
        return [1.0 if "GOLD" in t else 0.1 for _, t in pairs]


def test_retrieve_and_rerank_promotes_gold(monkeypatch):
    # retrieval ranks the gold 3rd; the reranker pulls it to #1
    monkeypatch.setattr(snomed_index, "query_index", lambda col, q, **k: [
        {"sctid": "A", "fsn": "A", "matched_text": "alpha", "score": 0.9},
        {"sctid": "B", "fsn": "B", "matched_text": "beta", "score": 0.8},
        {"sctid": "GOLD", "fsn": "G", "matched_text": "GOLD term", "score": 0.7}])
    rows = rerank.retrieve_and_rerank(
        "c", [("GOLD", "q")], reranker=_FakeReranker(),
        embedder=object(), store=object())
    r = rows[0]
    assert r["top_sctid"] == "GOLD" and r["recovered"] == 1 and r["correct_rank"] == 1


def test_rerank_node(tmp_path, monkeypatch):
    q = tmp_path / "q.csv"
    q.write_text("sctid,query\nGOLD,x\n", encoding="utf-8")
    monkeypatch.setattr("snomed_translation.rerank.Reranker", lambda *a, **k: object())
    monkeypatch.setattr("snomed_translation.rerank.retrieve_and_rerank",
                        lambda col, qs, **k: [
                            {"sctid": "GOLD", "query": "x", "top_sctid": "GOLD",
                             "top_fsn": "G", "top_score": 1.0, "top_text": "GOLD",
                             "correct_rank": 1, "recovered": 1}])
    ctx = RunContext(run_id="t", log_dir=tmp_path / "run")
    res = functions.rerank(ctx, {"index": {"collection": "c"}, "queries": str(q)},
                           {"top_k": 10})
    assert res.ok and res.metrics["recovered_pct"] == 100.0
    assert Path(res.outputs["matches"]).exists()
    assert functions.rerank(ctx, {}, {}).ok is False    # nothing wired


def test_registered():
    assert any(s.name == "rerank" for s in functions.specs())
