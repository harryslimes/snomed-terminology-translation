"""Agentic end-to-end orchestrator: a directory of dropped resources → a
**runnable, evaluable** language project, in one call.

Sequences the provisioning primitives (:mod:`snomed_translation.provision`) with
the data-materialization steps (:mod:`snomed_translation.materialize`) so adding a
language is one step instead of a dozen manual ones — the gap the wizard
deliberately left (build the pool, the eval splits, the exemplar index + lookup
cache). Pure core (no FastAPI/MCP); the MCP tool ``provision_language_project``
wraps it and adds switcher registration. Every stage records into a **receipt**
(what ran, artifact counts, and explicit **gaps** the caller must fill).

See the ``docs/add-a-language.md`` runbook and
``docs/design/new-language-orchestrator.md``.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from snomed_translation import materialize as mat
from snomed_translation import provision as prov

log = logging.getLogger("snomed_translation.orchestrate")

# ISO code -> the SNOMED language name used to resolve Athena CONCEPT.csv rows.
# Only needed for the Athena pool-build path; extend as new languages appear.
_LANG_NAMES = {
    "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "ko": "Korean", "ja": "Japanese",
    "zh": "Chinese", "ru": "Russian", "ar": "Arabic", "en": "English",
    "et": "Estonian",
}


def inspect_sources(drop_dir: str | Path) -> dict:
    """Classify a dropped resources directory into typed inputs:
    ``{rf2_archive, athena_bundle, pool_csv}`` (any may be None)."""
    drop_dir = Path(drop_dir)
    rf2 = next((p.parent for p in drop_dir.rglob("Snapshot")
                if p.is_dir() and any(p.rglob("sct2_Description_*Snapshot*.txt"))), None)
    athena = next((p for p in [drop_dir, *drop_dir.rglob("*")]
                   if p.is_dir() and (p / "CONCEPT.csv").exists()
                   and (p / "CONCEPT_SYNONYM.csv").exists()), None)
    pool = next((p for p in drop_dir.rglob("pool*.csv")), None)
    return {"rf2_archive": str(rf2) if rf2 else None,
            "athena_bundle": str(athena) if athena else None,
            "pool_csv": str(pool) if pool else None}


def orchestrate_language_project(
    *, code: str, name: str, language_name: str | None = None,
    drop_dir: str | Path | None = None,
    rf2_archive: str | Path | None = None,
    athena_bundle: str | Path | None = None,
    pool_csv: str | Path | None = None,
    configs_root: str | Path = "configs",
    data_root: str | Path = "data/languages",
    style_guide_root: str | Path = "style_guide",
    repo_root: str | Path | None = None,
    models_json: str | Path = "configs/models.json",
    model_key: str = "gemma4-26b",
    template: str = "translation_project",
    test: int = 200, dev: int = 100, train: int = 300, seed: int = 42,
    do_index: bool = True, do_lookup_cache: bool = True,
    overwrite: bool = False,
) -> dict:
    """Provision + materialize a language project from dropped resources.

    Runs, in order: inspect → detect RF2 → scaffold → build/ingest pool →
    register pool → seed template → build splits → index exemplars → build
    lookup cache. Returns a receipt ``{code, name, stages[], gaps[], ...}``;
    steps needing infra (Qdrant/embedder) are recorded as gaps on failure rather
    than aborting the run. Does NOT register the switcher/port — the MCP wrapper
    (or ``finalize_language_project``) does that last.
    """
    receipt: dict = {"code": code, "name": name, "stages": [], "gaps": []}

    def stage(n: str, **info):
        receipt["stages"].append({"stage": n, **info})
        log.info("orchestrate[%s]: %s %s", code, n, info)

    if drop_dir:
        found = inspect_sources(drop_dir)
        rf2_archive = rf2_archive or found["rf2_archive"]
        athena_bundle = athena_bundle or found["athena_bundle"]
        pool_csv = pool_csv or found["pool_csv"]
        stage("inspect", **found)
    language_name = language_name or _LANG_NAMES.get(code)

    configs_root = Path(configs_root)
    data_root = Path(data_root)
    style_guide_root = Path(style_guide_root)
    data_dir = data_root / code

    # 1. Detect the RF2 archive (refset id, edition dir, term count).
    archive = None
    if rf2_archive:
        archive = prov.detect_snomed_archive(rf2_archive, code)
        stage("detect", refset_id=archive.language_refset_id,
              term_count=archive.term_count, warnings=archive.warnings)
    else:
        receipt["gaps"].append("no RF2 archive → eval-gold splits cannot be built")

    # 2. Scaffold the config bundle + data skeleton (+ snomed source if archive).
    scaf = prov.scaffold_language_project(
        code=code, name=name, configs_root=configs_root, data_root=data_root,
        style_guide_root=style_guide_root, repo_root=repo_root,
        archive=archive, overwrite=overwrite)
    stage("scaffold", created=len(scaf.created))

    # 3. Bilingual pool (ingest provided, else build from the Athena bundle).
    pool_out: Path | None = data_dir / "pool" / f"{code}_pool.csv"
    if pool_csv:
        import shutil
        pool_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pool_csv, pool_out)
        stage("pool", mode="provided", out=str(pool_out))
    elif athena_bundle and language_name:
        try:
            r = mat.build_pool(bundle=Path(athena_bundle), out=pool_out,
                               language_name=language_name)
            stage("pool", mode="athena", pairs=r["pairs"], concepts=r["concepts"])
        except Exception as exc:  # bad bundle / unknown language — record, don't abort
            receipt["gaps"].append(f"build_pool failed: {exc}")
            pool_out = None
    else:
        receipt["gaps"].append(
            "no pool.csv and no athena_bundle(+language_name) → pool not built")
        pool_out = None

    # 4. Register the pool as the <code>_pool data source.
    if pool_out and pool_out.exists():
        prov.register_bilingual_pool(code=code, csv_path=pool_out,
                                     configs_root=configs_root)
        stage("register_pool", source=f"{code}_pool")

    # 5. Seed the template (problem tree + plan + wired translate/GEPA flows).
    seeded = prov.instantiate_template(code=code, name=name,
                                       configs_root=configs_root,
                                       template=template, model_key=model_key)
    stage("seed_template", template=template,
          counts=seeded.get("counts") if isinstance(seeded, dict) else None)

    # 6. Disjoint train/dev/test splits (gold = RF2 preferred term).
    splits_dir = data_dir / "evals" / "dspy_splits"
    if archive and pool_out and pool_out.exists():
        try:
            r = mat.build_splits(
                rf2_snapshot=Path(archive.edition_dir) / "Snapshot",
                pool_csv=pool_out, outdir=splits_dir, code=code,
                language_refset_id=archive.language_refset_id,
                test=test, dev=dev, train=train, seed=seed)
            stage("splits", eligible=r["eligible"], test=r["test"], dev=r["dev"],
                  train=r["train"])
        except Exception as exc:  # too few eligible / provided-pool column mismatch
            receipt["gaps"].append(f"build_splits failed: {exc}")
    else:
        receipt["gaps"].append("splits skipped (need RF2 archive + pool)")

    # 7. Exemplar index + lookup cache (needs Qdrant + BGE-M3; soft-fail).
    if pool_out and pool_out.exists() and do_index:
        try:
            res = mat.index_exemplars(code=code, configs_root=configs_root,
                                      models_json=models_json)
            stage("index_exemplars", collection=res.get("collection"),
                  points=res.get("points"))
        except Exception as exc:  # infra (Qdrant/embedder) — record, don't abort
            receipt["gaps"].append(f"index_exemplars failed: {exc}")
    if pool_out and pool_out.exists() and do_lookup_cache and splits_dir.exists():
        try:
            res = mat.build_lookup_cache(
                code=code, splits_dir=splits_dir,
                out=data_dir / "evals" / "lookup_cache.json",
                configs_root=configs_root, models_json=models_json)
            stage("lookup_cache", entries=res["entries"])
        except Exception as exc:
            receipt["gaps"].append(f"lookup_cache failed: {exc}")

    receipt["configs_dir"] = str(configs_root / code)
    receipt["data_dir"] = str(data_dir)
    receipt["next"] = (
        "finalize_language_project + provision_project_server, then run the "
        f"{code}_translate_eval flow (pass investigation='project')")
    return receipt


def main() -> int:
    p = argparse.ArgumentParser(description="Provision + materialize a language project.")
    p.add_argument("--code", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--language-name", default=None)
    p.add_argument("--drop-dir", default=None)
    p.add_argument("--rf2-archive", default=None)
    p.add_argument("--athena-bundle", default=None)
    p.add_argument("--pool-csv", default=None)
    p.add_argument("--configs-root", default="configs")
    p.add_argument("--data-root", default="data/languages")
    p.add_argument("--style-guide-root", default="style_guide")
    p.add_argument("--models-json", default="configs/models.json")
    p.add_argument("--model-key", default="gemma4-26b")
    p.add_argument("--test", type=int, default=200)
    p.add_argument("--dev", type=int, default=100)
    p.add_argument("--train", type=int, default=300)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-index", action="store_true")
    p.add_argument("--no-lookup-cache", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    receipt = orchestrate_language_project(
        code=a.code, name=a.name, language_name=a.language_name, drop_dir=a.drop_dir,
        rf2_archive=a.rf2_archive, athena_bundle=a.athena_bundle, pool_csv=a.pool_csv,
        configs_root=a.configs_root, data_root=a.data_root,
        style_guide_root=a.style_guide_root, models_json=a.models_json,
        model_key=a.model_key, test=a.test, dev=a.dev, train=a.train, seed=a.seed,
        do_index=not a.no_index, do_lookup_cache=not a.no_lookup_cache,
        overwrite=a.overwrite)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
