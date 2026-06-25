"""Build + query a semantic index over the SNOMED terminology.

This is the building block at the heart of the back-translation confidence
method: index every concept's English surface forms (FSN + synonyms) into Qdrant
so a back-translated English term can be linked back to the SNOMED concept it
came from. One point per *surface form* (all sharing the concept's ``sctid``) so
a query like "heart attack" matches the "Heart attack" synonym directly.

It reuses the project's existing embedding/vector plumbing wholesale — the
BGE-M3 embedder (dense + sparse) and the hybrid Qdrant store (dense COSINE +
sparse, RRF fusion) — so a query can be dense, lexical, or hybrid against the
*same* index. The index is an artifact: its collection name is a deterministic
hash of (release id + embedding model), and ``build_index`` returns a manifest
recording exactly that, so a rebuild with a different model is reproducible and
lands in a distinct collection.

Heavy deps (torch / FlagEmbedding / qdrant) are imported lazily so importing
this module (e.g. to read the manifest shape) stays cheap.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from snomed_translation.snomed_rf2 import read_concept_terms, release_id

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"


def index_collection_name(release: str, embedding_model: str) -> str:
    """Deterministic Qdrant collection name — changes iff the SNOMED release or
    the embedding model changes (so it doubles as a cache key)."""
    h = hashlib.blake2b(f"{release}|{embedding_model}".encode("utf-8"),
                        digest_size=4).hexdigest()
    return f"snomed_idx_{h}"


def build_index(
    release_root: Path | str,
    *,
    qdrant_url: str | None = None,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    scope: set[str] | None = None,
    batch_size: int = 256,
    embedder=None,
    store=None,
) -> dict:
    """Embed concept surface forms (FSN + synonyms) from a local RF2 release and
    upsert them into a hybrid Qdrant collection. Returns the index **manifest**
    (the thing a ``promote`` node registers as a DataObject)."""
    release_root = Path(release_root)
    rel = release_id(release_root)
    collection = index_collection_name(rel, embedding_model)

    if embedder is None:
        from agent.qdrant_store import BGEM3Embedder
        embedder = BGEM3Embedder()
    if store is None:
        from agent.qdrant_store import QdrantHybridStore
        store = QdrantHybridStore(qdrant_url)

    # (sctid, fsn, surface-form text) — one point per surface form.
    items: list[tuple[str, str, str]] = []
    n_concepts = 0
    for ct in read_concept_terms(release_root, scope):
        n_concepts += 1
        for text in ct.texts:
            items.append((ct.sctid, ct.fsn, text))

    dim: int | None = None
    next_id = 1
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        dense, sparse = embedder.encode_documents([t for _, _, t in batch])
        if dim is None:
            dim = len(dense[0])
            store.recreate_hybrid_collection(collection, dim)
        ids = list(range(next_id, next_id + len(batch)))
        next_id += len(batch)
        payloads = [{"sctid": s, "fsn": f, "text": t} for s, f, t in batch]
        store.upsert_hybrid_points(collection, ids, dense, sparse, payloads)

    return {
        "kind": "snomed_index",
        "collection": collection,
        "release_id": rel,
        "embedding_model": embedding_model,
        "vector_dim": dim,
        "n_concepts": n_concepts,
        "n_points": len(items),
        "scope_size": (len(scope) if scope is not None else None),
        "qdrant_url": store.url,
    }


def query_index(
    collection: str,
    text: str,
    *,
    limit: int = 5,
    mode: str = "hybrid",
    qdrant_url: str | None = None,
    embedder=None,
    store=None,
) -> list[dict]:
    """Retrieve the nearest concepts to ``text`` from a built index, deduped to
    one row per concept (best-scoring surface form), best first:
    ``[{sctid, fsn, matched_text, score}]``.

    ``mode`` selects the retrieval strategy against the same hybrid index:
    ``"hybrid"`` (dense + sparse, RRF), ``"dense"`` (embeddings only — the fair
    test for cross-lingual lookup, where the sparse/lexical channel is dead
    weight), or ``"sparse"`` (lexical only)."""
    if mode not in ("hybrid", "dense", "sparse"):
        raise ValueError(f"unknown retrieval mode {mode!r}")
    if embedder is None:
        from agent.qdrant_store import BGEM3Embedder
        embedder = BGEM3Embedder()
    if store is None:
        from agent.qdrant_store import QdrantHybridStore
        store = QdrantHybridStore(qdrant_url)

    dense, sparse = embedder.encode_query(text)
    if mode == "hybrid":
        res = store.hybrid_query(collection, dense, sparse, limit=limit * 4)
    else:
        from agent.qdrant_store import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME
        using = DENSE_VECTOR_NAME if mode == "dense" else SPARSE_VECTOR_NAME
        query = list(dense) if mode == "dense" else sparse
        res = store.client.query_points(
            collection_name=collection, query=query, using=using,
            limit=limit * 4, with_payload=True)
    best: dict[str, dict] = {}
    for p in res.points:
        sctid = (p.payload or {}).get("sctid")
        if sctid is None:
            continue
        if sctid not in best or p.score > best[sctid]["score"]:
            best[sctid] = {"sctid": sctid, "fsn": (p.payload or {}).get("fsn"),
                           "matched_text": (p.payload or {}).get("text"),
                           "score": p.score}
    return sorted(best.values(), key=lambda r: r["score"], reverse=True)[:limit]


def retrieve_concepts(
    collection: str,
    queries: list[tuple[str, str]],
    *,
    limit: int = 5,
    search_depth: int = 25,
    mode: str = "hybrid",
    qdrant_url: str | None = None,
    embedder=None,
    store=None,
) -> list[dict]:
    """Run round-trip lookups for ``queries`` (each ``(original_sctid, query_text)``)
    against a built index. Per query returns the top hit plus, for the *original*
    concept, its rank + score among the results — the raw confidence signal:
    ``recovered``/``correct_rank``≈1 with a high score ⇒ the round trip preserved
    meaning. ``original_sctid`` may be empty when there's no gold to compare to."""
    if embedder is None:
        from agent.qdrant_store import BGEM3Embedder
        embedder = BGEM3Embedder()
    if store is None:
        from agent.qdrant_store import QdrantHybridStore
        store = QdrantHybridStore(qdrant_url)

    rows: list[dict] = []
    for original_sctid, query in queries:
        ranked = query_index(collection, query, limit=max(search_depth, limit),
                             mode=mode, embedder=embedder, store=store)
        top = ranked[0] if ranked else {}
        correct_rank, correct_score = 0, None
        if original_sctid:
            for i, h in enumerate(ranked, 1):
                if str(h["sctid"]) == str(original_sctid):
                    correct_rank, correct_score = i, h["score"]
                    break
        rows.append({
            "sctid": original_sctid,
            "query": query,
            "top_sctid": top.get("sctid"),
            "top_fsn": top.get("fsn"),
            "top_score": round(float(top.get("score", 0.0)), 4),
            "top_text": top.get("matched_text"),
            "correct_rank": correct_rank,
            "correct_score": (round(float(correct_score), 4)
                              if correct_score is not None else ""),
            "recovered": int(bool(original_sctid)
                             and str(top.get("sctid")) == str(original_sctid)),
        })
    return rows
