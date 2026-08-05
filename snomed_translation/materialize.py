"""Data materialization for a language project — the from-scratch steps the
wizard deliberately leaves out: build the bilingual **pool**, the disjoint
train/dev/test **eval splits**, and the exemplar **lookup cache** (+ Qdrant
index) a project needs before its flows can run.

Language-agnostic generalizations of the one-off Korean/Spanish data-prep
scripts. Each function is importable (used by :mod:`snomed_translation.orchestrate`
and the ``scripts/data_prep`` CLIs) and returns a small summary dict.

Source shapes supported:

* **Athena OHDSI bundle** — ``CONCEPT.csv`` + ``CONCEPT_SYNONYM.csv`` (tab
  separated). English = ``CONCEPT.concept_name`` for SNOMED-vocabulary
  concepts; target = ``CONCEPT_SYNONYM`` rows in the target language (resolved
  from the bundle's own ``CONCEPT.csv`` ``domain_id=Language`` rows — the ids
  are release-specific, so we never hardcode them). → :func:`build_pool`.
* **RF2 Snapshot** — the ``sct2_Description_*`` + ``der2_cRefset_Language*``
  files. Gold reference = the concept's **Preferred** synonym (tag-free). →
  :func:`build_splits`.
"""
from __future__ import annotations

import csv
import json
import logging
import random
import re
import sys
from pathlib import Path

log = logging.getLogger("snomed_translation.materialize")
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# RF2 metadata concept ids (stable across editions).
_FSN_TYPE = "900000000000003001"
_SYN_TYPE = "900000000000013009"
_PREFERRED = "900000000000548007"
_TAG_RE = re.compile(r"\s*\(([^()]+)\)\s*$")


# --------------------------------------------------------------------------- #
# 1. Bilingual pool from an Athena bundle.
# --------------------------------------------------------------------------- #
def resolve_language_concept_id(bundle: Path, language_name: str) -> str:
    """``language_concept_id`` for ``language_name`` (e.g. "Spanish") from the
    bundle's own ``CONCEPT.csv`` (``domain_id=Language`` → "<name> language").
    Authoritative per release. Raises if not found."""
    target = f"{language_name.strip().lower()} language"
    with (bundle / "CONCEPT.csv").open(encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)
        for row in r:
            if len(row) >= 3 and row[2] == "Language" and row[1].strip().lower() == target:
                return row[0]
    raise ValueError(
        f"could not find {language_name!r} among domain_id=Language concepts in "
        f"{bundle / 'CONCEPT.csv'}")


def _load_snomed_concepts(bundle: Path) -> dict[str, tuple[str, str]]:
    """concept_id -> (sctid, english_name) for SNOMED-vocabulary concepts."""
    out: dict[str, tuple[str, str]] = {}
    with (bundle / "CONCEPT.csv").open(encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        header = next(r)
        ci, cn, vi, cc = (header.index(c) for c in
                          ("concept_id", "concept_name", "vocabulary_id", "concept_code"))
        for row in r:
            if len(row) > cc and row[vi] == "SNOMED":
                out[row[ci]] = (row[cc], row[cn])
    return out


def build_pool(*, bundle: Path, out: Path, language_name: str,
               language_concept_id: str | None = None,
               source_tag: str = "SNOMED") -> dict:
    """Build a ``sctid,en,target,source`` bilingual pool CSV by joining a bundle's
    English SNOMED labels with its target-language synonyms. Deduped by
    (sctid, target). Returns ``{pairs, concepts, language_concept_id, out}``."""
    bundle, out = Path(bundle), Path(out)
    lang_id = language_concept_id or resolve_language_concept_id(bundle, language_name)
    concepts = _load_snomed_concepts(bundle)
    log.info("build_pool: %d SNOMED concepts, %s=%s", len(concepts), language_name, lang_id)

    out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str]] = set()
    n = 0
    with (bundle / "CONCEPT_SYNONYM.csv").open(encoding="utf-8", newline="") as f, \
         out.open("w", encoding="utf-8", newline="") as g:
        r = csv.reader(f, delimiter="\t")
        next(r, None)  # concept_id, concept_synonym_name, language_concept_id
        w = csv.writer(g)
        w.writerow(["sctid", "en", "target", "source"])
        for row in r:
            if len(row) < 3 or row[2] != lang_id:
                continue
            hit = concepts.get(row[0])
            if not hit:
                continue
            sctid, en = hit
            target = row[1].strip()
            if not en or not target:
                continue
            key = (sctid, target)
            if key in seen:
                continue
            seen.add(key)
            w.writerow([sctid, en, target, source_tag])
            n += 1
    log.info("build_pool: wrote %d pairs (%d concepts) -> %s",
             n, len({s for s, _ in seen}), out)
    return {"pairs": n, "concepts": len({s for s, _ in seen}),
            "language_concept_id": lang_id, "out": str(out)}


