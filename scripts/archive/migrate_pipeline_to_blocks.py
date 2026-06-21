"""One-shot migration: split a monolithic PipelineConfig into building blocks.

Reads a legacy ``configs/pipeline_*.json`` and writes the block-library layout
the wizard now manages:

  * ``configs/project.json``        — environment + rarely-varying stage recipes
  * ``configs/sources/<id>.json``   — one file per data source
  * ``configs/flows/<name>.json``   — a starter flow reproducing the monolith's run
  * models stay in ``configs/models.json`` (already standalone); the source
    model's ``llm_params`` is folded onto its catalog entry so the assembler
    reproduces the run exactly.
  * resources stay in the YAML manifest (the monolith's inline list is empty).

After writing, it asserts the assembled config matches the monolith on the
fields that matter (language / paths / qdrant / sources / models / resolved
translation candidate), so we know flows reproduce the old behaviour.

Usage:
    python -m scripts.migrate_pipeline_to_blocks \\
        --pipeline configs/pipeline_ko.json --flow-name ko_baseline \\
        [--style-guide style_guide/style_guide_ko_v5_1.md] \\
        [--eval-set configs/eval_sets/ko_default.json] [--write]

Without ``--write`` it runs as a dry-run (verify only), printing what it would
write. With ``--write`` it persists the files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from snomed_translation.assemble import Registries, assemble_pipeline_config
from snomed_translation.config import (
    DataSourceSpec,
    ModelSpec,
    PipelineConfig,
    ProjectSpec,
)
from pipelines.flow import FlowSpec


def _candidate_snapshot(cfg: PipelineConfig) -> dict | None:
    """The resolved default translation candidate, as a comparable dict."""
    try:
        cand = cfg.translation.resolve_candidate()
    except Exception:
        return None
    return cand.model_dump(mode="json")


def build_blocks(
    monolith: PipelineConfig, *, flow_name: str,
    style_guide: str | None, eval_set: str | None,
) -> tuple[ProjectSpec, list[DataSourceSpec], FlowSpec, dict | None]:
    """Pure split of a monolith into (project, sources, flow, model_llm_params).

    ``model_llm_params`` is the source model's llm_params to fold onto its
    catalog entry (or None if the monolith had none)."""
    resolved = monolith.translation.resolve_candidate()
    src_model_key = resolved.model_key

    project = ProjectSpec(
        version=1,
        name="project",
        language=monolith.language,
        paths=monolith.paths,
        qdrant=monolith.qdrant,
        overlap_defaults=monolith.overlap_defaults,
        pool_output_csv=monolith.sources.pool.output_csv,
        pool_dedup_key=list(monolith.sources.pool.dedup_key),
        evaluation=monolith.evaluation,
        optimization=monolith.optimization,
        sme=monolith.sme,
        default_model_key=src_model_key,
    )

    sources = list(monolith.sources.data_sources)

    # Starter flow: translate (reproducing model/style-guide/output-tag/eval-set)
    # then evaluate against the same eval set, consuming the translate output.
    sg = style_guide or (
        str(monolith.translation.style_guide_path)
        if monolith.translation.style_guide_path else None
    )
    translate_params: dict = {"model_key": src_model_key,
                              "output_tag": monolith.translation.output_tag}
    if sg:
        translate_params["style_guide_path"] = sg
    if eval_set:
        translate_params["eval_set"] = eval_set

    eval_params: dict = {"translations": "$translate_full.output_csv"}
    if eval_set:
        eval_params["eval_set"] = eval_set

    flow = FlowSpec(
        name=flow_name,
        description=f"Migrated from monolithic pipeline (model {src_model_key}).",
        project="project",
        sources=[],          # empty = all enabled sources (matches pool.sources=[])
        resources=[],        # monolith had no inline resources
        steps=[
            {"id": "translate_full", "stage": "translate",
             "description": "Translate the corpus.", "params": translate_params},
            {"id": "evaluate_full", "stage": "evaluate",
             "description": "Score against the eval set.", "params": eval_params},
        ],
    )

    model_llm_params = resolved.llm_params or None
    return project, sources, flow, model_llm_params


def verify(monolith: PipelineConfig, assembled: PipelineConfig,
           *, folded_model_key: str | None = None) -> list[str]:
    """Return a list of human-readable mismatches (empty = equivalent).

    ``folded_model_key`` names the model whose ``llm_params`` the migration
    deliberately moves from the translation stage onto its catalog entry; that
    one intentional addition is excluded from the catalog comparison (the
    resolved-candidate check below proves the params landed correctly)."""
    problems: list[str] = []

    def cmp(label: str, a, b):
        if a != b:
            problems.append(f"{label} differs:\n  monolith : {a}\n  assembled: {b}")

    def _models_dump(cfg: PipelineConfig) -> dict:
        out = {}
        for k, v in cfg.models.items():
            d = v.model_dump(mode="json", exclude_none=True)
            if k == folded_model_key:
                d.pop("llm_params", None)  # ignore the intentional fold
            out[k] = d
        return out

    cmp("language", monolith.language.model_dump(), assembled.language.model_dump())
    cmp("paths", monolith.paths.model_dump(mode="json"),
        assembled.paths.model_dump(mode="json"))
    cmp("qdrant", monolith.qdrant.model_dump(mode="json"),
        assembled.qdrant.model_dump(mode="json"))
    cmp("overlap_defaults", monolith.overlap_defaults.model_dump(),
        assembled.overlap_defaults.model_dump())
    cmp("sources.data_sources",
        [s.model_dump(mode="json", exclude_none=True) for s in monolith.sources.data_sources],
        [s.model_dump(mode="json", exclude_none=True) for s in assembled.sources.data_sources])
    cmp("sources.pool", monolith.sources.pool.model_dump(mode="json"),
        assembled.sources.pool.model_dump(mode="json"))
    cmp("models", _models_dump(monolith), _models_dump(assembled))
    cmp("resolved translation candidate",
        _candidate_snapshot(monolith), _candidate_snapshot(assembled))
    cmp("resolved_exemplar_collection",
        monolith.resolved_exemplar_collection(),
        assembled.resolved_exemplar_collection())
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pipeline", default="configs/pipeline_ko.json")
    ap.add_argument("--flow-name", default="ko_baseline")
    ap.add_argument("--style-guide", default=None,
                    help="Override the translate step's style guide path.")
    ap.add_argument("--eval-set", default="configs/eval_sets/ko_default.json",
                    help="Eval set the starter flow's steps reference.")
    ap.add_argument("--models-json", default="configs/models.json")
    ap.add_argument("--sources-dir", default="configs/sources")
    ap.add_argument("--flows-dir", default="configs/flows")
    ap.add_argument("--project-path", default="configs/project.json")
    ap.add_argument("--resources-path", default="configs/resources_ko.yaml")
    ap.add_argument("--write", action="store_true",
                    help="Persist files (default: dry-run / verify only).")
    args = ap.parse_args()

    monolith = PipelineConfig.from_file(args.pipeline)
    project, sources, flow, model_llm_params = build_blocks(
        monolith, flow_name=args.flow_name,
        style_guide=args.style_guide, eval_set=args.eval_set,
    )

    src_model_key = monolith.translation.resolve_candidate().model_key
    print(f"Source model: {src_model_key}")
    print(f"Project: language={project.language.code} default_model={project.default_model_key}")
    print(f"Sources: {[s.id for s in sources]}")
    print(f"Flow: {flow.name} ({len(flow.steps)} steps)")
    if model_llm_params:
        print(f"Folding llm_params onto catalog entry {src_model_key!r}: {model_llm_params}")

    # --- Fold the source model's llm_params onto its catalog entry (in memory),
    #     then build registries so the assembler reproduces the run exactly.
    raw_models = json.loads(Path(args.models_json).read_text(encoding="utf-8"))
    if model_llm_params and src_model_key in raw_models.get("models", {}):
        raw_models["models"][src_model_key]["llm_params"] = model_llm_params

    registries = Registries(
        models={k: ModelSpec.model_validate(v) for k, v in raw_models.get("models", {}).items()},
        jobs=registries_jobs(raw_models),
        sources={s.id: s for s in sources},
        resources_manifest=Registries.load(
            models_json=args.models_json, sources_dir=args.sources_dir,
            resources_path=args.resources_path).resources_manifest,
    )

    assembled = assemble_pipeline_config(flow, project, registries)
    problems = verify(monolith, assembled, folded_model_key=src_model_key)
    if problems:
        print("\n❌ EQUIVALENCE MISMATCH:")
        for p in problems:
            print(" -", p)
        return 1
    print("\n✅ Assembled config matches the monolith on all checked fields.")

    if not args.write:
        print("\n(dry-run — pass --write to persist files)")
        return 0

    # --- Persist.
    project.save(args.project_path)
    print(f"wrote {args.project_path}")
    sdir = Path(args.sources_dir)
    for s in sources:
        out = sdir / f"{s.id}.json"
        s.save(out)
        print(f"wrote {out}")
    flow_out = Path(args.flows_dir) / f"{flow.name}.json"
    flow.save(flow_out)
    print(f"wrote {flow_out}")
    # Persist the folded llm_params back to the catalog.
    if model_llm_params:
        Path(args.models_json).write_text(
            json.dumps(raw_models, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"updated {args.models_json} ({src_model_key}.llm_params)")
    return 0


def registries_jobs(raw_models: dict) -> dict:
    from snomed_translation.config import JobSpec
    return {k: JobSpec.model_validate(v) for k, v in raw_models.get("jobs", {}).items()}


if __name__ == "__main__":
    raise SystemExit(main())
