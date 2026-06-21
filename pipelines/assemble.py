"""Assemble a runnable :class:`PipelineConfig` from registered building blocks.

This is the keystone of the block-library design. The wizard manages
independent libraries — Models, Data sources, Resources, Eval sets, Style
guides — plus a shared :class:`~pipelines.config.ProjectSpec` (the environment:
language, paths, Qdrant, overlap defaults, and the rarely-varying stage
recipes). A :class:`~pipelines.flow.FlowSpec` *composes* those blocks as a node
graph: datasource nodes reference registered sources, translate/evaluate nodes
wire to upstream outputs.

At run time :func:`assemble_pipeline_config` materialises an in-memory
``PipelineConfig`` from (project + referenced blocks + flow), so the existing
stage runners (``pipelines.stages.*``) execute against it unchanged. The
per-node wiring (which datasource feeds the term list vs the exemplar pool,
which model each translate node uses) is applied by the graph compiler
(:mod:`pipelines.graph`) on a deep copy per node. The assembler's obligations
are to expose every datasource node's source in ``sources.data_sources`` and
every translate node's model in ``translation.candidates``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pipelines.config import (
    BilingualPoolSpec,
    DataSourceSpec,
    JobSpec,
    ModelSpec,
    PipelineConfig,
    ProjectSpec,
    ResourceManifest,
    ResourceSpec,
    SourcesSpec,
    TranslationCandidate,
    TranslationStageSpec,
)
from pipelines.flow import FlowSpec


class AssemblyError(Exception):
    """Raised when a flow references a block that can't be resolved."""


@dataclass
class Registries:
    """Loaded building-block libraries, addressable by id/key.

    Eval sets and style guides stay path-valued (each step supplies one, loaded
    lazily by ``run_flow``), so they're deliberately absent here.
    """

    models: dict[str, ModelSpec] = field(default_factory=dict)
    jobs: dict[str, JobSpec] = field(default_factory=dict)
    sources: dict[str, DataSourceSpec] = field(default_factory=dict)
    resources_manifest: ResourceManifest = field(default_factory=ResourceManifest)

    @classmethod
    def load(
        cls,
        *,
        models_json: str | Path = "configs/models.json",
        sources_dir: str | Path = "configs/sources",
        resources_path: str | Path = "configs/resources_ko.yaml",
    ) -> "Registries":
        """Load all registries from disk. Paths default to the repo layout;
        the wizard passes its ``SETTINGS`` values so per-host overrides apply.
        Kept free of any ``wizard`` import so ``pipelines`` stays standalone.
        """
        models: dict[str, ModelSpec] = {}
        jobs: dict[str, JobSpec] = {}
        mp = Path(models_json)
        if mp.exists():
            raw = json.loads(mp.read_text(encoding="utf-8"))
            models = {k: ModelSpec.model_validate(v)
                      for k, v in (raw.get("models") or {}).items()}
            jobs = {k: JobSpec.model_validate(v)
                    for k, v in (raw.get("jobs") or {}).items()}

        sources: dict[str, DataSourceSpec] = {}
        sdir = Path(sources_dir)
        if sdir.is_dir():
            files = (sorted(sdir.glob("*.json")) + sorted(sdir.glob("*.yaml"))
                     + sorted(sdir.glob("*.yml")))
            for p in files:
                try:
                    spec = DataSourceSpec.from_file(p)
                except Exception as exc:  # surface broken files, don't crash load
                    raise AssemblyError(
                        f"data source {p.name!r} failed to load: {exc}"
                    ) from exc
                sources[spec.id] = spec

        rp = Path(resources_path)
        manifest = ResourceManifest.from_file(rp) if rp.exists() else ResourceManifest()

        return cls(models=models, jobs=jobs, sources=sources,
                   resources_manifest=manifest)


def load_project(name: str, configs_dir: str | Path = "configs") -> ProjectSpec:
    """Resolve a project by name to its spec file.

    Looks in ``configs/projects/<name>.{json,yaml,yml}`` first (the multi-project
    library), then falls back to the legacy singleton location
    ``configs/<name>.json`` so older layouts keep working.
    """
    base = Path(configs_dir)
    for parent in (base / "projects", base):
        for ext in (".json", ".yaml", ".yml"):
            p = parent / f"{name}{ext}"
            if p.exists():
                return ProjectSpec.from_file(p)
    raise AssemblyError(
        f"project {name!r} not found under {base} "
        f"(looked in projects/ and the legacy root for {name}.json/.yaml/.yml)."
    )


def _referenced_model_keys(flow: FlowSpec, project: ProjectSpec) -> list[str]:
    """Every model_key a translate or optimize node names, plus the project
    default — de-duplicated, order preserved. This is the translation
    candidate whitelist: optimize nodes count because GEPA optimises the
    guide *for* a task model, selected by the same candidate mechanism."""
    keys: list[str] = []
    for node in flow.nodes:
        if node.type not in ("translate", "translate_consistency", "optimize"):
            continue
        mk = node.params.get("model_key")
        if isinstance(mk, str) and mk:
            keys.append(mk)
    if project.default_model_key:
        keys.append(project.default_model_key)
    seen: set[str] = set()
    return [k for k in keys if not (k in seen or seen.add(k))]


