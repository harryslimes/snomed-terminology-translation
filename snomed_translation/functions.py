"""The SNOMED-translation plugin: the node functions a flow can run.

This is what the app discovers through the ``semi_automated_research.functions``
entry-point group (and the source resolver through
``semi_automated_research.sources``). Each :class:`~pipelines.functions.FunctionSpec`
tells the editor a node's ports + params; its runner adapts the generic
``run(ctx, inputs, params) -> FunctionResult`` contract to the existing
``graph.build_* + stages`` machinery.

How the impedance is bridged
----------------------------
The legacy compilers (:mod:`snomed_translation.graph`) take a ``FlowNode`` + a
``resolved`` dict (every upstream node's full output mapping) + an assembled
``PipelineConfig``. The generic engine instead hands a runner only the *primary*
value flowing along each input wire (typically a path) plus the node params, and
performs no config assembly for an all-generic flow. So each adapter:

* lazily assembles the project ``PipelineConfig`` from the running flow
  (``ctx.flow``) + ``ctx.configs_dir``, caching it on ``ctx.extras`` (:func:`_assemble`);
* reconstructs the ``resolved`` entries each compiler needs from the wire values
  — datasource paths are turned back into full ``{dataset, source_id, roles,
  present, columns}`` dicts via a reverse lookup in the loaded registries
  (:func:`_recover_input`);
* synthesises a ``FlowNode``, calls the matching ``build_*`` + stage runner, and
  maps the :class:`~pipelines.context.StageResult` to a
  :class:`~pipelines.functions.FunctionResult`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pipelines.context import RunContext, StageResult
from pipelines.flow import FlowNode
from pipelines.functions import FunctionResult, FunctionSpec, ParamSpec, PortSpec

from snomed_translation import graph
from snomed_translation.assemble import (
    AssemblyError,
    Registries,
    assemble_pipeline_config,
    load_environment,
    load_investigation,
    recipe_from_investigation,
    resolve_environment,
)
from snomed_translation.config import PipelineConfig
from snomed_translation.schema import PORT_REQUIRES
from snomed_translation.stages import get_stage


# ---------------------------------------------------------------------------
# Flow-level config assembly (lazy, cached per run on ctx.extras).
# ---------------------------------------------------------------------------
def _registries(ctx: RunContext) -> Registries:
    cached = ctx.extras.get("registries")
    if cached is not None:
        return cached
    base = Path(ctx.configs_dir) if ctx.configs_dir else Path("configs")
    reg = Registries.load(
        models_json=base / "models.json",
        sources_dir=base / "sources",
        resources_path=base / "resources_ko.yaml",
    )
    ctx.extras["registries"] = reg
    return reg


def _assemble(ctx: RunContext) -> PipelineConfig:
    """Assemble (and cache) the run ``PipelineConfig``.

    Needs the running flow on ``ctx.flow`` (the app sets it) so the candidate
    whitelist + sources are derived from the same blocks the legacy path used.
    A Run = Flow × Environment × Investigation: the investigation is chosen at
    run time (``ctx.investigation``, with the flow's legacy ``project`` binding
    as a fallback), and the environment is the run-time choice
    (``ctx.environment``) or the investigation's default (#22/#23).
    """
    cached = ctx.extras.get("base_cfg")
    if cached is not None:
        return cached
    flow = ctx.flow
    if flow is None:
        raise AssemblyError(
            "no flow on the run context — the engine must set ctx.flow before "
            "running translation functions")
    base = Path(ctx.configs_dir) if ctx.configs_dir else Path("configs")
    inv_name = getattr(ctx, "investigation", None) or getattr(flow, "project", None)
    if not inv_name:
        raise AssemblyError(
            "no investigation for this run — set ctx.investigation (or the "
            "flow's legacy project) so the environment + recipe resolve")
    investigation = load_investigation(inv_name, base)
    env_name = getattr(ctx, "environment", None)
    environment = (
        load_environment(env_name, base) if env_name
        else resolve_environment(investigation, base)
    )
    recipe = recipe_from_investigation(investigation)
    cfg = assemble_pipeline_config(flow, environment, recipe, _registries(ctx))
    ctx.extras["base_cfg"] = cfg
    return cfg


# ---------------------------------------------------------------------------
# Recovering the resolved-dicts each build_* expects from wire values.
# ---------------------------------------------------------------------------
def _datasource_dict(value: Any, ctx: RunContext) -> dict[str, Any]:
    """Turn a datasource wire value back into the full schema dict.

    The generic engine passes a datasource's *primary* (the CSV path). The
    compilers want the ``resolve_datasource`` mapping, so we reverse-look-up the
    source whose ``output_csv`` matches the path and resolve it afresh.
    """
    if isinstance(value, dict) and "dataset" in value:
        return value  # already a full dict (e.g. wired straight from a resolver)
    path = str(value)
    reg = _registries(ctx)
    for source in reg.sources.values():
        if str(source.output_csv) == path:
            node = FlowNode(id="_ds", type="datasource",
                            params={"source": source.id})
            return graph.resolve_datasource(node, reg)
    raise graph.GraphError(
        f"could not map dataset path {path!r} back to a known source; "
        f"available: {sorted(reg.sources)}")


def _recover_input(kind: str, value: Any, ctx: RunContext) -> Any:
    """Reconstruct the ``resolved`` entry a compiler reads for one input port,
    given the value the engine delivered on that wire and the port's ``kind``."""
    if value is None:
        return None
    if kind == "datasource":
        return _datasource_dict(value, ctx)
    if kind == "translate_out":
        # A translate node's output CSV — fixed schema (sctid/en/target).
        return {"translations": str(value), "dataset": str(value),
                "source_id": "_translate", **graph.translate_output_schema()}
    if kind == "candidates_out":
        return {"candidates": str(value), "dataset": str(value),
                "source_id": "_candidates",
                **graph.translate_consistency_output_schema()}
    if kind == "style_guide":
        # Either a style_guide node or an optimize node feeds this; expose both
        # keys so build_* find the guide whichever produced it.
        return {"style_guide": str(value), "optimized_style_guide": str(value)}
    if kind == "metrics":
        # A score node's upstream metric vector (wired from eval node's
        # ``metrics`` output). Engine delivers the dict directly.
        return {"metrics": value if isinstance(value, dict) else {}}
    return value


