"""Cross-encoder reranking of SNOMED retrieval candidates.

Retrieval (bi-encoder over the hybrid index) gets the right concept *near* the
top but not always #1 — recall@5 >> recall@1. A cross-encoder reranker
(BAAI/bge-reranker-v2-m3, which pairs with bge-m3 and is multilingual) re-scores
each (query, candidate-surface-form) pair jointly and reorders, pulling the
correct concept up. The model is multilingual, so it can rerank a Korean query
against English candidates directly.
"""
from __future__ import annotations

DEFAULT_RERANKER = "BAAI/bge-reranker-v2-m3"


class Reranker:
    """Thin lazy wrapper over FlagReranker. ``score(pairs)`` -> normalised
    relevance in [0,1] for each ``[query, text]`` pair."""

    def __init__(self, model: str = DEFAULT_RERANKER, use_fp16: bool = True):
        from FlagEmbedding import FlagReranker
        self._rr = FlagReranker(model, use_fp16=use_fp16)

    def score(self, pairs: list[list[str]]) -> list[float]:
        if not pairs:
            return []
        s = self._rr.compute_score(pairs, normalize=True)
        return [float(x) for x in (s if isinstance(s, (list, tuple)) else [s])]


def retrieve_and_rerank(
    collection: str,
    queries: list[tuple[str, str]],
    *,
    top_k: int = 10,
    mode: str = "hybrid",
    reranker: Reranker | None = None,
    embedder=None,
    store=None,
) -> list[dict]:
    """Retrieve the top-``top_k`` candidate concepts for each query, then reorder
    them with the cross-encoder. Returns the same row shape as
    :func:`snomed_index.retrieve_concepts` but with the reranked order — so
    recall@K is measured *after* reranking."""
    from snomed_translation.snomed_index import query_index
    if reranker is None:
        reranker = Reranker()

    rows: list[dict] = []
    for gold, query in queries:
        cands = query_index(collection, query, limit=top_k, mode=mode,
                            embedder=embedder, store=store)
        if not cands:
            rows.append({"sctid": gold, "query": query, "top_sctid": None,
                         "top_fsn": None, "top_score": 0.0, "top_text": None,
                         "correct_rank": 0, "recovered": 0})
            continue
        scores = reranker.score([[query, c["matched_text"] or c["fsn"] or ""]
                                 for c in cands])
        for c, sc in zip(cands, scores):
            c["rerank_score"] = sc
        cands.sort(key=lambda c: c["rerank_score"], reverse=True)
        correct_rank = 0
        if gold:
            correct_rank = next((i for i, c in enumerate(cands, 1)
                                 if str(c["sctid"]) == str(gold)), 0)
        top = cands[0]
        rows.append({
            "sctid": gold, "query": query, "top_sctid": top["sctid"],
            "top_fsn": top["fsn"], "top_score": round(top["rerank_score"], 4),
            "top_text": top["matched_text"], "correct_rank": correct_rank,
            "recovered": int(bool(gold) and str(top["sctid"]) == str(gold)),
        })
    return rows