def _referenced_source_ids(flow: FlowSpec) -> list[str]:
    """Source ids referenced by datasource nodes, de-duplicated, order kept."""
    ids: list[str] = []
    for node in flow.nodes:
        if node.type != "datasource":
            continue
        sid = node.params.get("source")
        if isinstance(sid, str) and sid:
            ids.append(sid)
    seen: set[str] = set()
    return [s for s in ids if not (s in seen or seen.add(s))]


def _make_candidate(key: str, model: ModelSpec) -> TranslationCandidate:
    """Synthesise a candidate, inheriting the model's default runtime bundle
    (llm_params / api_key_env) from the catalog when present. Per-step params
    (concurrency, etc.) still override at run time."""
    kwargs: dict = {"model_key": key}
    if model.llm_params is not None:
        kwargs["llm_params"] = dict(model.llm_params)
    if model.api_key_env is not None:
        kwargs["api_key_env"] = model.api_key_env
    return TranslationCandidate(**kwargs)


def assemble_pipeline_config(
    flow: FlowSpec, project: ProjectSpec, registries: Registries
) -> PipelineConfig:
    """Materialise a ``PipelineConfig`` from a flow + project + registries.

    Raises :class:`AssemblyError` (naming the offending id) on any unresolved
    block reference, so the UI and CLI can show actionable messages.
    """
    # --- Data sources: every source a datasource node references. The
    #   per-node compiler (pipelines.graph) picks which feeds the pool vs the
    #   term list at run time, so pool.sources is left empty here. If the flow
    #   has no datasource nodes yet, fall back to all enabled sources so the
    #   base config + exemplar-collection name still resolve.
    node_source_ids = _referenced_source_ids(flow)
    if node_source_ids:
        selected_ids = node_source_ids
    else:
        selected_ids = [sid for sid, s in registries.sources.items() if s.enabled]
    pool_source_ids: list[str] = []  # set per translate node at run time
    missing = [sid for sid in selected_ids if sid not in registries.sources]
    if missing:
        raise AssemblyError(
            f"flow {flow.name!r} references unknown source id(s) {missing}; "
            f"available: {sorted(registries.sources)}"
        )
    data_sources = [registries.sources[sid] for sid in selected_ids]

    # --- Resources: None = all manifest entries; [] = none; else filter by id.
    if flow.resources is None:
        resource_entries = list(registries.resources_manifest.resources)
    else:
        by_id = {r.get("id"): r for r in registries.resources_manifest.resources}
        missing_r = [rid for rid in flow.resources if rid not in by_id]
        if missing_r:
            raise AssemblyError(
                f"flow {flow.name!r} references unknown resource id(s) {missing_r}; "
                f"available: {sorted(k for k in by_id if k)}"
            )
        resource_entries = [by_id[rid] for rid in flow.resources]
    try:
        resources = [ResourceSpec.model_validate(r) for r in resource_entries]
    except Exception as exc:
        raise AssemblyError(
            f"resource manifest entry failed validation: {exc}"
        ) from exc

    # --- Translation candidates derived from the flow's translate steps.
    model_keys = _referenced_model_keys(flow, project)
    missing_m = [k for k in model_keys if k not in registries.models]
    if missing_m:
        raise AssemblyError(
            f"flow {flow.name!r} references model_key(s) {missing_m} not in the "
            f"catalog; available: {sorted(registries.models)}"
        )
    candidates = [_make_candidate(k, registries.models[k]) for k in model_keys]
    default_model_key = (
        project.default_model_key
        or (model_keys[0] if model_keys else None)
    )

    translation = TranslationStageSpec(
        candidates=candidates,
        default_model_key=default_model_key,
    )

    pool = BilingualPoolSpec(
        sources=pool_source_ids,
        output_csv=project.pool_output_csv or BilingualPoolSpec().output_csv,
        dedup_key=list(project.pool_dedup_key),
    )

    # Construct via the model so every validator (candidate uniqueness,
    # default membership, reflection normalisation) runs exactly as for a
    # file-loaded config. eval_set stays None — each step supplies one.
    return PipelineConfig(
        version=1,
        language=project.language,
        paths=project.paths,
        sources=SourcesSpec(data_sources=data_sources, pool=pool),
        eval_set=None,
        resources=resources,
        overlap_defaults=project.overlap_defaults,
        qdrant=project.qdrant,
        models=registries.models,
        jobs=registries.jobs,
        translation=translation,
        evaluation=project.evaluation,
        optimization=project.optimization,
        sme=project.sme,
    )