# Per function: each input port's upstream *kind* (how to recover its dict).
_INPUT_KINDS: dict[str, dict[str, str]] = {
    "translate": {"terms": "datasource", "exemplars": "datasource",
                  "style_guide": "style_guide"},
    "translate_consistency": {"terms": "datasource", "exemplars": "datasource",
                              "style_guide": "style_guide"},
    "evaluate": {"translations": "translate_out", "reference": "datasource"},
    "evaluate_consistency": {"candidates": "candidates_out",
                             "reference": "datasource"},
    "optimize": {"trainset": "datasource", "devset": "datasource",
                 "seed_style_guide": "style_guide"},
    "evaluate_formula": {"metrics": "metrics"},
    "score_workflow_llm": {"metrics": "metrics"},
}

# Per function: which build_* compiler produces (cfg, kwargs) for its stage.
_BUILDERS: dict[str, Callable] = {
    "translate": graph.build_translate,
    "translate_consistency": graph.build_translate_consistency,
    "evaluate": graph.build_evaluate,
    "evaluate_consistency": graph.build_evaluate_consistency,
    "optimize": graph.build_optimize,
    "evaluate_formula": graph.build_evaluate_formula,
    "score_workflow_llm": graph.build_score_workflow_llm,
}

# Functions whose stage needs no assembled PipelineConfig (pure metric maths).
_NO_CONFIG = {"evaluate_formula"}


