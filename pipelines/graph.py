"""Compile a flow *graph* into stage executions.

A flow is a DAG of typed nodes (:mod:`pipelines.flow`). This module turns that
graph into work the existing stage runners can execute, with no change to the
runners themselves:

* **datasource** nodes don't execute — they resolve to a registered source's
  output CSV (+ its column mapping), which downstream nodes consume.
* **translate** nodes map their ``terms`` input onto ``cfg.eval_set`` (the rows
  to translate) and their ``exemplars`` input onto ``cfg.sources.pool`` (the RAG
  pool), then run the translate stage.
* **evaluate** nodes map their ``reference`` input onto ``cfg.eval_set`` (gold
  references) and consume the upstream translate node's ``output_csv`` as the
  translations to score.

The compiler deep-copies the assembled base config per node so one node's
overrides never bleed into another (same isolation the old linear runner had).
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from pipelines.assemble import Registries
from pipelines.config import EvalSetColumns, EvalSetSpec, PipelineConfig
from pipelines.flow import PORT_REQUIRES, ROLE_LABELS, FlowNode, FlowSpec
from pipelines.publish import PublishError, validate_publish_name


class GraphError(Exception):
    """Raised when a flow graph can't be compiled (bad wiring, missing block)."""


# Header-name aliases per role, so a dataset's roles are detected even when its
# column names differ from the canonical (sctid, en_term, target_term). Matched
# case-insensitively; the source's declared csv_columns mapping wins when its
# column is actually present in the file.
ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "sctid": ("sctid", "id", "concept_id", "conceptid", "sct_id", "code"),
    "en": ("en", "en_term", "english", "eng", "source_term", "preferred_term", "term"),
    "target": ("target", "target_term", "ko", "kor", "ko_term", "translation", "reference"),
    "candidates": ("candidates",),
}

# The translate stage's writer emits these columns (pipelines/stages/translate.py)
# — which means a translate node's output is itself a dataset carrying the
# concept id, the original English term, and the produced translation. The
# graph advertises this schema so downstream ports (evaluate.translations
# today; exemplars/optimize inputs in future flows) validate against it
# exactly like a datasource.
TRANSLATE_OUTPUT_ROLES: dict[str, str] = {
    "sctid": "sctid",
    "en": "preferred_term",
    "target": "translation",
}


def translate_output_schema() -> dict[str, Any]:
    """Dataset schema of a translate node's output CSV (static by design)."""
    return {
        "columns": ["sctid", "preferred_term", "ko_reference", "translation"],
        "roles": dict(TRANSLATE_OUTPUT_ROLES),
        "present": list(TRANSLATE_OUTPUT_ROLES),
    }


# A translate_consistency node's output CSV carries the concept id, the source
# English term, and a JSON list of distinct candidate translations (see
# pipelines/stages/translate_consistency.py). It advertises the `candidates`
# role instead of `target` — there is no single chosen translation yet, so only
# evaluate_consistency (which judges + scores) can consume it.
TRANSLATE_CONSISTENCY_OUTPUT_ROLES: dict[str, str] = {
    "sctid": "sctid",
    "en": "preferred_term",
    "candidates": "candidates",
}


def translate_consistency_output_schema() -> dict[str, Any]:
    """Dataset schema of a translate_consistency node's output CSV."""
    return {
        "columns": ["sctid", "preferred_term", "ko_reference",
                    "n_samples", "n_distinct", "candidates"],
        "roles": dict(TRANSLATE_CONSISTENCY_OUTPUT_ROLES),
        "present": list(TRANSLATE_CONSISTENCY_OUTPUT_ROLES),
    }


def topo_order(nodes: list[FlowNode]) -> list[FlowNode]:
    """Dependency order: a node appears after every node it consumes.

    Assumes the graph validated acyclic (FlowSpec validators guarantee this);
    raises GraphError defensively if a cycle slips through.
    """
    by_id = {n.id: n for n in nodes}
    ordered: list[FlowNode] = []
    state: dict[str, int] = {}  # 0 unseen, 1 on-stack, 2 done

    def visit(n: FlowNode) -> None:
        state[n.id] = 1
        for src_id in n.inputs.values():
            src = by_id.get(src_id)
            if src is None:
                raise GraphError(f"node {n.id!r} references unknown node {src_id!r}")
            s = state.get(src_id, 0)
            if s == 1:
                raise GraphError(f"cycle involving {n.id!r}")
            if s == 0:
                visit(src)
        state[n.id] = 2
        ordered.append(n)

    for n in nodes:
        if state.get(n.id, 0) == 0:
            visit(n)
    return ordered


