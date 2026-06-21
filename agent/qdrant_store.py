from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Iterable, Sequence

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client import models as qmodels

try:
    import torch
except Exception:  # pragma: no cover - torch import may fail in some envs
    torch = None

try:
    from FlagEmbedding import BGEM3FlagModel
except Exception:  # pragma: no cover - handled at runtime with a clear error
    BGEM3FlagModel = None


logger = logging.getLogger("snomed.qdrant")


DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r. Using default %d.", name, raw, default)
        return default


@dataclass
class BGEM3Config:
    model_name: str = os.getenv("BGE_MODEL_NAME", "BAAI/bge-m3")
    batch_size: int = _get_env_int("BGE_BATCH_SIZE", 256)
    max_length: int = 2048
    top_k_sparse: int = 512


class BGEM3Embedder:
    """
    BGE-M3 embedder that returns both dense and sparse (lexical) vectors.
    """

    def __init__(self, config: BGEM3Config | None = None) -> None:
        if BGEM3FlagModel is None:
            raise RuntimeError(
                "FlagEmbedding is not installed. Install it with: pip install FlagEmbedding"
            )
        self.config = config or BGEM3Config()

        use_fp16 = bool(torch and torch.cuda.is_available())
        logger.info(
            "Loading BGE-M3 model '%s' (fp16=%s, batch_size=%d).",
            self.config.model_name,
            use_fp16,
            self.config.batch_size,
        )
        self.model = BGEM3FlagModel(self.config.model_name, use_fp16=use_fp16)

        # Cache dense size for collection creation.
        probe = self.model.encode(
            ["probe"],
            batch_size=1,
            max_length=self.config.max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        dense_vec = probe["dense_vecs"][0]
        self.dense_size = int(len(dense_vec))
        logger.info("Detected dense vector size: %d.", self.dense_size)

    def _encode(self, texts: Sequence[str]) -> dict:
        return self.model.encode(
            list(texts),
            batch_size=self.config.batch_size,
            max_length=self.config.max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

    def _lexical_to_sparse(self, lexical_weights: dict) -> qmodels.SparseVector:
        if not lexical_weights:
            return qmodels.SparseVector(indices=[], values=[])

        # Keep the highest-weight terms only to control payload size.
        items = sorted(lexical_weights.items(), key=lambda kv: kv[1], reverse=True)
        if self.config.top_k_sparse > 0:
            items = items[: self.config.top_k_sparse]

        indices: list[int] = []
        values: list[float] = []
        for key, value in items:
            try:
                idx = int(key)
            except Exception:
                # Some versions may return string keys that are not numeric.
                # Skip such entries rather than failing the whole batch.
                continue
            indices.append(idx)
            values.append(float(value))

        return qmodels.SparseVector(indices=indices, values=values)

    def encode_documents(
        self, texts: Sequence[str]
    ) -> tuple[list[list[float]], list[qmodels.SparseVector]]:
        encoded = self._encode(texts)
        dense = np.asarray(encoded["dense_vecs"], dtype=np.float32).tolist()
        sparse = [self._lexical_to_sparse(w) for w in encoded.get("lexical_weights", [])]
        return dense, sparse

    def encode_query(self, text: str) -> tuple[list[float], qmodels.SparseVector]:
        dense, sparse = self.encode_documents([text])
        return dense[0], sparse[0]


class QdrantHybridStore:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        logger.info("Connecting to Qdrant at %s.", self.url)
        self.client = QdrantClient(url=self.url)

    def recreate_hybrid_collection(self, name: str, dense_size: int) -> None:
        logger.info("Recreating collection '%s' (dense_size=%d).", name, dense_size)
        self.client.recreate_collection(
            collection_name=name,
            vectors_config={
                DENSE_VECTOR_NAME: qmodels.VectorParams(
                    size=dense_size,
                    distance=qmodels.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: qmodels.SparseVectorParams()
            },
        )

    def upsert_hybrid_points(
        self,
        collection_name: str,
        ids: Sequence[str | int],
        dense_vectors: Sequence[Sequence[float]],
        sparse_vectors: Sequence[qmodels.SparseVector],
        payloads: Sequence[dict],
    ) -> None:
        points = []
        for idx, dense_vec, sparse_vec, payload in zip(
            ids, dense_vectors, sparse_vectors, payloads, strict=False
        ):
            points.append(
                qmodels.PointStruct(
                    id=idx,
                    vector={
                        DENSE_VECTOR_NAME: list(dense_vec),
                        SPARSE_VECTOR_NAME: sparse_vec,
                    },
                    payload=payload,
                )
            )

        self.client.upsert(collection_name=collection_name, points=points)

    def hybrid_query(
        self,
        collection_name: str,
        dense_vector: Sequence[float],
        sparse_vector: qmodels.SparseVector,
        limit: int,
        query_filter: qmodels.Filter | None = None,
        prefetch_factor: int = 4,
    ):
        prefetch_limit = max(limit * prefetch_factor, limit)
        return self.client.query_points(
            collection_name=collection_name,
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            prefetch=[
                qmodels.Prefetch(
                    query=list(dense_vector),
                    using=DENSE_VECTOR_NAME,
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
                qmodels.Prefetch(
                    query=sparse_vector,
                    using=SPARSE_VECTOR_NAME,
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
            ],
            limit=limit,
            with_payload=True,
        )


def direction_filter(direction: str) -> qmodels.Filter:
    return qmodels.Filter(
        must=[qmodels.FieldCondition(key="direction", match=qmodels.MatchValue(value=direction))]
    )


def lang_filter(lang: str) -> qmodels.Filter:
    return qmodels.Filter(must=[qmodels.FieldCondition(key="lang", match=qmodels.MatchValue(value=lang))])