def _map_outputs(function: str, node_id: str, result: StageResult) -> dict[str, Any]:
    """Expose a StageResult's artifacts under this function's output-port names
    (so downstream nodes wire to them) plus the schema a dataset-shaped output
    advertises (so column checks downstream succeed)."""
    out: dict[str, Any] = {}
    o = result.outputs
    if function == "translate" and "output_csv" in o:
        p = str(o["output_csv"])
        out = {"translations": p, "dataset": p, "source_id": node_id,
               **graph.translate_output_schema()}
    elif function == "translate_consistency" and "candidates_csv" in o:
        p = str(o["candidates_csv"])
        out = {"candidates": p, "dataset": p, "source_id": node_id,
               **graph.translate_consistency_output_schema()}
        if o.get("prompts_json"):
            out["prompts_json"] = str(o["prompts_json"])
    elif function == "evaluate" and "scored_csv" in o:
        out = {"rows": str(o["scored_csv"])}
    elif function == "evaluate_consistency" and "scored_csv" in o:
        out = {"rows": str(o["scored_csv"])}
        if o.get("chosen_csv"):
            out["chosen"] = str(o["chosen_csv"])
    elif function == "optimize" and "optimized_style_guide" in o:
        p = str(o["optimized_style_guide"])
        out = {"optimized_style_guide": p, "style_guide": p}
    elif function in ("evaluate_formula", "score_workflow_llm"):
        # Single named scalar — surface it as the `score` output port too.
        name = next(iter(result.metrics), "score")
        out = {"score": result.metrics.get(name)}
    else:
        out = {k: str(v) for k, v in o.items()}
    return out


def _run_function(function: str, ctx: RunContext, inputs: dict[str, Any],
                  params: dict[str, Any]) -> FunctionResult:
    """Generic adapter: reconstruct a node + resolved dict, compile, run."""
    node_id = str(params.get("output_tag") or function)
    kinds = _INPUT_KINDS.get(function, {})
    # Synthesise the FlowNode + the resolved map the compiler reads. Each wired
    # input port becomes one synthetic upstream id keyed in ``resolved``.
    node_inputs: dict[str, str] = {}
    resolved: dict[str, dict] = {}
    for port, value in inputs.items():
        if value is None:
            continue
        up_id = f"_in_{port}"
        node_inputs[port] = up_id
        recovered = _recover_input(kinds.get(port, ""), value, ctx)
        resolved[up_id] = recovered if isinstance(recovered, dict) else {port: recovered}
    node = FlowNode(id=node_id, type=function, params=dict(params),
                    inputs=node_inputs)

    base_cfg = None if function in _NO_CONFIG else _assemble(ctx)
    try:
        cfg, kwargs = _BUILDERS[function](node, base_cfg, resolved)
    except graph.GraphError as exc:
        return FunctionResult(ok=False, message=f"compile failed: {exc}")

    runner = get_stage(function)
    result: StageResult = runner(cfg, ctx, **kwargs)
    return FunctionResult(
        ok=result.ok,
        outputs=_map_outputs(function, node_id, result),
        metrics={k: float(v) for k, v in result.metrics.items()},
        message=result.message,
    )


# --- Per-function runner entry points (referenced by FunctionSpec.runner) ----
def translate(ctx, inputs, params):  # noqa: D401
    return _run_function("translate", ctx, inputs, params)


def translate_consistency(ctx, inputs, params):
    return _run_function("translate_consistency", ctx, inputs, params)


def evaluate(ctx, inputs, params):
    return _run_function("evaluate", ctx, inputs, params)


def evaluate_consistency(ctx, inputs, params):
    return _run_function("evaluate_consistency", ctx, inputs, params)


def optimize(ctx, inputs, params):
    return _run_function("optimize", ctx, inputs, params)


def evaluate_formula(ctx, inputs, params):
    return _run_function("evaluate_formula", ctx, inputs, params)


def score_workflow_llm(ctx, inputs, params):
    return _run_function("score_workflow_llm", ctx, inputs, params)


def style_guide(ctx: RunContext, inputs: dict[str, Any],
                params: dict[str, Any]) -> FunctionResult:
    """Trivial source node: put a style-guide markdown file on the wire."""
    path = params.get("path")
    if not path:
        return FunctionResult(ok=False, message="style_guide node has no `path`")
    p = Path(str(path))
    if not p.exists():
        return FunctionResult(ok=False, message=f"style guide not found: {p}")
    return FunctionResult(ok=True, outputs={"style_guide": str(p)},
                          message=f"style guide {p.name}")


