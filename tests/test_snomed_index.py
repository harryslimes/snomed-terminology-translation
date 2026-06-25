"""The SNOMED index building block — the parts testable without GPU/Qdrant.

(The live embed + Qdrant round-trip is exercised separately against a running
Qdrant + the BGE-M3 embedder; here we lock the deterministic naming + the
manifest/query wiring via fakes.)
"""
from __future__ import annotations

from snomed_translation import snomed_index as si
from snomed_translation.snomed_rf2 import ConceptTerms


def test_collection_name_is_deterministic_and_model_sensitive():
    a = si.index_collection_name("INT_20260101", "BAAI/bge-m3")
    assert a == si.index_collection_name("INT_20260101", "BAAI/bge-m3")
    assert a.startswith("snomed_idx_")
    # a different model OR release -> a different (distinct) collection
    assert a != si.index_collection_name("INT_20260101", "other-model")
    assert a != si.index_collection_name("INT_20251101", "BAAI/bge-m3")


class _FakeEmbedder:
    def encode_documents(self, texts):
        return [[float(len(t)), 1.0] for t in texts], [None] * len(texts)


class _FakeStore:
    url = "http://fake:6333"

    def __init__(self):
        self.created = None
        self.points = []

    def recreate_hybrid_collection(self, name, dim):
        self.created = (name, dim)

    def upsert_hybrid_points(self, collection, ids, dense, sparse, payloads):
        self.points.extend(payloads)


def test_build_index_manifest_and_points(monkeypatch, tmp_path):
    # bypass RF2 reading with a tiny concept set
    monkeypatch.setattr(si, "release_id", lambda root: "INT_TEST")
    monkeypatch.setattr(si, "read_concept_terms", lambda root, scope=None: iter([
        ConceptTerms("22298006", "Myocardial infarction (disorder)",
                     ["Heart attack", "Cardiac infarction"]),
        ConceptTerms("73211009", "Diabetes mellitus (disorder)", []),
    ]))
    store = _FakeStore()
    manifest = si.build_index(tmp_path, embedder=_FakeEmbedder(), store=store)

    assert manifest["release_id"] == "INT_TEST"
    assert manifest["n_concepts"] == 2
    # MI has FSN + 2 synonyms = 3 surface forms; diabetes has just its FSN = 1
    assert manifest["n_points"] == 4
    assert manifest["vector_dim"] == 2
    assert manifest["collection"] == store.created[0]
    assert {p["sctid"] for p in store.points} == {"22298006", "73211009"}
    assert any(p["text"] == "Heart attack" for p in store.points)


def test_build_snomed_index_node(monkeypatch):
    """The function-node runner maps the manifest to outputs/metrics and fails
    cleanly on a bad rf2_root (without loading the embedder)."""
    from snomed_translation import functions, snomed_index

    bad = functions.build_snomed_index(None, {}, {"rf2_root": "/no/such/release"})
    assert bad.ok is False and "not found" in bad.message

    missing = functions.build_snomed_index(None, {}, {})
    assert missing.ok is False and "rf2_root" in missing.message

    monkeypatch.setattr(snomed_index, "build_index", lambda *a, **k: {
        "kind": "snomed_index", "collection": "snomed_idx_x",
        "release_id": "INT_20260101", "embedding_model": "BAAI/bge-m3",
        "vector_dim": 1024, "n_concepts": 15, "n_points": 93,
        "scope_size": None, "qdrant_url": "http://x:6333"})
    monkeypatch.setattr("pathlib.Path.exists", lambda self: True)
    res = functions.build_snomed_index(None, {}, {"rf2_root": "/tmp/rel"})
    assert res.ok is True
    assert res.outputs["index"]["collection"] == "snomed_idx_x"
    assert res.metrics["n_concepts"] == 15.0
    assert "INT_20260101" in res.message


