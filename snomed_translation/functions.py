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


def _read_sctids(path: str) -> set[str] | None:
    """Read a column of concept ids (sctid / conceptId / id) from a CSV, to scope
    an index build. None if the file is absent or empty."""
    import csv as _csv
    p = Path(str(path))
    if not p.exists():
        return None
    ids: set[str] = set()
    with p.open(encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            v = row.get("sctid") or row.get("conceptId") or row.get("id")
            if v and v.strip():
                ids.add(v.strip())
    return ids or None


def build_snomed_index(ctx: RunContext, inputs: dict[str, Any],
                       params: dict[str, Any]) -> FunctionResult:
    """Build a hybrid semantic index over the SNOMED terminology (FSN + synonyms)
    from a local International RF2 release, for back-translation lookup. Emits an
    index manifest (a DataObject to promote + reuse)."""
    rf2 = params.get("rf2_root")
    if not rf2:
        return FunctionResult(ok=False, message="build_snomed_index needs `rf2_root`")
    if not Path(str(rf2)).exists():
        return FunctionResult(ok=False, message=f"rf2_root not found: {rf2}")
    model = str(params.get("embedding_model") or "BAAI/bge-m3")
    scope = _read_sctids(params["scope_csv"]) if params.get("scope_csv") else None
    try:
        from snomed_translation.snomed_index import build_index
        manifest = build_index(str(rf2), embedding_model=model, scope=scope)
    except Exception as exc:  # surfaced in the run journal, not raised
        return FunctionResult(ok=False, message=f"index build failed: {exc}")
    return FunctionResult(
        ok=True,
        outputs={"index": manifest},
        metrics={"n_concepts": float(manifest["n_concepts"]),
                 "n_points": float(manifest["n_points"])},
        message=(f"indexed {manifest['n_concepts']} concepts "
                 f"({manifest['n_points']} surface forms) from "
                 f"{manifest['release_id']} -> {manifest['collection']}"),
    )


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

generate_text_spec = FunctionSpec(
    name="generate_text", label="Generate (LLM, Agent SDK)", category="generate",
    description="Render a prompt template with wired/given context and ask a SOTA "
                "Claude model (via the Claude Agent SDK, reusing the host's "
                "subscription auth) for a single text result, written to a file. "
                "The output is a `text` artifact that also presents as a "
                "`style_guide` — wire it into a translate node or seed GEPA. First "
                "use: induce an EN->KO instruction prompt from a pruned corpus.",
    inputs=[
        PortSpec(name="context", label="Context", kinds=["dataset", "text",
                 "style_guide"], required=False, multiple=True),
    ],
    outputs=[PortSpec(name="text", kinds=["text"])],
    params=[
        ParamSpec(name="prompt_template", label="Prompt template", kind="text",
                  help="Id of a stored prompt template to use as the prompt "
                       "(overrides the inline Prompt below). The resolved body + "
                       "its version hash are recorded on the run for reproducibility."),
        ParamSpec(name="prompt", label="Prompt", kind="textarea", required=False,
                  help="Inline instruction template (used when no prompt_template "
                       "is set). {{context}} inserts the assembled context (wired "
                       "inputs + context_paths files); {{portname}} inserts one "
                       "wired input by its port name."),
        ParamSpec(name="model", label="Model", kind="text", default="opus",
                  help="Claude Agent SDK model alias (e.g. opus, sonnet) or id."),
        ParamSpec(name="thinking", label="Extended thinking", kind="bool",
                  default=True),
        ParamSpec(name="effort", label="Thinking effort", kind="select",
                  default="high", options=["low", "medium", "high", "max"]),
        ParamSpec(name="max_thinking_tokens", label="Max thinking tokens",
                  kind="number",
                  help="Thinking budget in tokens (0 = 16000 default)."),
        ParamSpec(name="system", label="System prompt", kind="textarea"),
        ParamSpec(name="context_paths", label="Context file paths", kind="text",
                  help="Comma-separated md/csv/txt files concatenated into "
                       "{{context}} (no wiring needed). cwd = configs dir."),
        ParamSpec(name="max_context_chars", label="Max context chars",
                  kind="number", default=400000,
                  help="Truncation guard for the assembled context."),
        ParamSpec(name="output_tag", label="Output tag", kind="text",
                  default="generated"),
        ParamSpec(name="output_ext", label="Output extension", kind="text",
                  default="md"),
    ],
    runner="snomed_translation.generate:generate_text",
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

build_snomed_index_spec = FunctionSpec(
    name="build_snomed_index", label="Build SNOMED index", category="index",
    description="Embed concept surface forms (FSN + synonyms) from a local "
                "International RF2 release into a hybrid Qdrant collection for "
                "back-translation lookup. Outputs an index manifest to promote "
                "as a reusable DataObject (it records the release + embedding "
                "model so a rebuild is reproducible).",
    inputs=[],
    outputs=[PortSpec(name="index", kinds=["index"])],
    params=[
        ParamSpec(name="rf2_root", label="RF2 release root", kind="text",
                  required=True,
                  help="Path to a SNOMED International RF2 release directory."),
        ParamSpec(name="embedding_model", label="Embedding model", kind="text",
                  default="BAAI/bge-m3"),
        ParamSpec(name="scope_csv", label="Scope CSV (optional)", kind="text",
                  help="CSV with an sctid column to restrict the index; "
                       "empty = the whole terminology."),
    ],
    runner=f"{_RUN}:build_snomed_index",
)

snomed_retrieve_spec = FunctionSpec(
    name="snomed_retrieve", label="SNOMED retrieve", category="index",
    description="Look up back-translated English terms against a SNOMED index "
                "and report, per query, the top concept and whether/where the "
                "original concept was recovered — the round-trip confidence "
                "signal. Feeds a score/distance node.",
    inputs=[
        PortSpec(name="index", label="Index", kinds=["index"], required=True),
        PortSpec(name="queries", label="Queries", kinds=["dataset"],
                 required=True),
    ],
    outputs=[PortSpec(name="matches", kinds=["dataset"])],
    params=[
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid",
                  help="Column in the queries dataset holding the ORIGINAL "
                       "concept id (gold), for measuring recovery."),
        ParamSpec(name="query_col", label="Query column", kind="text",
                  default="query",
                  help="Column holding the query term (back-translated English, "
                       "or Korean for a direct multilingual lookup)."),
        ParamSpec(name="mode", label="Retrieval mode", kind="select",
                  default="hybrid", options=["hybrid", "dense", "sparse"]),
        ParamSpec(name="search_depth", label="Search depth", kind="number",
                  default=25,
                  help="How deep to look for the gold concept (sets the max K for "
                       "recall@K)."),
    ],
    runner=f"{_RUN}:snomed_retrieve",
)


def back_translate(ctx: RunContext, inputs: dict[str, Any],
                   params: dict[str, Any]) -> FunctionResult:
    """Translate each Korean term in the wired dataset to English (KO->EN) via an
    LLM, for round-trip SNOMED lookup. Output dataset: {id_col, out_col=query}."""
    import csv as _csv
    qpath = _dataset_path(inputs.get("queries"))
    if not qpath or not Path(qpath).exists():
        return FunctionResult(ok=False, message="back_translate: no `queries` dataset wired")
    model_id = params.get("model_id")
    if not model_id:
        return FunctionResult(ok=False, message="back_translate needs `model_id`")
    base_url = str(params.get("base_url") or "http://localhost:8086")
    id_col = str(params.get("id_col") or "sctid")
    src_col = str(params.get("source_col") or "korean")
    out_col = str(params.get("out_col") or "query")
    from snomed_translation.back_translate import DEFAULT_SYSTEM, back_translate_terms
    system = str(params.get("system") or DEFAULT_SYSTEM)
    fmt = str(params.get("format") or "chat")
    src_lang = str(params.get("source_lang") or "Korean")
    src_code = str(params.get("source_lang_code") or "ko")
    tgt_lang = str(params.get("target_lang") or "English")
    tgt_code = str(params.get("target_lang_code") or "en")
    concurrency = int(params.get("concurrency") or 1)

    rows: list[tuple[str, str]] = []
    with Path(qpath).open(encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            rows.append(((r.get(id_col) or "").strip(), (r.get(src_col) or "").strip()))
    if not rows:
        return FunctionResult(ok=False, message=f"back_translate: no rows in {qpath}")
    try:
        english = back_translate_terms(
            [k for _, k in rows], base_url=base_url, model_id=str(model_id),
            system=system, fmt=fmt, source_lang=src_lang, source_code=src_code,
            target_lang=tgt_lang, target_code=tgt_code, concurrency=concurrency)
    except Exception as exc:
        return FunctionResult(ok=False, message=f"back-translation failed: {exc}")

    out = Path(ctx.log_dir) / "back_translate.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=[id_col, out_col])
        w.writeheader()
        for (sid, _), en in zip(rows, english):
            w.writerow({id_col: sid, out_col: en})
    return FunctionResult(ok=True, outputs={"translations": str(out)},
                          metrics={"n": float(len(rows))},
                          message=f"back-translated {len(rows)} terms via {model_id}")


def _index_collection(value: Any) -> str | None:
    """The Qdrant collection name from a wired `index` input — a manifest dict,
    a path to its JSON, or a bare collection name."""
    if isinstance(value, dict):
        return value.get("collection")
    if isinstance(value, str) and value:
        p = Path(value)
        if value.endswith(".json") and p.exists():
            import json as _json
            try:
                return _json.loads(p.read_text(encoding="utf-8")).get("collection")
            except Exception:
                return None
        return value   # a bare collection name
    return None


def _dataset_path(value: Any) -> str | None:
    """The CSV path from a wired dataset input (a path string or a resolved dict)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in ("_primary", "dataset", "rows", "path"):
            if isinstance(value.get(k), str):
                return value[k]
    return None


def _recall_metrics(rows: list[dict]) -> dict:
    """recall@K + MRR over result rows (each with ``sctid`` gold + ``correct_rank``)
    — shared by the retrieve and rerank nodes so their metrics are comparable."""
    gold = [r for r in rows if r["sctid"]]
    n = len(gold)

    def at(k: int) -> float:
        return 100.0 * sum(1 for r in gold if 0 < r["correct_rank"] <= k) / n if n else 0.0

    mrr = (sum(1.0 / r["correct_rank"] for r in gold if r["correct_rank"] > 0)
           / n) if n else 0.0
    return {"n_queries": float(len(rows)), "recovered_pct": at(1),
            "recall_at_3_pct": at(3), "recall_at_5_pct": at(5),
            "recall_at_10_pct": at(10), "mrr": round(mrr, 4)}


def snomed_retrieve(ctx: RunContext, inputs: dict[str, Any],
                    params: dict[str, Any]) -> FunctionResult:
    """Look up back-translated English terms against a SNOMED index, emitting per
    query the top concept + whether/where the *original* concept was recovered —
    the round-trip confidence signal. Wire an `index` (from build_snomed_index or
    a promoted index) + a `queries` dataset (an id column + a query-text column)."""
    import csv as _csv

    collection = _index_collection(inputs.get("index"))
    if not collection:
        return FunctionResult(ok=False, message="snomed_retrieve: no `index` wired "
                              "(connect build_snomed_index or a promoted index)")
    qpath = _dataset_path(inputs.get("queries"))
    if not qpath or not Path(qpath).exists():
        return FunctionResult(ok=False, message="snomed_retrieve: no `queries` dataset wired")

    id_col = str(params.get("id_col") or "sctid")
    query_col = str(params.get("query_col") or "query")
    mode = str(params.get("mode") or "hybrid")
    search_depth = int(params.get("search_depth") or 25)
    queries: list[tuple[str, str]] = []
    with Path(qpath).open(encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            q = (row.get(query_col) or "").strip()
            if q:
                queries.append(((row.get(id_col) or "").strip(), q))
    if not queries:
        return FunctionResult(ok=False,
                              message=f"snomed_retrieve: no {query_col!r} values in {qpath}")

    try:
        from snomed_translation.snomed_index import retrieve_concepts
        rows = retrieve_concepts(collection, queries, limit=search_depth,
                                 search_depth=search_depth, mode=mode)
    except Exception as exc:
        return FunctionResult(ok=False, message=f"retrieval failed: {exc}")

    out = Path(ctx.log_dir) / "snomed_retrieve.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # recall@K: did the *correct* concept land in the top K (meaning preserved,
    # even if not #1)? correct_rank is 0 when the gold isn't in the top search_depth.
    metrics = _recall_metrics(rows)
    return FunctionResult(
        ok=True, outputs={"matches": str(out)}, metrics=metrics,
        message=(f"retrieved {len(rows)} queries against {collection} [{mode}]; "
                 f"recall@1={metrics['recovered_pct']:.0f}% "
                 f"@5={metrics['recall_at_5_pct']:.0f}% "
                 f"@10={metrics['recall_at_10_pct']:.0f}%"),
    )


def rerank(ctx: RunContext, inputs: dict[str, Any],
           params: dict[str, Any]) -> FunctionResult:
    """Retrieve the top-K candidates per query, then re-rank them with a
    cross-encoder (BAAI/bge-reranker-v2-m3), measuring recall@K *after* rerank.
    The reranker is multilingual, so the query may be back-translated English or
    Korean (set mode=dense for a direct cross-lingual rerank)."""
    import csv as _csv
    collection = _index_collection(inputs.get("index"))
    if not collection:
        return FunctionResult(ok=False, message="rerank: no `index` wired")
    qpath = _dataset_path(inputs.get("queries"))
    if not qpath or not Path(qpath).exists():
        return FunctionResult(ok=False, message="rerank: no `queries` dataset wired")
    id_col = str(params.get("id_col") or "sctid")
    query_col = str(params.get("query_col") or "query")
    mode = str(params.get("mode") or "hybrid")
    top_k = int(params.get("top_k") or 10)
    model = str(params.get("reranker_model") or "BAAI/bge-reranker-v2-m3")

    queries: list[tuple[str, str]] = []
    with Path(qpath).open(encoding="utf-8") as f:
        for row in _csv.DictReader(f):
            q = (row.get(query_col) or "").strip()
            if q:
                queries.append(((row.get(id_col) or "").strip(), q))
    if not queries:
        return FunctionResult(ok=False, message=f"rerank: no {query_col!r} values in {qpath}")

    try:
        from snomed_translation.rerank import Reranker, retrieve_and_rerank
        rows = retrieve_and_rerank(collection, queries, top_k=top_k, mode=mode,
                                   reranker=Reranker(model))
    except Exception as exc:
        return FunctionResult(ok=False, message=f"rerank failed: {exc}")

    out = Path(ctx.log_dir) / "rerank.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    metrics = _recall_metrics(rows)
    return FunctionResult(
        ok=True, outputs={"matches": str(out)}, metrics=metrics,
        message=(f"reranked top-{top_k} [{mode}] via {model}; "
                 f"recall@1={metrics['recovered_pct']:.0f}% "
                 f"@5={metrics['recall_at_5_pct']:.0f}% "
                 f"@10={metrics['recall_at_10_pct']:.0f}%"),
    )


back_translate_spec = FunctionSpec(
    name="back_translate", label="Back-translate (KO->EN)", category="translate",
    description="Translate each Korean term in the wired dataset to English via an "
                "LLM (KO->EN), for round-trip SNOMED lookup. Output: {id, query}.",
    inputs=[PortSpec(name="queries", label="Terms", kinds=["dataset"], required=True)],
    outputs=[PortSpec(name="translations", kinds=["dataset"])],
    params=[
        ParamSpec(name="model_id", label="Model id", kind="text", required=True,
                  help="The served model id (e.g. an OpenAI-compatible vLLM id)."),
        ParamSpec(name="base_url", label="Base URL", kind="text",
                  default="http://localhost:8086"),
        ParamSpec(name="source_col", label="Korean column", kind="text",
                  default="korean"),
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid"),
        ParamSpec(name="out_col", label="Output column", kind="text", default="query"),
        ParamSpec(name="system", label="System prompt", kind="textarea"),
        ParamSpec(name="format", label="Prompt format", kind="select",
                  default="chat", options=["chat", "translategemma"],
                  help="`chat` = system+user instruction (most models). "
                       "`translategemma` = structured translation prompt via the "
                       "completions endpoint (for google/translategemma-*)."),
        ParamSpec(name="source_lang", label="Source language", kind="text",
                  default="Korean"),
        ParamSpec(name="source_lang_code", label="Source code", kind="text",
                  default="ko"),
        ParamSpec(name="target_lang", label="Target language", kind="text",
                  default="English"),
        ParamSpec(name="target_lang_code", label="Target code", kind="text",
                  default="en"),
        ParamSpec(name="concurrency", label="Concurrency", kind="number",
                  default=1, help="Parallel LLM calls (vLLM batches them). A "
                                  "throughput sweep on gemma4-26b-qat plateaus "
                                  "~128 (≈2.4x over 24); use 128 at extension scale."),
    ],
    runner=f"{_RUN}:back_translate",
)


rerank_spec = FunctionSpec(
    name="rerank", label="Rerank (cross-encoder)", category="index",
    description="Retrieve top-K candidates per query, then re-rank them with a "
                "cross-encoder (BAAI/bge-reranker-v2-m3) and measure recall@K "
                "after rerank. Multilingual — query may be back-translated English "
                "or (with mode=dense) Korean directly.",
    inputs=[
        PortSpec(name="index", label="Index", kinds=["index"], required=True),
        PortSpec(name="queries", label="Queries", kinds=["dataset"], required=True),
    ],
    outputs=[PortSpec(name="matches", kinds=["dataset"])],
    params=[
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid"),
        ParamSpec(name="query_col", label="Query column", kind="text", default="query"),
        ParamSpec(name="mode", label="Retrieval mode", kind="select",
                  default="hybrid", options=["hybrid", "dense", "sparse"]),
        ParamSpec(name="top_k", label="Candidates to rerank", kind="number", default=10),
        ParamSpec(name="reranker_model", label="Reranker", kind="text",
                  default="BAAI/bge-reranker-v2-m3"),
    ],
    runner=f"{_RUN}:rerank",
)


def specs() -> list[FunctionSpec]:
    return [
        translate_spec, translate_consistency_spec, evaluate_spec,
        evaluate_consistency_spec, optimize_spec, evaluate_formula_spec,
        score_workflow_llm_spec, generate_text_spec, style_guide_spec,
        build_snomed_index_spec,
        snomed_retrieve_spec, back_translate_spec, rerank_spec,
    ]


def install() -> None:
    """Register all functions + the source resolver in-process (tests)."""
    from pipelines import registry
    for s in specs():
        registry.register(s)
    registry.register_source("snomed_translation", resolve_source)