# ---------------------------------------------------------------------------
# Source resolver: a datasource node naming a project ``source``.
# ---------------------------------------------------------------------------
def resolve_source(node: Any, ctx: RunContext) -> dict[str, Any] | None:
    """Resolve a ``datasource`` node's ``source`` to its dataset + schema.

    Returns ``None`` (defer) when the node names no ``source`` — e.g. it uses a
    promoted ``data_object``, which the app handles itself.
    """
    params = getattr(node, "params", {}) or {}
    if not params.get("source"):
        return None
    out = graph.resolve_datasource(node, _registries(ctx))
    out["_primary"] = out.get("dataset")
    return out


# ---------------------------------------------------------------------------
# FunctionSpecs — ports + params the editor renders, and the runner path.
# ---------------------------------------------------------------------------
def _roles(function: str, port: str) -> list[str]:
    return PORT_REQUIRES.get(function, {}).get(port, [])


_RUN = "snomed_translation.functions"

translate_spec = FunctionSpec(
    name="translate", label="Translate", category="translate",
    description="Translate every concept in the wired term set, writing a "
                "translations CSV (sctid / English / translation).",
    inputs=[
        PortSpec(name="terms", label="Terms", kinds=["dataset"],
                 roles=_roles("translate", "terms"), required=True),
        PortSpec(name="exemplars", label="Exemplars", kinds=["dataset"],
                 roles=_roles("translate", "exemplars"), required=True),
        PortSpec(name="style_guide", label="Style guide",
                 kinds=["style_guide"], required=True),
    ],
    outputs=[PortSpec(name="translations", kinds=["dataset"],
                      roles=["sctid", "en", "target"])],
    params=[
        ParamSpec(name="model_key", label="Model", kind="model", required=True),
        ParamSpec(name="output_tag", label="Output tag", kind="text"),
        ParamSpec(name="limit", label="Row limit", kind="number"),
        ParamSpec(name="temperature", label="Temperature", kind="number"),
        ParamSpec(name="resume", label="Resume", kind="bool", default=False),
    ],
    runner=f"{_RUN}:translate",
)

translate_consistency_spec = FunctionSpec(
    name="translate_consistency", label="Translate (self-consistency)",
    category="translate",
    description="Translate every concept N times, writing a candidates CSV of "
                "distinct translations per concept.",
    inputs=[
        PortSpec(name="terms", label="Terms", kinds=["dataset"],
                 roles=_roles("translate_consistency", "terms"), required=True),
        PortSpec(name="exemplars", label="Exemplars", kinds=["dataset"],
                 roles=_roles("translate_consistency", "exemplars"),
                 required=True),
        PortSpec(name="style_guide", label="Style guide",
                 kinds=["style_guide"], required=True),
    ],
    outputs=[PortSpec(name="candidates", kinds=["candidates"],
                      roles=["sctid", "en", "candidates"])],
    params=[
        ParamSpec(name="model_key", label="Model", kind="model", required=True),
        ParamSpec(name="samples", label="Samples", kind="number", default=5),
        ParamSpec(name="output_tag", label="Output tag", kind="text"),
        ParamSpec(name="temperature", label="Temperature", kind="number"),
        ParamSpec(name="limit", label="Row limit", kind="number"),
    ],
    runner=f"{_RUN}:translate_consistency",
)

