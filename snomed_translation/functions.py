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
def _configs_base(ctx: RunContext) -> Path:
    """The configs root for a run. A run subprocess sets ``ctx.configs_dir`` to
    the useless default ``configs`` (cwd-relative, empty here) but DOES carry the
    ``WIZARD_*_DIR`` env overrides — all co-located under one configs dir in this
    deployment — so derive the base from one of them first, then fall back to
    ctx.configs_dir. Fixes datasource/translate/evaluate runs launched by the
    wizard/MCP runner (which don't pass a configs dir)."""
    import os
    for env in ("WIZARD_INVESTIGATIONS_DIR", "WIZARD_PROJECTS_DIR",
                "WIZARD_SOURCES_DIR", "WIZARD_FLOWS_DIR", "WIZARD_PROMPTS_DIR"):
        v = os.environ.get(env)
        if v:
            return Path(v).parent
    cd = getattr(ctx, "configs_dir", None)
    return Path(cd) if cd else Path("configs")


def _resolve_asset(ctx: RunContext, path: str) -> Path:
    """Resolve a flow-config relative asset path (e.g. ``style_guide/x.md``,
    ``data/…``) that is written relative to the PLUGIN ROOT. A run subprocess'
    cwd is the app dir (which only symlinks ``data/``, not ``style_guide/``), so
    an as-is relative path may miss. Try: as given (cwd) → plugin-root/path (root
    = parent of the configs base derived from WIZARD_*) → WIZARD_STYLE_GUIDES_DIR/
    basename. Returns the first existing candidate, else the original."""
    import os
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p
    root = _configs_base(ctx).parent           # the plugin repo root
    for cand in (root / path,):
        if cand.exists():
            return cand
    sg = os.environ.get("WIZARD_STYLE_GUIDES_DIR")
    if sg and (Path(sg) / p.name).exists():
        return Path(sg) / p.name
    return p