# --------------------------------------------------------------------------- #
# 2. Disjoint train/dev/test eval splits from an RF2 Snapshot.
# --------------------------------------------------------------------------- #
def _preferred_desc_ids(lang_refset: Path) -> set[str]:
    out: set[str] = set()
    with lang_refset.open(encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)  # id,effectiveTime,active,moduleId,refsetId,referencedComponentId,acceptabilityId
        for row in r:
            if len(row) >= 7 and row[2] == "1" and row[6] == _PREFERRED:
                out.add(row[5])
    return out


def _concept_gold(desc_file: Path, pref_ids: set[str],
                  language_code: str) -> tuple[dict[str, str], dict[str, str]]:
    """(conceptId -> preferred synonym term (tag-free), conceptId -> FSN tag)."""
    pt: dict[str, str] = {}
    tag: dict[str, str] = {}
    with desc_file.open(encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter="\t")
        next(r, None)  # id,effectiveTime,active,moduleId,conceptId,languageCode,typeId,term,caseSig
        for row in r:
            if len(row) < 8 or row[2] != "1" or row[5] != language_code:
                continue
            desc_id, cid, type_id, term = row[0], row[4], row[6], row[7].strip()
            if type_id == _FSN_TYPE and cid not in tag:
                m = _TAG_RE.search(term)
                if m:
                    tag[cid] = m.group(1)
            elif type_id == _SYN_TYPE and desc_id in pref_ids and cid not in pt:
                pt[cid] = term
    return pt, tag


def _find_rf2_files(rf2_snapshot: Path) -> tuple[Path, Path]:
    """Locate the Description + Language-refset snapshot files (national-ext or
    International-edition naming)."""
    desc = next((p for pat in ("Terminology/sct2_Description_*Snapshot*.txt",
                               "**/sct2_Description_*Snapshot*.txt")
                 for p in sorted(rf2_snapshot.glob(pat))), None)
    lang = next((p for pat in ("Refset/Language/der2_cRefset_Language*Snapshot*.txt",
                               "**/der2_cRefset_Language*Snapshot*.txt")
                 for p in sorted(rf2_snapshot.glob(pat))), None)
    if desc is None or lang is None:
        raise ValueError(f"could not find Description/Language snapshot under {rf2_snapshot}")
    return desc, lang


def build_splits(*, rf2_snapshot: Path, pool_csv: Path, outdir: Path, code: str,
                 language_code: str | None = None,
                 test: int = 200, dev: int = 100, train: int = 300,
                 seed: int = 42) -> dict:
    """Write disjoint ``{test,dev,train}.csv`` (columns
    ``sctid,preferred_term,<code>_reference,semantic_tag``) — gold = the RF2
    **Preferred** synonym (tag-free), English input = the pool's ``en`` column.
    Concepts must have both to be eligible. Returns a summary dict."""
    rf2_snapshot, pool_csv, outdir = Path(rf2_snapshot), Path(pool_csv), Path(outdir)
    lang_code = language_code or code
    desc, lang = _find_rf2_files(rf2_snapshot)
    log.info("build_splits: desc=%s lang=%s (languageCode=%s)", desc.name, lang.name, lang_code)

    pref = _preferred_desc_ids(lang)
    pt, tag = _concept_gold(desc, pref, lang_code)
    en: dict[str, str] = {}
    with pool_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            en.setdefault(row["sctid"], row["en"])

    ref_col = f"{code}_reference"
    eligible = [
        {"sctid": s, "preferred_term": en[s], ref_col: pt[s],
         "semantic_tag": tag.get(s, "")}
        for s in pt if s in en and en[s] and pt[s]
    ]
    need = test + dev + train
    if len(eligible) < need:
        raise ValueError(f"only {len(eligible)} eligible concepts, need {need}")
    rng = random.Random(seed)
    rng.shuffle(eligible)
    splits = {"test": eligible[:test], "dev": eligible[test:test + dev],
              "train": eligible[test + dev:test + dev + train]}

    outdir.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        p = outdir / f"{name}.csv"
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sctid", "preferred_term", ref_col, "semantic_tag"])
            w.writeheader()
            w.writerows(rows)
    log.info("build_splits: eligible=%d -> test=%d dev=%d train=%d in %s",
             len(eligible), test, dev, train, outdir)
    return {"eligible": len(eligible), "test": test, "dev": dev, "train": train,
            "reference_column": ref_col, "outdir": str(outdir)}