def test_query_index_mode_dispatch():
    import pytest

    class _Res:
        points = []

    class _Client:
        def __init__(self):
            self.using = None

        def query_points(self, collection_name, query, using, limit, with_payload):
            self.using = using
            return _Res()

    class _Store:
        url = "x"

        def __init__(self):
            self.client = _Client()
            self.hybrid_calls = 0

        def hybrid_query(self, *a, **k):
            self.hybrid_calls += 1
            return _Res()

    class _Emb:
        def encode_query(self, text):
            return [0.1, 0.2], object()

    st, em = _Store(), _Emb()
    si.query_index("c", "q", mode="hybrid", embedder=em, store=st)
    assert st.hybrid_calls == 1                       # hybrid -> RRF path
    si.query_index("c", "q", mode="dense", embedder=em, store=st)
    assert st.client.using == "dense"                 # dense -> embeddings only
    si.query_index("c", "q", mode="sparse", embedder=em, store=st)
    assert st.client.using == "sparse"
    with pytest.raises(ValueError, match="unknown retrieval mode"):
        si.query_index("c", "q", mode="bogus", embedder=em, store=st)


def test_retrieve_concepts_signal(monkeypatch):
    # fake the index lookup: "heart attack" -> MI top; "chest pain" -> a different
    # concept (MI not recovered).
    def fake_query(collection, text, **k):
        if "heart attack" in text:
            return [{"sctid": "22298006", "fsn": "MI (disorder)",
                     "matched_text": "Heart attack", "score": 1.0},
                    {"sctid": "84114007", "fsn": "Heart failure", "matched_text": "x", "score": 0.4}]
        return [{"sctid": "29857009", "fsn": "Chest pain", "matched_text": "Chest pain", "score": 1.0},
                {"sctid": "22298006", "fsn": "MI (disorder)", "matched_text": "y", "score": 0.3}]
    monkeypatch.setattr(si, "query_index", fake_query)

    rows = {r["query"]: r for r in si.retrieve_concepts(
        "col", [("22298006", "heart attack"), ("22298006", "chest pain")],
        embedder=object(), store=object())}
    good = rows["heart attack"]
    assert good["recovered"] == 1 and good["correct_rank"] == 1 and good["top_score"] == 1.0
    bad = rows["chest pain"]
    assert bad["recovered"] == 0 and bad["correct_rank"] == 2   # MI only 2nd → low confidence


def test_snomed_retrieve_node(tmp_path, monkeypatch):
    from pipelines.context import RunContext
    from snomed_translation import functions, snomed_index

    q = tmp_path / "q.csv"
    q.write_text("sctid,query\n22298006,heart attack\n", encoding="utf-8")
    # one concept recovered at rank 1, one only at rank 4 (in top-5, not top-1)
    monkeypatch.setattr(snomed_index, "retrieve_concepts", lambda col, qs, **k: [
        {"sctid": "22298006", "query": "heart attack", "top_sctid": "22298006",
         "top_fsn": "MI", "top_score": 1.0, "top_text": "Heart attack",
         "correct_rank": 1, "correct_score": 1.0, "recovered": 1},
        {"sctid": "73211009", "query": "sugar", "top_sctid": "999",
         "top_fsn": "Other", "top_score": 0.6, "top_text": "x",
         "correct_rank": 4, "correct_score": 0.5, "recovered": 0}])
    ctx = RunContext(run_id="t", log_dir=tmp_path / "run")
    res = functions.snomed_retrieve(
        ctx, {"index": {"collection": "snomed_idx_x"}, "queries": str(q)},
        {"id_col": "sctid", "query_col": "query"})
    assert res.ok
    assert res.metrics["recovered_pct"] == 50.0     # recall@1: only one at rank 1
    assert res.metrics["recall_at_5_pct"] == 100.0  # both within top 5
    assert res.metrics["recall_at_3_pct"] == 50.0   # the rank-4 one is outside top 3
    assert (tmp_path / "run" / "snomed_retrieve.csv").exists()

    # clean failure when nothing is wired
    bad = functions.snomed_retrieve(ctx, {}, {})
    assert bad.ok is False and "index" in bad.message


def test_build_snomed_index_registered():
    from snomed_translation.functions import specs
    spec = next((s for s in specs() if s.name == "build_snomed_index"), None)
    assert spec is not None and spec.category == "index"
    assert [o.name for o in spec.outputs] == ["index"]
    assert {p.name for p in spec.params} >= {"rf2_root", "embedding_model"}