def _registries(ctx: RunContext) -> Registries:
    cached = ctx.extras.get("registries")
    if cached is not None:
        return cached
    # Honour the WIZARD_* env overrides first (a run subprocess launched by the
    # wizard/MCP runner carries them but NOT ctx.configs_dir, which defaults to
    # the cwd's empty ``configs/``); fall back to ctx.configs_dir/<default>. This
    # mirrors how prompt_source resolves WIZARD_PROMPTS_DIR.
    import os
    base = _configs_base(ctx)
    reg = Registries.load(
        models_json=os.environ.get("WIZARD_MODELS_JSON") or base / "models.json",
        sources_dir=os.environ.get("WIZARD_SOURCES_DIR") or base / "sources",
        resources_path=(os.environ.get("WIZARD_RESOURCES_PATH")
                        or base / "resources_ko.yaml"),
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
    base = _configs_base(ctx)
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
    dynamic = _dynamic_dataset_dict(path)
    if dynamic is not None:
        return dynamic
    raise graph.GraphError(
        f"could not map dataset path {path!r} back to a known source; "
        f"available: {sorted(reg.sources)}")


def _dynamic_dataset_dict(path: str) -> dict[str, Any] | None:
    """Recover schema for a run-generated CSV that is not a named source."""
    header = graph.read_csv_header(path)
    if header is None:
        return None
    lower = {column.lower(): column for column in header}
    roles: dict[str, str] = {}
    for role, aliases in graph.ROLE_ALIASES.items():
        for alias in aliases:
            if alias in lower:
                roles[role] = lower[alias]
                break
    return {
        "dataset": path,
        "source_id": "_dynamic_dataset",
        "roles": roles,
        "present": list(roles),
        "columns": header,
        "built": True,
    }


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

    if function == "optimize" and cfg is not None and cfg.optimization is not None:
        # The optimization recipe carries plugin-relative asset paths
        # (configs/hard_rules/…, configs/hints/…, the lookup cache, an optional
        # seed guide). A run subprocess' cwd is the app dir, which only symlinks
        # data/ — so resolve them against the plugin root, same as style_guide/
        # data assets (§ _resolve_asset). Without this, GEPA runs launched by the
        # wizard/MCP runner fail with "hard_rules_file not found".
        opt = cfg.optimization
        for attr in ("hard_rules_file", "hints_file", "lookup_cache",
                     "seed_style_guide"):
            val = getattr(opt, attr, None)
            if val is not None:
                setattr(opt, attr, _resolve_asset(ctx, str(val)))

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
    p = _resolve_asset(ctx, str(path))
    if not p.exists():
        return FunctionResult(ok=False, message=f"style guide not found: {path}")
    return FunctionResult(ok=True, outputs={"style_guide": str(p)},
                          message=f"style guide {p.name}")


def text_source(ctx: RunContext, inputs: dict[str, Any],
                params: dict[str, Any]) -> FunctionResult:
    """Source node: put a text/corpus file (md/txt/csv) on the wire as a `text`
    artifact. The downstream generate_text node reads its contents into
    ``{{context}}`` — the wired-node twin of its ``context_paths`` param."""
    path = params.get("path")
    if not path:
        return FunctionResult(ok=False, message="text_source node has no `path`")
    p = Path(str(path))
    if not p.exists():
        return FunctionResult(ok=False, message=f"text file not found: {p}")
    return FunctionResult(ok=True, outputs={"text": str(p)},
                          message=f"text {p.name}")


def prompt_source(ctx: RunContext, inputs: dict[str, Any],
                  params: dict[str, Any]) -> FunctionResult:
    """Source node: put a stored prompt template on the wire as a `prompt`
    artifact. Emits the resolved body plus the template id + content-hash version
    so a generate_text node downstream pins the exact revision it ran (design
    D4). Prompts dir: ``WIZARD_PROMPTS_DIR`` env, else ``<configs_dir>/prompts``."""
    import os
    tid = params.get("prompt_template")
    if not tid:
        return FunctionResult(
            ok=False, message="prompt_source node has no `prompt_template`")
    base = os.environ.get("WIZARD_PROMPTS_DIR")
    if not base:
        cfg = getattr(ctx, "configs_dir", None)
        base = str(Path(cfg) / "prompts") if cfg else "configs/prompts"
    try:
        from pipelines.prompts import load_template
        t = load_template(base, str(tid))
    except FileNotFoundError as exc:
        return FunctionResult(ok=False, message=str(exc))
    if not t.body:
        return FunctionResult(ok=False, message=f"prompt template {tid!r} has no body")
    return FunctionResult(
        ok=True,
        outputs={"prompt": {"body": t.body, "prompt_template": str(tid),
                            "prompt_version": t.current_version or ""}},
        message=f"prompt {tid} @ {t.current_version or '?'}")


def _prompt_body_of(value: Any) -> str:
    """Extract the prompt body from a wired input: a prompt_source dict, a path
    (read the file), or a raw string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for k in ("body", "prompt", "text", "style_guide", "_primary", "path"):
            v = value.get(k)
            if isinstance(v, str):
                value = v
                break
        else:
            return ""
    s = str(value)
    p = Path(s)
    if len(s) < 4096 and p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return s


def _slugify(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-zA-Z0-9_-]+", "-", s.strip()).strip("-_") or "prompt"


def promote_prompt(ctx: RunContext, inputs: dict[str, Any],
                   params: dict[str, Any]) -> FunctionResult:
    """Sink node: persist a wired prompt/text into the PromptTemplate store as a
    new versioned template. Because it runs INSIDE a flow run, the stored template
    always gets **provenance='flow'** with this run's id as its ``provenance_run``
    (the run pins the flow + shas) — that IS its provenance. Generalises GEPA's
    bespoke publish so ANY flow emitting an improved/derived prompt (induction,
    optimize, a future rewriter) makes it a first-class stored prompt via wiring.
    ``parent`` = the template this improves (lineage); ``origin`` = the prompt that
    produced it. Prompts dir: ``WIZARD_PROMPTS_DIR`` env, else
    ``<configs_dir>/prompts``; a ``style_guide`` kind is also written to
    ``WIZARD_STYLE_GUIDES_DIR`` as a bare ``<id>.md`` so translate nodes resolve
    it by path."""
    import os
    from pipelines.prompts import promote_to_store
    body = _prompt_body_of(inputs.get("prompt"))
    if not body.strip():
        return FunctionResult(ok=False, message="promote_prompt: no `prompt` body wired")
    kind = str(params.get("kind") or "style_guide")
    parent = params.get("parent") or None
    run_id = getattr(ctx, "run_id", None)
    tid = params.get("id") or (
        _slugify(f"{parent}__improved") if parent else _slugify("flow-prompt"))
    tags = [t.strip() for t in str(params.get("tags") or "").split(",") if t.strip()]

    base = os.environ.get("WIZARD_PROMPTS_DIR")
    if not base:
        cfg = getattr(ctx, "configs_dir", None)
        base = str(Path(cfg) / "prompts") if cfg else "configs/prompts"
    try:
        t = promote_to_store(
            prompts_dir=base, id=tid, body=body, kind=kind, provenance="flow",
            provenance_run=run_id, parent=parent, origin=params.get("origin"),
            name=params.get("name") or tid, tags=tags, notes=params.get("notes"),
            style_guides_dir=os.environ.get("WIZARD_STYLE_GUIDES_DIR"))
    except Exception as exc:  # surfaced as a stage failure, not raised
        return FunctionResult(ok=False, message=f"promote_prompt failed: {exc}")
    return FunctionResult(
        ok=True,
        outputs={"prompt_template": tid, "prompt_version": t.current_version or ""},
        message=(f"promoted prompt {tid} @ {t.current_version or '?'} "
                 f"(provenance=flow, run={run_id}"
                 + (f", parent={parent}" if parent else "") + ")"))


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
        # Optional SNOMED defining-attribute context, keyed by sctid.
        ParamSpec(name="attributes_json", label="Concept attributes JSON",
                  kind="text"),
        # Force reasoning on/off per node across backends (Claude `thinking`,
        # vLLM/DashScope `enable_thinking`); unset inherits the model default.
        ParamSpec(name="thinking", label="Reasoning/thinking mode", kind="bool"),
        ParamSpec(name="model_key", label="Model", kind="model", required=True),
        ParamSpec(name="output_tag", label="Output tag", kind="text"),
        ParamSpec(name="limit", label="Row limit", kind="number"),
        ParamSpec(name="temperature", label="Temperature", kind="number"),
        ParamSpec(name="resume", label="Resume", kind="bool", default=False),
        ParamSpec(name="request_timeout_seconds", label="Request timeout (s)",
                  kind="number", default=120),
        ParamSpec(name="max_attempts", label="Maximum attempts", kind="number",
                  default=3),
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
        PortSpec(name="prompt", label="Prompt", kinds=["prompt", "text"],
                 required=False),
        PortSpec(name="context", label="Context", kinds=["dataset", "text",
                 "style_guide"], required=False, multiple=True),
    ],
    outputs=[PortSpec(name="text", kinds=["text"])],
    params=[
        ParamSpec(name="prompt_template", label="Prompt template", kind="prompt",
                  help="Id of a stored prompt template to use as the prompt "
                       "(used when no Prompt node is wired; a wired prompt wins). "
                       "The resolved body + its version hash are recorded on the "
                       "run for reproducibility."),
        ParamSpec(name="prompt", label="Prompt", kind="textarea", required=False,
                  help="Inline instruction template (used when no prompt_template "
                       "is set). {{context}} inserts the assembled context (wired "
                       "inputs + context_paths files); {{portname}} inserts one "
                       "wired input by its port name."),
        ParamSpec(name="model", label="Model", kind="model", default="claude-opus",
                  help="A models.json entry — an Agent-SDK Claude model "
                       "(claude-opus/claude-sonnet) or any served model. A bare "
                       "SDK alias (e.g. 'opus') not in the catalogue still works."),
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

text_source_spec = FunctionSpec(
    name="text_source", label="Text / corpus file", category="generate",
    description="A static text/corpus file (md/txt/csv) put on the wire as a "
                "`text` artifact for a generate_text node to read into its "
                "{{context}}. The wired-node twin of generate_text's "
                "`context_paths` param.",
    inputs=[],
    outputs=[PortSpec(name="text", kinds=["text"])],
    params=[ParamSpec(name="path", label="File", kind="text", required=True,
                      help="Path to an md/txt/csv file. cwd = the app dir "
                           "(the `data/` symlink resolves into the plugin).")],
    runner=f"{_RUN}:text_source",
)

prompt_source_spec = FunctionSpec(
    name="prompt_source", label="Prompt", category="generate",
    description="A stored prompt template put on the wire as a `prompt` artifact "
                "for a generate_text node. Emits the resolved body + the template "
                "id/version, so the run pins the exact revision it used.",
    inputs=[],
    outputs=[PortSpec(name="prompt", kinds=["prompt"])],
    params=[ParamSpec(name="prompt_template", label="Prompt template",
                      kind="prompt", required=True,
                      help="Id of a stored prompt template.")],
    runner=f"{_RUN}:prompt_source",
)

promote_prompt_spec = FunctionSpec(
    name="promote_prompt", label="Promote prompt (to store)", category="generate",
    description="Persist a wired prompt/text into the PromptTemplate store as a "
                "new versioned template. Runs inside a flow run, so the stored "
                "prompt always gets provenance='flow' with this run's id (that IS "
                "its provenance). Generalises GEPA's publish: wire any node that "
                "emits an improved/derived prompt (generate_text, optimize) into "
                "this to make it a first-class stored prompt. Outputs the id.",
    inputs=[PortSpec(name="prompt", label="Prompt",
                     kinds=["text", "prompt", "style_guide"], required=True)],
    outputs=[PortSpec(name="prompt_template", kinds=["prompt"])],
    params=[
        ParamSpec(name="id", label="New template id", kind="text",
                  help="Slug for the stored prompt. Blank = derived from parent."),
        ParamSpec(name="kind", label="Kind", kind="select", default="style_guide",
                  options=["style_guide", "induction", "scoring",
                           "translate_system", "judge", "freeform"]),
        ParamSpec(name="parent", label="Parent (lineage)", kind="prompt",
                  help="Template id this IMPROVES (v1→v2 lineage). Blank = a new "
                       "root. NOT the prompt that produced it — see Origin."),
        ParamSpec(name="origin", label="Origin (produced-by)", kind="prompt",
                  help="The prompt that PRODUCED this output (e.g. the induction "
                       "prompt). Recorded in notes/tags for traceability."),
        ParamSpec(name="name", label="Name", kind="text"),
        ParamSpec(name="tags", label="Tags", kind="text", help="Comma-separated."),
        ParamSpec(name="notes", label="Notes", kind="textarea"),
    ],
    runner=f"{_RUN}:promote_prompt",
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


transliteration_detect_spec = FunctionSpec(
    name="transliteration_detect", label="Transliteration detect", category="detect",
    description="Deterministic MT error gate: flag Korean translations that are "
                "pure phonetic transliterations of the English source (e.g. "
                "Herniogram -> 허니오그램) — the failure mode embedding/back-"
                "translation confidence is blind to. Consonant-skeleton phonetic "
                "echo, gated by native/Sino morpheme coverage from a dictionary "
                "(the register oracle). Emits per-row flags + a false-positive "
                "proxy when the input carries an SME-rating column.",
    inputs=[
        PortSpec(name="translations", label="Translations", kinds=["dataset"],
                 required=True),
        PortSpec(name="dictionary", label="KO dictionary", kinds=["dataset"],
                 required=False),
    ],
    outputs=[
        PortSpec(name="flags", label="Per-row flags", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="echo_threshold", label="Echo threshold", kind="number",
                  default=0.80, help="Min consonant-skeleton similarity to flag."),
        ParamSpec(name="cov_threshold", label="Coverage threshold", kind="number",
                  default=0.20, help="Max native/Sino dictionary coverage to flag."),
        ParamSpec(name="en_col", label="English column", kind="text",
                  help="Override the datasource's `en` role."),
        ParamSpec(name="ko_col", label="Korean column", kind="text",
                  help="Override the datasource's `target` role (candidate KO)."),
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid"),
        ParamSpec(name="label_col", label="SME-rating column", kind="text",
                  default="sme_rating",
                  help="If present in the input, adds a false-positive proxy."),
        ParamSpec(name="dict_col", label="Dictionary term column", kind="text",
                  default="ko_term"),
    ],
    runner="snomed_translation.transliteration:transliteration_detect",
)

acceptability_judge_spec = FunctionSpec(
    name="acceptability_judge", label="Acceptability judge (LLM)", category="detect",
    description="Reference-free LLM judge: would a Korean SNOMED terminologist "
                "accept this EN->KO translation? Labels ACCEPTABLE/PARTIAL/WRONG "
                "+ a 0-1 score + reason. Catches semantic errors distance metrics "
                "miss. Routes on `model`: a Claude alias (opus/sonnet/…) uses the "
                "Agent SDK; anything else is a vLLM hf_id over `base_url`. Reports "
                "agreement with the SME when the input carries an SME-rating column.",
    inputs=[
        PortSpec(name="translations", label="Translations", kinds=["dataset"],
                 required=True),
    ],
    outputs=[
        PortSpec(name="judgements", label="Per-row judgements", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="model", label="Model", kind="text", required=True,
                  help="Claude alias (opus/sonnet) OR a vLLM hf_id, e.g. "
                       "cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4."),
        ParamSpec(name="base_url", label="vLLM base url", kind="text",
                  default="http://localhost:8086",
                  help="Used only for local (non-Claude) models."),
        ParamSpec(name="concurrency", label="Concurrency", kind="number",
                  help="Parallel judge calls (default 16 local / 4 Claude)."),
        ParamSpec(name="max_tokens", label="Max tokens", kind="number", default=220),
        ParamSpec(name="limit", label="Row limit", kind="number"),
        ParamSpec(name="en_col", label="English column", kind="text"),
        ParamSpec(name="ko_col", label="Korean column", kind="text"),
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid"),
        ParamSpec(name="label_col", label="SME-rating column", kind="text",
                  default="sme_rating"),
        ParamSpec(name="system", label="System prompt (rubric)", kind="textarea"),
    ],
    runner="snomed_translation.acceptability:acceptability_judge",
)

acceptability_judge_batched_spec = FunctionSpec(
    name="acceptability_judge_batched", label="Acceptability judge (batched LLM)",
    category="detect",
    description="Judge N EN/KO pairs per call, recording call reduction, parsing "
                "reliability, runtime, and optional reference-label agreement.",
    inputs=[PortSpec(name="translations", label="Translations", kinds=["dataset"],
                     required=True)],
    outputs=[
        PortSpec(name="judgements", label="Per-row judgements", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="model", label="Model", kind="text", required=True),
        ParamSpec(name="base_url", label="vLLM base url", kind="text",
                  default="http://localhost:8086"),
        ParamSpec(name="batch_size", label="Terms per call", kind="number", default=10),
        ParamSpec(name="concurrency", label="Concurrent calls", kind="number"),
        ParamSpec(name="max_attempts", label="Maximum attempts", kind="number", default=2),
        ParamSpec(name="max_tokens_per_item", label="Output tokens per item",
                  kind="number", default=90),
        ParamSpec(name="max_tokens", label="Output token cap", kind="number", default=8192),
        ParamSpec(name="sample_size", label="Fixed random sample size", kind="number"),
        ParamSpec(name="seed", label="Sample seed", kind="number", default=20260714),
        ParamSpec(name="en_col", label="English column", kind="text"),
        ParamSpec(name="ko_col", label="Korean column", kind="text"),
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid"),
        ParamSpec(name="reference_label_col", label="Reference label column",
                  kind="text", default="judge_label"),
        ParamSpec(name="system", label="System prompt (batch rubric)", kind="textarea"),
    ],
    runner="snomed_translation.acceptability_batched:acceptability_judge_batched",
)
correction_round_spec = FunctionSpec(
    name="correction_round", label="Correction round (LLM)", category="translate",
    description="Revise translations flagged by transliteration_detect OR rejected "
                "by acceptability_judge. On SME-labelled input, report exact/chrF "
                "against the corrected SME rendering without exposing it to the LLM.",
    inputs=[
        PortSpec(name="translations", label="Translations", kinds=["dataset"], required=True),
        PortSpec(name="transliteration_flags", label="Transliteration flags",
                 kinds=["dataset"], required=True),
        PortSpec(name="judgements", label="Judge results", kinds=["dataset"], required=True),
    ],
    outputs=[PortSpec(name="translations", label="Corrected translations", kinds=["dataset"])],
    params=[
        ParamSpec(name="model", label="Correction model", kind="text", required=True),
        ParamSpec(name="base_url", label="vLLM base url", kind="text",
                  default="http://localhost:8086"),
        ParamSpec(name="concurrency", label="Concurrency", kind="number"),
        ParamSpec(name="max_tokens", label="Max tokens", kind="number", default=260),
        ParamSpec(name="limit", label="Row limit", kind="number"),
        ParamSpec(name="judge_score_threshold", label="Judge score threshold",
                  kind="number", default=0.85),
        ParamSpec(name="en_col", label="English column", kind="text"),
        ParamSpec(name="ko_col", label="Korean column", kind="text"),
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid"),
        ParamSpec(name="reference_col", label="SME corrected column", kind="text",
                  default="sme_corrected_ko"),
        ParamSpec(name="label_col", label="SME rating column", kind="text",
                  default="sme_rating"),
        ParamSpec(name="system", label="Correction system prompt", kind="textarea"),
    ],
    runner="snomed_translation.correction:correction_round",
)

select_sme_batch_spec = FunctionSpec(
    name="select_sme_batch", label="Select SME review batch", category="evaluate",
    description="Select a reproducible, non-overlapping imaging-procedure batch. "
                "Excludes prior SCTIDs and near-duplicate English terms, learns "
                "error-prone source tokens from prior SME labels, and supports "
                "coverage, active-risk, or balanced selection.",
    inputs=[
        PortSpec(name="candidates", label="Translated frontier", kinds=["dataset"],
                 required=True),
        PortSpec(name="previous_sme", label="Prior SME labels", kinds=["dataset"],
                 required=True),
        PortSpec(name="backtranslations", label="Back-translation signals",
                 kinds=["dataset"], required=False),
    ],
    outputs=[
        PortSpec(name="batch", label="SME review batch", kinds=["dataset"]),
        PortSpec(name="audit", label="Selection audit", kinds=["text"]),
    ],
    params=[
        ParamSpec(name="strategy", label="Strategy", kind="select", default="balanced",
                  options=["balanced", "coverage", "active"]),
        ParamSpec(name="size", label="Batch size", kind="number", default=100),
        ParamSpec(name="seed", label="Seed", kind="number", default=20260712),
        ParamSpec(name="max_prior_similarity", label="Max similarity to batch 1",
                  kind="number", default=0.72),
        ParamSpec(name="max_internal_similarity", label="Max within-batch similarity",
                  kind="number", default=0.50,
                  help="Reject a candidate at or above this token-Jaccard similarity "
                       "to an already selected term."),
        ParamSpec(name="max_topic_repeats", label="Max topic repetitions",
                  kind="number", default=10,
                  help="Cap repeated non-modality content such as an anatomy or "
                       "procedure family."),
    ],
    runner="snomed_translation.batch_selection:select_sme_batch",
)

package_sme_batch_spec = FunctionSpec(
    name="package_sme_batch", label="Package SME review batch", category="evaluate",
    description="Join selection metadata to newly generated translations and emit "
                "one reviewer-ready CSV with blank structured SME feedback fields.",
    inputs=[
        PortSpec(name="selection", label="Selected terms", kinds=["dataset"],
                 required=True),
        PortSpec(name="translations", label="Generated translations", kinds=["dataset"],
                 required=True),
    ],
    outputs=[
        PortSpec(name="packet", label="SME review packet", kinds=["dataset"]),
        PortSpec(name="metrics", label="Packet metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="id_col", label="Id column", kind="text", default="sctid"),
        ParamSpec(name="translation_col", label="Translation column", kind="text",
                  default="translation"),
    ],
    runner="snomed_translation.batch_selection:package_sme_batch",
)

translation_evaluation_summary_spec = FunctionSpec(
    name="translation_evaluation_summary", label="Translation evaluation summary",
    category="evaluate",
    description="Aggregate translation, judge, and transliteration outcomes with "
                "measured stage runtimes into a JSON report and tracked metrics.",
    inputs=[
        PortSpec(name="translation_metrics", label="Translation metrics",
                 kinds=["metrics"], required=True),
        PortSpec(name="judge_metrics", label="Judge metrics",
                 kinds=["metrics"], required=True),
        PortSpec(name="transliteration_metrics", label="Transliteration metrics",
                 kinds=["metrics"], required=True),
    ],
    outputs=[PortSpec(name="report", label="Evaluation report", kinds=["text"])],
    params=[],
    runner="snomed_translation.evaluation_summary:translation_evaluation_summary",
)

semantic_partial_credit_calibration_spec = FunctionSpec(
    name="semantic_partial_credit_calibration",
    label="Semantic partial-credit calibration",
    category="evaluate",
    description="Reproduce the large-set KO↔KO partial-credit estimate and "
                "independently validate its threshold against SME ratings.",
    inputs=[
        PortSpec(name="scores", label="Precomputed large-set scores",
                 kinds=["dataset"], required=True),
        PortSpec(name="sme_labels", label="SME labels",
                 kinds=["dataset"], required=True),
    ],
    outputs=[
        PortSpec(name="audit", label="SME calibration audit", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[ParamSpec(name="threshold", label="KO↔KO threshold",
                      kind="number", default=0.784)],
    runner="snomed_translation.evidence_analysis:semantic_partial_credit_calibration",
)

curate_exemplar_pool_spec = FunctionSpec(
    name="curate_exemplar_pool", label="Curate exemplar pool",
    category="data",
    description="Apply declarative, versioned curation rules to the raw "
                "bilingual pool and emit a NEW csv (the raw pool is never "
                "mutated). Each rule carries a rationale + evidence links; "
                "per-rule match counts and the rules-file content hash are "
                "reported as run metrics, so what changed and why is visible "
                "in the ledger. Register the output as its own source to A/B "
                "raw vs curated by editing a flow instead of a file.",
    inputs=[
        PortSpec(name="pool", label="Raw bilingual pool", kinds=["dataset"],
                 required=True),
    ],
    outputs=[
        PortSpec(name="pool", label="Curated pool", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="rules_file", label="Curation rules YAML", kind="text",
                  required=True),
        ParamSpec(name="output_csv", label="Curated output CSV", kind="text",
                  required=True),
    ],
    runner="snomed_translation.pool_curation:curate_exemplar_pool",
)

self_review_spec = FunctionSpec(
    name="self_review", label="Self review (model checks translations)",
    category="evaluate",
    description="Ask a model to review translations (typically its own) with a "
                "deliberately neutral prompt that names no error class, then "
                "measure it against gold: detection rate on wrong rows, "
                "false-alarm rate on correct rows, repair and damage rates.",
    inputs=[
        PortSpec(name="translations", label="Translations", kinds=["dataset"],
                 required=True),
        PortSpec(name="gold", label="Gold references", kinds=["dataset"]),
        PortSpec(name="style_guide", label="Style guide (optional)",
                 kinds=["style_guide", "text"]),
    ],
    outputs=[
        PortSpec(name="reviews", label="Per-row reviews", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="model", label="Review model", kind="text", required=True),
        ParamSpec(name="base_url", label="Base URL", kind="text",
                  default="http://localhost:8086"),
        ParamSpec(name="concurrency", label="Concurrency", kind="number"),
        ParamSpec(name="max_tokens", label="Max tokens", kind="number", default=220),
        ParamSpec(name="en_col", label="English column", kind="text"),
        ParamSpec(name="ko_col", label="Korean column", kind="text"),
        ParamSpec(name="system", label="Review system prompt", kind="textarea"),
    ],
    runner="snomed_translation.sme_feedback:self_review",
)

contrast_fidelity_detect_spec = FunctionSpec(
    name="contrast_fidelity_detect", label="Contrast fidelity detect",
    category="detect",
    description="Deterministic source-conditional detector for contrast-phrase "
                "mismatches: 조영제 사용/미사용 hallucinated when the source has "
                "no contrast mention, wrong polarity, or a source contrast "
                "modifier dropped. Top SME batch-2 'Wrong' class. Ambiguous "
                "constructions ('contrast procedure') are skipped for precision.",
    inputs=[
        PortSpec(name="translations", label="Translations", kinds=["dataset"],
                 required=True),
    ],
    outputs=[
        PortSpec(name="flags", label="Contrast fidelity flags", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="en_col", label="English column", kind="text", default=""),
        ParamSpec(name="ko_col", label="Korean column", kind="text", default=""),
        ParamSpec(name="label_col", label="SME label column (optional)",
                  kind="text", default="sme_rating"),
    ],
    runner="snomed_translation.sme_feedback:contrast_fidelity_detect",
)

sme_metric_separation_spec = FunctionSpec(
    name="sme_metric_separation", label="SME metric separation",
    category="evaluate",
    description="Score SME-reviewed translations against the multi-reference "
                "SME gold with candidate metrics (spacing-normalised exact, "
                "chrF, BGE-M3 cosine) and measure how well each separates "
                "Correct/Acceptable from Partial/Wrong (AUC, class means, best "
                "cosine threshold). Picks the metric GEPA should optimise.",
    inputs=[
        PortSpec(name="labels", label="SME gold labels", kinds=["dataset"],
                 required=True),
    ],
    outputs=[
        PortSpec(name="audit", label="Per-row metric audit", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[
        ParamSpec(name="candidate_col", label="Candidate column", kind="text",
                  default="reviewed_ko"),
        ParamSpec(name="reference_col", label="Canonical reference column",
                  kind="text", default="ko_reference"),
        ParamSpec(name="allrefs_col", label="All-references column",
                  kind="text", default="ko_all"),
        ParamSpec(name="label_col", label="Rating column", kind="text",
                  default="sme_rating"),
    ],
    runner="snomed_translation.sme_feedback:sme_metric_separation",
)

register_feedback_analysis_spec = FunctionSpec(
    name="register_feedback_analysis",
    label="SME register feedback analysis",
    category="evaluate",
    description="Audit category-specific Sino↔native SME edits and measure "
                "Sonnet over-acceptance on those rows.",
    inputs=[PortSpec(name="sme_labels", label="SME labels",
                     kinds=["dataset"], required=True)],
    outputs=[
        PortSpec(name="audit", label="Register-shift audit", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[],
    runner="snomed_translation.evidence_analysis:register_feedback_analysis",
)

transliteration_recall_calibration_spec = FunctionSpec(
    name="transliteration_recall_calibration",
    label="Transliteration recall calibration",
    category="evaluate",
    description="Evaluate the phonetic-echo rule on an explicitly labelled "
                "audit set and report frontier flag burden at calibrated thresholds.",
    inputs=[
        PortSpec(name="audit", label="Labelled transliteration audit",
                 kinds=["dataset"], required=True),
        PortSpec(name="frontier", label="Full translated frontier",
                 kinds=["dataset"], required=False),
    ],
    outputs=[
        PortSpec(name="audit", label="Scored audit", kinds=["dataset"]),
        PortSpec(name="metrics", label="Metrics", kinds=["metrics"]),
    ],
    params=[ParamSpec(name="current_threshold", label="Current threshold",
                      kind="number", default=0.70)],
    runner="snomed_translation.evidence_analysis:transliteration_recall_calibration",
)


def specs() -> list[FunctionSpec]:
    return [
        translate_spec, translate_consistency_spec, evaluate_spec,
        evaluate_consistency_spec, optimize_spec, evaluate_formula_spec,
        score_workflow_llm_spec, generate_text_spec, style_guide_spec,
        text_source_spec, prompt_source_spec, promote_prompt_spec,
        build_snomed_index_spec,
        snomed_retrieve_spec, back_translate_spec, rerank_spec,
        transliteration_detect_spec, acceptability_judge_spec,
        acceptability_judge_batched_spec, correction_round_spec,
        select_sme_batch_spec, package_sme_batch_spec,
        translation_evaluation_summary_spec,
        semantic_partial_credit_calibration_spec,
        curate_exemplar_pool_spec,
        self_review_spec,
        contrast_fidelity_detect_spec,
        sme_metric_separation_spec,
        register_feedback_analysis_spec,
        transliteration_recall_calibration_spec,
    ]


def install() -> None:
    """Register all functions + the source resolver in-process (tests)."""
    from pipelines import registry
    for s in specs():
        registry.register(s)
    registry.register_source("snomed_translation", resolve_source)