# --------------------------------------------------------------------------- #
# 3. Exemplar index + lookup cache.
# --------------------------------------------------------------------------- #
def _assemble_cfg(code: str, configs_root: str | Path, models_json: str | Path,
                  pool_source: str):
    """A PipelineConfig for ``code`` with ``pool_source`` pinned as the exemplar
    corpus — the same assembly the translate node does."""
    from snomed_translation.assemble import (
        Registries, load_investigation, resolve_environment,
        recipe_from_investigation, assemble_pipeline_config,
    )
    from pipelines.flow import FlowSpec
    configs_root = Path(configs_root)
    flow = FlowSpec.from_file(configs_root / code / "flows" / f"{code}_translate_eval.json")
    inv = load_investigation("project", configs_root / code)
    env = resolve_environment(inv, configs_root / code)
    recipe = recipe_from_investigation(inv)
    regs = Registries.load(models_json=str(models_json),
                           sources_dir=str(configs_root / code / "sources"))
    cfg = assemble_pipeline_config(flow, env, recipe, regs)
    cfg.sources.pool.sources = [pool_source]
    return cfg, regs, env


def index_exemplars(*, code: str, configs_root: str | Path = "configs",
                    models_json: str | Path = "configs/models.json",
                    pool_source: str | None = None) -> dict:
    """Index the pool source's ``(en, target)`` exemplars into Qdrant. Idempotent
    (a complete collection returns immediately). Returns ``{collection, points}``."""
    from pipelines.exemplars import index_source
    pool_source = pool_source or f"{code}_pool"
    cfg, regs, env = _assemble_cfg(code, configs_root, models_json, pool_source)
    spec = regs.sources[pool_source]
    res = index_source(spec, env.language.code, env.qdrant.url,
                       env.qdrant.bgem3.model_name)
    log.info("index_exemplars: %s -> %s (%s points)",
             pool_source, res.get("collection"), res.get("points"))
    return res


def build_lookup_cache(*, code: str, splits_dir: str | Path, out: str | Path,
                       configs_root: str | Path = "configs",
                       models_json: str | Path = "configs/models.json",
                       pool_source: str | None = None,
                       splits=("train", "dev", "test")) -> dict:
    """Build the BGE-M3 exemplar lookup cache (``sctid -> [[en,target],…]``) the
    optimizer requires, covering every concept in the given splits. Writes
    ``out`` and returns ``{entries, out}``."""
    from pipelines.exemplars import ensure_exemplars
    pool_source = pool_source or f"{code}_pool"
    splits_dir, out = Path(splits_dir), Path(out)
    cfg, _, _ = _assemble_cfg(code, configs_root, models_json, pool_source)

    rows = []
    for split in splits:
        p = splits_dir / f"{split}.csv"
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as f:
            rows.extend({"sctid": r["sctid"], "preferred_term": r["preferred_term"]}
                        for r in csv.DictReader(f))
    cache = ensure_exemplars(cfg, rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log.info("build_lookup_cache: %d concepts -> %s (%d entries)",
             len(rows), out, len(cache))
    return {"entries": len(cache), "out": str(out)}