def _declared_roles(source) -> dict[str, str]:
    """The role->column mapping a source *declares* (before checking the file).

    csv-kind sources carry an explicit mapping; the SNOMED/Athena/LOINC
    ingesters all emit the canonical ``(sctid, en_term, target_term)``.
    """
    cc = getattr(source, "csv_columns", None)
    if source.kind == "csv" and cc is not None:
        return {"sctid": cc.sctid, "en": cc.en, "target": cc.target}
    return {"sctid": "sctid", "en": "en_term", "target": "target_term"}


def read_csv_header(path: str | Path) -> list[str] | None:
    """The header row of a CSV, or None if the file is missing/unreadable."""
    import csv as _csv
    p = Path(path)
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8", newline="") as f:
            line = f.readline()
        if not line:
            return []
        return next(_csv.reader([line]))
    except Exception:
        return None


def source_schema(source) -> dict[str, Any]:
    """Resolve a source's dataset schema for display + compatibility.

    Returns ``{columns, roles, present, built}`` where ``roles`` maps each
    detected role to its physical column, ``present`` lists the roles the
    dataset actually provides, and ``built`` is whether the CSV exists yet.
    Role detection prefers the source's declared mapping, then falls back to
    header-name aliases, so a dataset whose columns don't match the declared
    mapping is still understood (and the mismatch is visible to the user).
    """
    declared = _declared_roles(source)
    header = read_csv_header(source.output_csv)
    if header is None:
        # Not built yet — trust the declared mapping, columns unknown.
        return {"columns": list(declared.values()), "roles": dict(declared),
                "present": list(declared), "built": False}
    lower = {h.lower(): h for h in header}
    roles: dict[str, str] = {}
    for role, decl_col in declared.items():
        if decl_col in header:
            roles[role] = decl_col
            continue
        for alias in ROLE_ALIASES.get(role, ()):  # alias fallback
            if alias in lower:
                roles[role] = lower[alias]
                break
    return {"columns": header, "roles": roles, "present": list(roles),
            "built": True}


def _eval_set_from_datasource(ds: dict) -> EvalSetSpec:
    """Build an EvalSetSpec that translates a datasource's English column and
    treats its target column as the (single) reference."""
    roles = ds["roles"]
    return EvalSetSpec(
        csv=Path(ds["dataset"]),
        columns=EvalSetColumns(
            sctid=roles.get("sctid", "sctid"),
            source_term=roles.get("en", "en_term"),
            reference=roles.get("target", "target_term"),
            all_references=roles.get("target", "target_term"),
        ),
    )


def resolve_datasource(node: FlowNode, registries: Registries) -> dict[str, Any]:
    """Resolve a datasource node to its output CSV + detected schema (no run)."""
    sid = node.params.get("source")
    if not sid:
        raise GraphError(f"datasource node {node.id!r} has no `source` param")
    source = registries.sources.get(sid)
    if source is None:
        raise GraphError(
            f"datasource node {node.id!r} references unknown source {sid!r}; "
            f"available: {sorted(registries.sources)}"
        )
    schema = source_schema(source)
    if not schema["built"]:
        raise GraphError(
            f"datasource node {node.id!r}: source {sid!r} is not built — "
            f"expected CSV at {source.output_csv}. Build it (or pick a "
            "built source on the node) before running."
        )
    return {
        "dataset": str(source.output_csv),
        "source_id": source.id,
        "roles": schema["roles"],
        "present": schema["present"],
        "columns": schema["columns"],
        "built": schema["built"],
    }


def resolve_style_guide(node: FlowNode) -> dict[str, Any]:
    """Resolve a style-guide node to its markdown file (no run).

    Style-guide nodes are the static counterpart of an optimize node's
    output: both put a guide on the wire; translate consumes either.
    """
    path = node.params.get("path")
    if not path:
        raise GraphError(f"style-guide node {node.id!r} has no `path` param")
    p = Path(path)
    if not p.exists():
        raise GraphError(
            f"style-guide node {node.id!r}: file not found: {p}")
    return {"style_guide": str(p)}


