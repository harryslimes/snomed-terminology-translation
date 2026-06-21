"""Exemplar embeddings: per-source Qdrant collections + lookup cache.

The wired exemplars datasource is the **source of truth**. Embeddings live in
a Qdrant collection **per source**, named
``exemplars_<source_id>_<lang>_<digest>`` where the digest covers the CSV's
content and the embedder model — so re-ingesting the source automatically
calls for a fresh index (stale sibling collections are dropped after a
successful re-index), while unchanged sources keep their embeddings across
runs forever.

Indexing belongs to the *source's* lifecycle: trigger it from the Sources page
in the wizard or via ``python -m snomed_translation.index_exemplars --source <id>``.
The translate stage verifies the collection at run time and only falls back to
indexing inline (loudly) when it's missing.

The on-disk lookup cache (``lookup_cache.<collection>.json`` + ``.meta.json``)
is purely a performance layer: keyed by collection name, so both re-wiring the
exemplars source *and* changing its content invalidate it; uncovered rows are
looked up live and appended.

Anything unservable — Qdrant down, source CSV missing, no en/target columns —
raises ``ExemplarError`` so callers fail loudly instead of silently
translating with empty exemplars.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Iterator

from snomed_translation.config import DataSourceSpec, PipelineConfig

log = logging.getLogger(__name__)


class ExemplarError(Exception):
    """Raised when exemplars can't be served from the wired source."""


# ---------------------------------------------------------------------------
# Source pairs + collection naming
# ---------------------------------------------------------------------------

# (path, mtime, size) -> content digest, so the sources page doesn't re-hash
# a 50 MB CSV on every render.
_DIGEST_CACHE: dict[tuple, str] = {}


