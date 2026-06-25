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


def test_build_snomed_index_registered():
    from snomed_translation.functions import specs
    spec = next((s for s in specs() if s.name == "build_snomed_index"), None)
    assert spec is not None and spec.category == "index"
    assert [o.name for o in spec.outputs] == ["index"]
    assert {p.name for p in spec.params} >= {"rf2_root", "embedding_model"}