evaluate_spec = FunctionSpec(
    name="evaluate", label="Evaluate", category="evaluate",
    description="Score a translations CSV against the gold reference; emits "
                "composite_score / mean_chrf / exact_match_pct.",
    inputs=[
        PortSpec(name="translations", label="Translations", kinds=["dataset"],
                 roles=_roles("evaluate", "translations"), required=True),
        PortSpec(name="reference", label="Reference", kinds=["dataset"],
                 roles=_roles("evaluate", "reference"), required=True),
    ],
    outputs=[
        PortSpec(name="rows", label="Scored rows", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[ParamSpec(name="limit", label="Row limit", kind="number")],
    runner=f"{_RUN}:evaluate",
)

evaluate_consistency_spec = FunctionSpec(
    name="evaluate_consistency", label="Evaluate (self-consistency)",
    category="evaluate",
    description="Judge the best of each concept's candidate translations, then "
                "score the chosen translation against the reference.",
    inputs=[
        PortSpec(name="candidates", label="Candidates", kinds=["candidates"],
                 roles=_roles("evaluate_consistency", "candidates"),
                 required=True),
        PortSpec(name="reference", label="Reference", kinds=["dataset"],
                 roles=_roles("evaluate_consistency", "reference"),
                 required=True),
    ],
    outputs=[
        PortSpec(name="rows", label="Scored rows", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="model_key", label="Judge model", kind="model"),
        ParamSpec(name="thinking", label="Thinking", kind="select",
                  options=["off", "on"], default="off"),
        ParamSpec(name="explanation_language", label="Explanation language",
                  kind="text", default="English"),
        ParamSpec(name="limit", label="Row limit", kind="number"),
    ],
    runner=f"{_RUN}:evaluate_consistency",
)

optimize_spec = FunctionSpec(
    name="optimize", label="Optimize (GEPA)", category="optimize",
    description="Train a style guide with GEPA against the wired trainset; "
                "outputs an optimised style-guide file.",
    inputs=[
        PortSpec(name="trainset", label="Train set", kinds=["dataset"],
                 roles=_roles("optimize", "trainset"), required=True),
        PortSpec(name="devset", label="Dev set", kinds=["dataset"],
                 roles=_roles("optimize", "devset"), required=False),
        PortSpec(name="seed_style_guide", label="Seed style guide",
                 kinds=["style_guide"], required=False),
    ],
    outputs=[PortSpec(name="optimized_style_guide", kinds=["style_guide"])],
    params=[
        ParamSpec(name="model_key", label="Task model", kind="model",
                  required=True),
        ParamSpec(name="reflection_model_key", label="Reflection model",
                  kind="model"),
        ParamSpec(name="output_tag", label="Output tag", kind="text"),
        ParamSpec(name="train_limit", label="Train limit", kind="number"),
        ParamSpec(name="dev_limit", label="Dev limit", kind="number"),
    ],
    runner=f"{_RUN}:optimize",
)

evaluate_formula_spec = FunctionSpec(
    name="evaluate_formula", label="Score (formula)", category="score",
    description="Collapse an upstream evaluate node's metric vector to one "
                "scalar via a safe arithmetic expression.",
    inputs=[PortSpec(name="metrics", label="Metrics", kinds=["metrics"],
                     required=True)],
    outputs=[PortSpec(name="score", kinds=["score"])],
    params=[
        ParamSpec(name="expression", label="Expression", kind="textarea",
                  required=True,
                  help="e.g. 0.7*composite_score + 0.3*(mean_chrf/100)"),
        ParamSpec(name="output_name", label="Output name", kind="text",
                  default="score"),
    ],
    runner=f"{_RUN}:evaluate_formula",
)

score_workflow_llm_spec = FunctionSpec(
    name="score_workflow_llm", label="Score (LLM)", category="score",
    description="Render a prompt with the upstream metric vector and ask a "
                "model for a single scalar score.",
    inputs=[PortSpec(name="metrics", label="Metrics", kinds=["metrics"],
                     required=True)],
    outputs=[PortSpec(name="score", kinds=["score"])],
    params=[
        ParamSpec(name="prompt", label="Prompt", kind="textarea", required=True),
        ParamSpec(name="model_key", label="Model", kind="model"),
        ParamSpec(name="output_name", label="Output name", kind="text",
                  default="score"),
        ParamSpec(name="thinking", label="Thinking", kind="bool", default=False),
    ],
    runner=f"{_RUN}:score_workflow_llm",
)

style_guide_spec = FunctionSpec(
    name="style_guide", label="Style guide", category="translate",
    description="A static style-guide markdown file, put on the wire for a "
                "translate or optimize node to consume.",
    inputs=[],
    outputs=[PortSpec(name="style_guide", kinds=["style_guide"])],
    params=[ParamSpec(name="path", label="File", kind="style_guide",
                      required=True)],
    runner=f"{_RUN}:style_guide",
)


def specs() -> list[FunctionSpec]:
    return [
        translate_spec, translate_consistency_spec, evaluate_spec,
        evaluate_consistency_spec, optimize_spec, evaluate_formula_spec,
        score_workflow_llm_spec, style_guide_spec,
    ]


def install() -> None:
    """Register all functions + the source resolver in-process (tests)."""
    from pipelines import registry
    for s in specs():
        registry.register(s)
    registry.register_source("snomed_translation", resolve_source)