def _csv_digest(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _DIGEST_CACHE:
        h = hashlib.blake2b(digest_size=4)
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _DIGEST_CACHE[key] = h.hexdigest()
    return _DIGEST_CACHE[key]


def _source_roles(spec: DataSourceSpec) -> dict[str, str]:
    """role->column for the source, or raise if it can't serve exemplars."""
    from snomed_translation.graph import source_schema

    schema = source_schema(spec)
    if not schema["built"]:
        raise ExemplarError(
            f"exemplars source {spec.id!r} is not built — expected CSV at "
            f"{spec.output_csv}")
    roles = schema["roles"]
    missing = [r for r in ("en", "target") if r not in roles]
    if missing:
        raise ExemplarError(
            f"exemplars source {spec.id!r} lacks role column(s) {missing} "
            f"(columns: {schema['columns']})")
    return roles


def iter_source_pairs(spec: DataSourceSpec) -> Iterator[tuple[str, str]]:
    """(English, target) pairs from the source CSV, via its role mapping."""
    roles = _source_roles(spec)
    with Path(spec.output_csv).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            en = (row.get(roles["en"]) or "").strip()
            tgt = (row.get(roles["target"]) or "").strip()
            if en and tgt:
                yield en, tgt


def collection_prefix(spec: DataSourceSpec, language_code: str) -> str:
    return f"exemplars_{spec.id}_{language_code}_"


def source_collection(spec: DataSourceSpec, language_code: str,
                      embedder_model: str) -> str:
    """Deterministic collection name: changes iff the CSV content, the
    embedder model, or the language changes."""
    content = _csv_digest(Path(spec.output_csv))
    h = hashlib.blake2b(f"{embedder_model}|{content}".encode("utf-8"),
                        digest_size=4).hexdigest()
    return f"{collection_prefix(spec, language_code)}{h}"


# ---------------------------------------------------------------------------
# Status + indexing (the source-lifecycle API)
# ---------------------------------------------------------------------------


def collection_status(spec: DataSourceSpec, language_code: str,
                      embedder_model: str, qdrant_url: str) -> dict:
    """Embedding status for the sources UI.

    ``state`` is one of: ``ready`` / ``partial`` / ``missing`` (collection
    absent), ``not_built`` (no CSV yet), ``no_pairs`` (CSV lacks en/target
    columns), ``unreachable`` (Qdrant down).
    """
    try:
        expected = sum(1 for _ in iter_source_pairs(spec))
        collection = source_collection(spec, language_code, embedder_model)
    except ExemplarError as exc:
        state = "not_built" if "not built" in str(exc) else "no_pairs"
        return {"state": state, "detail": str(exc)}
    try:
        from agent.qdrant_store import QdrantHybridStore
        store = QdrantHybridStore(url=qdrant_url)
        existing = {c.name for c in store.client.get_collections().collections}
        points = 0
        if collection in existing:
            points = int(store.client.count(collection_name=collection,
                                            exact=True).count)
    except Exception as exc:
        return {"state": "unreachable", "collection": collection,
                "expected": expected, "detail": str(exc)}
    state = ("ready" if points >= expected and expected > 0
             else "partial" if points > 0 else "missing")
    return {"state": state, "collection": collection,
            "points": points, "expected": expected}


def index_source(spec: DataSourceSpec, language_code: str, qdrant_url: str,
                 bgem3_model: str = "BAAI/bge-m3", embedder=None) -> dict:
    """Embed + index the source's pairs into its per-source collection.

    Resumes an interrupted index by point count (sequential ids); after a
    complete index, drops stale sibling collections (same source, older
    content digest). Returns ``{collection, points}``. Pass ``embedder`` to
    reuse an already-loaded BGE-M3 instance.
    """
    from agent.qdrant_store import BGEM3Config, BGEM3Embedder, QdrantHybridStore

    pairs = list(iter_source_pairs(spec))
    if not pairs:
        raise ExemplarError(
            f"source {spec.id!r} has no usable (en, target) rows")
    collection = source_collection(spec, language_code, bgem3_model)
    direction = f"EN->{language_code.upper()}"

    store = QdrantHybridStore(url=qdrant_url)
    try:
        existing = {c.name for c in store.client.get_collections().collections}
    except Exception as exc:
        raise ExemplarError(f"cannot reach Qdrant at {qdrant_url}: {exc}") from exc

    if embedder is None:
        embedder = BGEM3Embedder(BGEM3Config(model_name=bgem3_model))
    skip = 0
    if collection in existing:
        skip = int(store.client.count(collection_name=collection,
                                      exact=True).count)
        if skip >= len(pairs):
            log.info("Collection %r already complete (%d points)",
                     collection, skip)
            _drop_stale_siblings(store, spec, language_code, collection)
            return {"collection": collection, "points": skip}
        log.info("Collection %r incomplete (%d/%d) — resuming",
                 collection, skip, len(pairs))
    else:
        log.info("Indexing %d pairs from %r into %r",
                 len(pairs), spec.id, collection)
        store.recreate_hybrid_collection(collection, embedder.dense_size)

    batch_size = embedder.config.batch_size
    for start in range(skip, len(pairs), batch_size):
        batch = pairs[start:start + batch_size]
        dense, sparse = embedder.encode_documents([en for en, _ in batch])
        store.upsert_hybrid_points(
            collection,
            list(range(start + 1, start + 1 + len(batch))),
            dense, sparse,
            [{"source": spec.id, "direction": direction, "lang": "en",
              "text": en, "translation": tgt} for en, tgt in batch])
        done = start + len(batch)
        log.info("  indexed %d/%d", done, len(pairs))

    _drop_stale_siblings(store, spec, language_code, collection)
    return {"collection": collection, "points": len(pairs)}


def _drop_stale_siblings(store, spec: DataSourceSpec, language_code: str,
                         keep: str) -> None:
    """Delete older collections for the same source (superseded content)."""
    prefix = collection_prefix(spec, language_code)
    for c in store.client.get_collections().collections:
        if c.name.startswith(prefix) and c.name != keep:
            log.info("Dropping stale exemplar collection %r", c.name)
            store.client.delete_collection(collection_name=c.name)


# ---------------------------------------------------------------------------
# Run-time path (translate stage)
# ---------------------------------------------------------------------------


def _pool_source(cfg: PipelineConfig) -> DataSourceSpec:
    """The single source wired to the exemplars port."""
    selected = set(cfg.sources.pool.sources)
    picked = [s for s in cfg.sources.data_sources
              if s.enabled and (not selected or s.id in selected)]
    if not picked:
        raise ExemplarError(
            "no exemplar source selected — wire a datasource to the "
            "translate node's exemplars port")
    if len(picked) > 1:
        raise ExemplarError(
            f"multiple exemplar sources selected ({[s.id for s in picked]}) — "
            "exemplar collections are per-source; wire exactly one")
    return picked[0]


def _cache_paths(cfg: PipelineConfig, collection: str) -> tuple[Path, Path]:
    base = Path(cfg.paths.lookup_cache)
    cache = base.with_name(f"{base.stem}.{collection}.json")
    return cache, cache.with_suffix(".meta.json")


def ensure_exemplars(cfg: PipelineConfig, rows: list[dict]) -> dict:
    """sctid -> top-N ``[en, target]`` pairs for every row in ``rows``.

    Serves from the per-collection cache when fresh; otherwise looks up live
    against the wired source's collection — indexing it first (loudly) if the
    Sources page hasn't done so yet. Raises ExemplarError when unservable.
    """
    spec = _pool_source(cfg)
    bgem3_model = cfg.qdrant.bgem3.model_name
    collection = (cfg.qdrant.exemplar_collection
                  or source_collection(spec, cfg.language.code, bgem3_model))
    topn = cfg.translation.lookup_topn
    cache_path, meta_path = _cache_paths(cfg, collection)

    cache: dict[str, list] = {}
    if cache_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        if meta.get("collection") == collection and \
                int(meta.get("topn") or 0) >= topn:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            log.info("Exemplar cache %s: %d entries", cache_path.name, len(cache))
        else:
            log.info("Exemplar cache %s is stale (%s) — ignoring",
                     cache_path.name, meta)
            cache = {}

    missing = [r for r in rows if r["sctid"] not in cache]
    if not missing:
        return cache

    log.info("Live exemplar lookup for %d term(s) (collection %r, qdrant %s)",
             len(missing), collection, cfg.qdrant.url)
    try:
        from agent.qdrant_store import (
            BGEM3Config, BGEM3Embedder, QdrantHybridStore, direction_filter,
        )
        from scripts.translation.translate_korean_with_lookup import lookup_pairs
    except ImportError as exc:
        raise ExemplarError(f"exemplar lookup deps unavailable: {exc}") from exc

    store = QdrantHybridStore(url=cfg.qdrant.url)
    try:
        existing = {c.name for c in store.client.get_collections().collections}
    except Exception as exc:
        raise ExemplarError(
            f"cannot reach Qdrant at {cfg.qdrant.url}: {exc}") from exc

    embedder = BGEM3Embedder(BGEM3Config(model_name=bgem3_model))

    if cfg.qdrant.exemplar_collection:
        # Pinned name with unknown provenance — we can't (re)build it.
        if collection not in existing:
            raise ExemplarError(
                f"pinned exemplar collection {collection!r} does not exist in "
                f"Qdrant at {cfg.qdrant.url}")
    else:
        complete = False
        if collection in existing:
            points = int(store.client.count(collection_name=collection,
                                            exact=True).count)
            complete = points >= sum(1 for _ in iter_source_pairs(spec))
        if not complete:
            log.warning(
                "Exemplar embeddings for %r are missing/incomplete "
                "(collection %r) — generating them now. Tip: pre-generate "
                "from the wizard's Sources page (or `python -m "
                "snomed_translation.index_exemplars --source %s`) to keep translate "
                "runs fast.", spec.id, collection, spec.id)
            index_source(spec, cfg.language.code, cfg.qdrant.url, bgem3_model,
                         embedder=embedder)
    filt = direction_filter(f"EN->{cfg.language.code.upper()}")
    for i, row in enumerate(missing, 1):
        cache[row["sctid"]] = lookup_pairs(
            embedder, store, collection, row["preferred_term"], topn, filt)
        if i % 100 == 0:
            log.info("  lookups: %d/%d", i, len(missing))

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False),
                          encoding="utf-8")
    meta_path.write_text(
        json.dumps({"collection": collection, "topn": topn}),
        encoding="utf-8")
    log.info("Exemplar cache updated: %s (%d entries)", cache_path.name,
             len(cache))
    return cache