def _require_roles(node: FlowNode, port: str, ds: dict) -> None:
    """Raise GraphError if datasource ``ds`` lacks a role the port needs."""
    needed = PORT_REQUIRES.get(node.type, {}).get(port, [])
    missing = [r for r in needed if r not in ds.get("present", [])]
    if missing:
        labels = ", ".join(ROLE_LABELS.get(r, r) for r in missing)
        raise GraphError(
            f"node {node.id!r} input {port!r} needs columns [{labels}] which "
            f"dataset {ds.get('source_id')!r} (columns: {ds.get('columns')}) "
            "does not provide"
        )


def _check_publish_name(node: FlowNode) -> None:
    pub = node.params.get("publish_as")
    if pub:
        try:
            validate_publish_name(str(pub))
        except PublishError as exc:
            raise GraphError(f"node {node.id!r}: {exc}") from exc


def _input(node: FlowNode, port: str, resolved: dict[str, dict]) -> dict:
    src_id = node.inputs.get(port)
    if not src_id:
        raise GraphError(f"node {node.id!r} has no {port!r} input wired")
    if src_id not in resolved:
        raise GraphError(
            f"node {node.id!r} input {port!r} depends on {src_id!r}, which "
            "did not resolve"
        )
    return resolved[src_id]


def build_translate(node: FlowNode, base_cfg: PipelineConfig,
                    resolved: dict[str, dict]) -> tuple[PipelineConfig, dict]:
    """Deep-copy the base config and apply a translate node's wiring + params."""
    cfg = copy.deepcopy(base_cfg)
    _check_publish_name(node)
    terms = _input(node, "terms", resolved)
    exemplars = _input(node, "exemplars", resolved)
    _require_roles(node, "terms", terms)
    _require_roles(node, "exemplars", exemplars)

    cfg.eval_set = _eval_set_from_datasource(terms)
    cfg.sources.pool.sources = [exemplars["source_id"]]

    model_key = node.params.get("model_key")
    if model_key:
        cfg.translation.resolve_candidate(model_key)  # validates against catalog
        cfg.translation.default_model_key = model_key
    sgp = node.params.get("style_guide_path")
    if sgp:
        # Legacy param from pre-wiring flows; the wired input supersedes it.
        cfg.translation.style_guide_path = Path(sgp)
    if node.inputs.get("style_guide"):
        upstream = _input(node, "style_guide", resolved)
        guide = upstream.get("style_guide") or upstream.get("optimized_style_guide")
        if not guide:
            raise GraphError(
                f"node {node.id!r} style_guide input is wired to "
                f"{node.inputs['style_guide']!r}, which produced no style "
                "guide output"
            )
        cfg.translation.style_guide_path = Path(str(guide))
    if cfg.translation.style_guide_path is None:
        raise GraphError(
            f"node {node.id!r} has no style guide — wire a style-guide node "
            "(or an optimize node's output) to its style_guide port"
        )
    cfg.translation.output_tag = node.params.get("output_tag") or node.id

    kwargs: dict[str, Any] = {}
    if "limit" in node.params:
        kwargs["limit"] = int(node.params["limit"])
    if "resume" in node.params:
        kwargs["resume"] = bool(node.params["resume"])
    if "temperature" in node.params:
        kwargs["temperature"] = float(node.params["temperature"])
    return cfg, kwargs


def build_translate_consistency(node: FlowNode, base_cfg: PipelineConfig,
                                resolved: dict[str, dict]
                                ) -> tuple[PipelineConfig, dict]:
    """Compile a translate_consistency node.

    Wiring + params are identical to a translate node (terms / exemplars /
    style_guide / model_key / output_tag), so it reuses :func:`build_translate`
    wholesale and only adds the self-consistency knobs: ``samples`` (how many
    times to run each concept) and an optional ``temperature`` override (the
    candidate's default is usually 0.0, which makes every sample identical —
    self-consistency wants sampling, so a temperature > 0 is the point).
    """
    cfg, kwargs = build_translate(node, base_cfg, resolved)
    kwargs["samples"] = int(node.params.get("samples", 5))
    if "temperature" in node.params:
        kwargs["temperature"] = float(node.params["temperature"])
    return cfg, kwargs


def build_evaluate_consistency(node: FlowNode, base_cfg: PipelineConfig,
                               resolved: dict[str, dict]
                               ) -> tuple[PipelineConfig, dict]:
    """Compile an evaluate_consistency node.

    Consumes a translate_consistency node's candidates artifact and the gold
    reference. For concepts with more than one distinct candidate it re-prompts
    the same translating model (using the prompt sidecar the upstream node
    wrote) to pick the best, then scores the chosen translation against the
    reference. An optional ``model_key`` param overrides the judging model
    (defaults to the model that produced the candidates)."""
    cfg = copy.deepcopy(base_cfg)
    _check_publish_name(node)
    candidates = _input(node, "candidates", resolved)
    ref = _input(node, "reference", resolved)
    _require_roles(node, "candidates", candidates)
    _require_roles(node, "reference", ref)

    cfg.eval_set = _eval_set_from_datasource(ref)
    # The chosen-translations artifact is tagged like the upstream candidates so
    # the published "best picks" dataset is easy to trace back.
    cfg.translation.output_tag = node.params.get("output_tag") or node.id
    path = candidates.get("candidates") or candidates.get("dataset")
    if not path:
        raise GraphError(
            f"node {node.id!r} candidates input is wired to "
            f"{node.inputs.get('candidates')!r}, which produced no candidates "
            "artifact")
    kwargs: dict[str, Any] = {"candidates_path": Path(str(path))}
    if "limit" in node.params:
        kwargs["limit"] = int(node.params["limit"])
    if node.params.get("model_key"):
        kwargs["model_key"] = str(node.params["model_key"])
    # Thinking is the on/off comparison knob; accept bool or the editor's
    # "on"/"off" string. explanation_language picks the reason's language.
    kwargs["thinking"] = str(node.params.get("thinking", "")).strip().lower() \
        in ("on", "true", "1", "yes")
    if node.params.get("explanation_language"):
        kwargs["explanation_language"] = str(node.params["explanation_language"])
    return cfg, kwargs


def build_optimize(node: FlowNode, base_cfg: PipelineConfig,
                   resolved: dict[str, dict]) -> tuple[PipelineConfig, dict]:
    """Deep-copy the base config and apply an optimize node's wiring + params.

    The optimize node runs GEPA: it trains a style guide against the wired
    ``trainset`` (validating on ``devset`` when wired, else the trainset) and
    outputs an optimised style-guide file. The task model being optimised for
    is picked exactly like a translate node's (``params.model_key``); the GEPA
    recipe (budget, reflection LM, hints) comes from the project's
    ``optimization`` block.
    """
    cfg = copy.deepcopy(base_cfg)
    _check_publish_name(node)
    if cfg.optimization is None:
        raise GraphError(
            f"node {node.id!r}: the project supplies no `optimization` recipe "
            "— add one to the project block before using an optimize node"
        )
    train = _input(node, "trainset", resolved)
    _require_roles(node, "trainset", train)
    kwargs: dict[str, Any] = {"trainset": train}
    if node.inputs.get("devset"):
        dev = _input(node, "devset", resolved)
        _require_roles(node, "devset", dev)
        kwargs["devset"] = dev

    model_key = node.params.get("model_key")
    if model_key:
        cfg.translation.resolve_candidate(model_key)  # validates against catalog
        cfg.translation.default_model_key = model_key
    sgp = node.params.get("style_guide_path")
    if sgp:
        # Legacy param from pre-wiring flows; the wired input supersedes it.
        cfg.optimization.seed_style_guide = Path(sgp)
    if node.inputs.get("seed_style_guide"):
        upstream = _input(node, "seed_style_guide", resolved)
        guide = upstream.get("style_guide")
        if not guide:
            raise GraphError(
                f"node {node.id!r} seed_style_guide input is wired to "
                f"{node.inputs['seed_style_guide']!r}, which produced no "
                "style guide output"
            )
        cfg.optimization.seed_style_guide = Path(str(guide))
    if cfg.optimization.seed_style_guide is None:
        raise GraphError(
            f"node {node.id!r} needs a seed style guide — wire a style-guide "
            "node to its seed_style_guide port, or set the project recipe's "
            "optimization.seed_style_guide"
        )
    kwargs["output_tag"] = node.params.get("output_tag") or node.id
    for key in ("train_limit", "dev_limit"):
        if key in node.params:
            kwargs[key] = int(node.params[key])
    if node.params.get("reflection_model_key"):
        kwargs["reflection_model_key"] = node.params["reflection_model_key"]
    return cfg, kwargs


def _collect_metric_vars(node: FlowNode, resolved: dict[str, dict]
                         ) -> dict[str, float]:
    """The metric vector of a score node's wired upstream input as a flat
    ``{name: value}`` map for the formula / prompt — the JSON of metric keys→
    values the upstream evaluate node emitted, referenced by bare name."""
    variables: dict[str, float] = {}
    src_id = node.inputs.get("metrics")
    if not src_id:
        return variables
    if src_id not in resolved:
        raise GraphError(
            f"score node {node.id!r} metrics input depends on {src_id!r}, "
            "which did not resolve")
    metrics = resolved[src_id].get("metrics") or {}
    for key, val in metrics.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        variables[key] = float(val)
    return variables


def build_evaluate_formula(node: FlowNode, base_cfg: PipelineConfig,
                           resolved: dict[str, dict]) -> tuple[PipelineConfig, dict]:
    """Compile a formula score node: a safe arithmetic expression over the
    metric vector of its wired upstream evaluate node -> one scalar."""
    from pipelines.formula import FormulaError, compile_formula

    if not node.inputs.get("metrics"):
        raise GraphError(
            f"score node {node.id!r} needs its metrics input wired to an "
            "evaluate node")
    expr = str(node.params.get("expression") or "").strip()
    if not expr:
        raise GraphError(f"score node {node.id!r} has no `expression` param")
    try:
        compile_formula(expr)  # shape check only; names checked at run time
    except FormulaError as exc:
        raise GraphError(f"node {node.id!r}: invalid formula: {exc}") from exc
    return base_cfg, {
        "expression": expr,
        "variables": _collect_metric_vars(node, resolved),
        "output_name": str(node.params.get("output_name") or "score"),
    }


def build_score_workflow_llm(node: FlowNode, base_cfg: PipelineConfig,
                             resolved: dict[str, dict]) -> tuple[PipelineConfig, dict]:
    """Compile an LLM score node: render the user's prompt with the upstream
    metric vector templated in, then ask a model for a single scalar."""
    if not node.inputs.get("metrics"):
        raise GraphError(
            f"score node {node.id!r} needs its metrics input wired to an "
            "evaluate node")
    prompt = str(node.params.get("prompt") or "").strip()
    if not prompt:
        raise GraphError(f"score node {node.id!r} has no `prompt` param")
    model_key = node.params.get("model_key") or base_cfg.translation.default_model_key
    if not model_key or model_key not in base_cfg.models:
        raise GraphError(
            f"score node {node.id!r}: model {model_key!r} not in the models "
            "catalogue — set the node's model or the project default")
    kwargs = {
        "prompt": prompt,
        "variables": _collect_metric_vars(node, resolved),
        "model_key": str(model_key),
        "output_name": str(node.params.get("output_name") or "score"),
    }
    if "thinking" in node.params:
        kwargs["thinking"] = str(node.params["thinking"]).strip().lower() in (
            "on", "true", "1", "yes")
    return base_cfg, kwargs


def build_evaluate(node: FlowNode, base_cfg: PipelineConfig,
                   resolved: dict[str, dict]) -> tuple[PipelineConfig, dict]:
    """Deep-copy the base config and apply an evaluate node's wiring + params."""
    cfg = copy.deepcopy(base_cfg)
    ref = _input(node, "reference", resolved)
    translations = _input(node, "translations", resolved)
    _require_roles(node, "reference", ref)
    _require_roles(node, "translations", translations)

    cfg.eval_set = _eval_set_from_datasource(ref)
    kwargs: dict[str, Any] = {"translations_path": Path(translations["translations"])}
    if "limit" in node.params:
        kwargs["limit"] = int(node.params["limit"])
    return cfg, kwargs
