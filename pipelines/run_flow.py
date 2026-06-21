"""CLI entry point: ``python -m pipelines.run_flow --flow F``.

Executes a saved FlowSpec end-to-end. Each step:
  1. starts from a deep copy of the pipeline's base config (so step-N's
     overrides don't bleed into step-N+1);
  2. has its ``params`` resolved against prior steps' outputs
     (``$step_id.output_csv`` etc.);
  3. has its overrides applied to the (copied) config;
  4. runs through the registered stage runner;
  5. contributes its ``StageResult.outputs`` to the ``completed`` dict for
     downstream steps to reference.

A run journal is written alongside the run log so the entire execution is
auditable post-hoc.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from pipelines.assemble import (
    AssemblyError,
    Registries,
    assemble_pipeline_config,
    load_project,
)
from pipelines.config import PipelineConfig
from pipelines.context import RunContext, StageResult
from pipelines.flow import NODE_OUTPUT, FlowNode, FlowSpec
from pipelines.graph import (
    GraphError,
    build_evaluate,
    build_evaluate_consistency,
    build_evaluate_formula,
    build_optimize,
    build_score_workflow_llm,
    build_translate,
    build_translate_consistency,
    resolve_datasource,
    resolve_style_guide,
    topo_order,
    translate_consistency_output_schema,
    translate_output_schema,
)
from pipelines.publish import (
    PublishError,
    publish_dataset,
    publish_style_guide,
)
from pipelines.registry import get_stage


def _journal_entry(step_id: str, stage: str, result: StageResult,
                   elapsed: float) -> dict[str, Any]:
    """Render a single step's outcome into a JSON-safe dict for the journal."""
    return {
        "step_id": step_id,
        "stage": stage,
        "ok": result.ok,
        "message": result.message,
        "outputs": {k: str(v) for k, v in result.outputs.items()},
        "metrics": dict(result.metrics),
        "elapsed_seconds": round(elapsed, 2),
    }


def run_flow(flow: FlowSpec, ctx: RunContext, *,
             stop_on_error: bool = True,
             configs_dir: str | Path = "configs",
             registries: Registries | None = None,
             log: logging.Logger | None = None) -> tuple[bool, list[dict]]:
    """Execute the flow start-to-finish. Returns (overall_ok, journal).

    The base config is *assembled* from the flow's referenced blocks — the
    project named by ``flow.project`` (configs/<name>.json), the source/model/
    resource registries — rather than loaded from a monolithic file. The
    assembled config is written to ``ctx.log_dir/assembled_config.json`` for
    post-hoc auditability.
    """
    log = log or logging.getLogger("pipelines.run_flow")
    try:
        project = load_project(flow.project, configs_dir)
        registries = registries or Registries.load()
        base_cfg = assemble_pipeline_config(flow, project, registries)
    except AssemblyError as exc:
        log.error("Flow %r could not be assembled: %s", flow.name, exc)
        return False, [{
            "step_id": "<assemble>", "stage": "assemble", "ok": False,
            "message": str(exc), "outputs": {}, "metrics": {},
            "elapsed_seconds": 0.0,
        }]
    if ctx.log_dir is not None:
        ctx.log_dir.mkdir(parents=True, exist_ok=True)
        (ctx.log_dir / "assembled_config.json").write_text(
            base_cfg.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8")
        # Snapshot the flow as it was for this run — flow files keep evolving,
        # so this is the authoritative record (used by retroactive publishing
        # and reproduction).
        (ctx.log_dir / "flow.json").write_text(
            json.dumps(flow.model_dump(mode="json", exclude_none=True),
                       indent=2, ensure_ascii=False),
            encoding="utf-8")
        (ctx.log_dir / "run_meta.json").write_text(
            json.dumps(_config_fingerprint(flow, base_cfg), indent=2),
            encoding="utf-8")

    log.info("Flow %r over project %r (%d nodes)",
             flow.name, flow.project, len(flow.nodes))
    overall_ok, journal = _run_graph(
        flow, base_cfg, registries, ctx, stop_on_error, log)
    _write_journal(ctx, journal, log)
    return overall_ok, journal


def _config_fingerprint(flow: FlowSpec, base_cfg: PipelineConfig) -> dict:
    """Identity of everything the flow's version hash does NOT cover.

    The flow hash pins the *graph*; this pins the *conditions* it ran under:
    the assembled block environment (model llm_params, sources, scorer
    weights, recipes) plus the **content** of every style guide the flow
    references. Two runs with equal flow_version but different config_version
    ran the same graph under different conditions — e.g. a model-temperature
    edit in the models catalog, or an edited guide file.
    """
    import hashlib

    def _digest(b: bytes) -> str:
        return hashlib.blake2b(b, digest_size=4).hexdigest()

    guides: dict[str, str] = {}
    for n in flow.nodes:
        for key in ("path", "style_guide_path"):
            p = n.params.get(key)
            if p and Path(p).exists():
                guides[str(p)] = _digest(Path(p).read_bytes())

    h = hashlib.blake2b(digest_size=4)
    h.update(base_cfg.model_dump_json(exclude_none=True).encode("utf-8"))
    for path in sorted(guides):
        h.update(f"|{path}={guides[path]}".encode("utf-8"))
    return {"config_version": h.hexdigest(), "style_guide_digests": guides}


def _write_journal(ctx: RunContext, journal: list[dict],
                   log: logging.Logger) -> None:
    if ctx.log_dir is not None:
        jpath = ctx.log_dir / "journal.json"
        jpath.write_text(json.dumps(journal, indent=2, ensure_ascii=False,
                                     default=str), encoding="utf-8")
        log.info("Wrote journal to %s", jpath)


def _node_journal(node: FlowNode, *, ok: bool, message: str,
                  outputs: dict | None = None,
                  elapsed: float = 0.0) -> dict:
    return {
        "step_id": node.id, "stage": node.type, "ok": ok, "message": message,
        "outputs": {k: str(v) for k, v in (outputs or {}).items()},
        "metrics": {}, "elapsed_seconds": round(elapsed, 2),
    }


def _node_outputs(node: FlowNode, result: StageResult) -> dict[str, Any]:
    """Expose a stage's outputs under the node's logical output-port name so
    downstream nodes can wire to it (translate->`translations`, etc.)."""
    out = dict(result.outputs)
    port = NODE_OUTPUT.get(node.type)
    if node.type == "translate" and "output_csv" in out:
        out[port] = out["output_csv"]
        # A translate output is itself a dataset (sctid + en + translation):
        # expose it with the same shape resolve_datasource produces so
        # downstream column checks treat it uniformly.
        out["dataset"] = str(out["output_csv"])
        out["source_id"] = node.id
        out.update(translate_output_schema())
    elif node.type == "translate_consistency" and "candidates_csv" in out:
        # A candidates dataset (sctid + en + multiple candidates). Same uniform
        # shape as a datasource so evaluate_consistency's column checks work.
        out[port] = out["candidates_csv"]
        out["dataset"] = str(out["candidates_csv"])
        out["source_id"] = node.id
        out.update(translate_consistency_output_schema())
    elif node.type in ("evaluate", "evaluate_consistency") and "scored_csv" in out:
        out[port] = out["scored_csv"]
    # Expose the stage's aggregate metrics on the wire too, so a downstream
    # score node can reference an upstream evaluate node's vector
    # (e.g. composite_score, mean_chrf) by name.
    out["metrics"] = {k: float(v) for k, v in result.metrics.items()}
    return out


def _run_graph(flow: FlowSpec, base_cfg: PipelineConfig, registries,
               ctx: RunContext, stop_on_error: bool,
               log: logging.Logger) -> tuple[bool, list[dict]]:
    """Topologically execute a flow's node graph."""
    resolved: dict[str, dict] = {}
    journal: list[dict] = []
    overall_ok = True

    try:
        order = topo_order(flow.nodes)
    except GraphError as exc:
        log.error("graph error: %s", exc)
        return False, [{
            "step_id": "<graph>", "stage": "graph", "ok": False,
            "message": str(exc), "outputs": {}, "metrics": {},
            "elapsed_seconds": 0.0,
        }]

    n_total = len(order)
    for i, node in enumerate(order, start=1):
        log.info("== Node %d/%d: %s (%s) ==", i, n_total, node.id, node.type)
        if ctx.is_cancelled():
            log.warning("Cancelled before node %s", node.id)
            overall_ok = False
            break

        if node.type in ("datasource", "style_guide"):
            try:
                if node.type == "datasource":
                    resolved[node.id] = resolve_datasource(node, registries)
                    outputs = {"dataset": resolved[node.id]["dataset"]}
                else:
                    resolved[node.id] = resolve_style_guide(node)
                    outputs = dict(resolved[node.id])
                log.info("[%s] %s -> %s", node.id, node.type,
                         next(iter(outputs.values())))
                journal.append(_node_journal(
                    node, ok=True, message="resolved", outputs=outputs))
            except GraphError as exc:
                log.error("[%s] %s", node.id, exc)
                journal.append(_node_journal(node, ok=False, message=str(exc)))
                overall_ok = False
                if stop_on_error:
                    break
            continue

        # Executable node: compile its cfg + kwargs, then run the stage.
        try:
            if node.type == "translate":
                cfg, kwargs = build_translate(node, base_cfg, resolved)
                stage = "translate"
            elif node.type == "translate_consistency":
                cfg, kwargs = build_translate_consistency(node, base_cfg, resolved)
                stage = "translate_consistency"
            elif node.type == "evaluate":
                cfg, kwargs = build_evaluate(node, base_cfg, resolved)
                stage = "evaluate"
            elif node.type == "evaluate_consistency":
                cfg, kwargs = build_evaluate_consistency(node, base_cfg, resolved)
                stage = "evaluate_consistency"
            elif node.type == "optimize":
                cfg, kwargs = build_optimize(node, base_cfg, resolved)
                stage = "optimize"
            elif node.type == "evaluate_formula":
                cfg, kwargs = build_evaluate_formula(node, base_cfg, resolved)
                stage = "evaluate_formula"
            elif node.type == "score_workflow_llm":
                cfg, kwargs = build_score_workflow_llm(node, base_cfg, resolved)
                stage = "score_workflow_llm"
            else:
                log.warning("[%s] node type %r not wired yet — skipping",
                            node.id, node.type)
                journal.append(_node_journal(
                    node, ok=False, message=f"{node.type} runner not wired"))
                overall_ok = False
                if stop_on_error:
                    break
                continue
        except GraphError as exc:
            log.error("[%s] compile failed: %s", node.id, exc)
            journal.append(_node_journal(
                node, ok=False, message=f"compile-failed: {exc}"))
            overall_ok = False
            if stop_on_error:
                break
            continue

        runner = get_stage(stage)
        t0 = time.monotonic()
        try:
            result: StageResult = runner(cfg, ctx, **kwargs)
        except Exception as exc:  # a crashed stage must still leave a journal
            elapsed = time.monotonic() - t0
            log.exception("[%s] stage crashed", node.id)
            journal.append(_node_journal(
                node, ok=False, elapsed=elapsed,
                message=f"crashed: {type(exc).__name__}: {exc}"))
            overall_ok = False
            if stop_on_error:
                break
            continue
        elapsed = time.monotonic() - t0
        journal.append(_journal_entry(node.id, stage, result, elapsed))
        log.info("[%s] %s in %.1fs: %s", node.id,
                 "OK" if result.ok else "FAILED", elapsed, result.message)
        if not result.ok:
            overall_ok = False
            if stop_on_error:
                break
        resolved[node.id] = _node_outputs(node, result)

        # Promotion: a node with `publish_as` registers its artifact under a
        # stable name once it succeeds. Failure to publish doesn't stop the
        # flow (the run store keeps the artifact) but is journaled as a
        # failure so it can't pass silently.
        publish_as = node.params.get("publish_as")
        if publish_as and result.ok:
            try:
                if node.type == "translate":
                    info = publish_dataset(
                        publish_as, Path(result.outputs["output_csv"]),
                        flow.name, node, ctx, cfg)
                elif node.type == "evaluate_consistency":
                    # The judge's chosen "best candidate" translations — a
                    # standard translate-shaped CSV, published as a data source.
                    info = publish_dataset(
                        publish_as, Path(result.outputs["chosen_csv"]),
                        flow.name, node, ctx, cfg)
                elif node.type == "optimize":
                    seed = (cfg.optimization.seed_style_guide
                            if cfg.optimization else None)
                    info = publish_style_guide(
                        publish_as,
                        Path(result.outputs["optimized_style_guide"]),
                        flow.name, node, ctx, seed_style_guide=seed)
                else:
                    info = None
                if info is not None:
                    log.info("[%s] published as %r: %s",
                             node.id, publish_as, info)
                    journal.append(_node_journal(
                        node, ok=True,
                        message=f"published as {publish_as!r}",
                        outputs=info))
            except (PublishError, KeyError) as exc:
                log.error("[%s] publish failed: %s", node.id, exc)
                journal.append(_node_journal(
                    node, ok=False, message=f"publish-failed: {exc}"))
                overall_ok = False

    return overall_ok, journal


def main() -> int:
    p = argparse.ArgumentParser(description="Execute a saved flow end-to-end.")
    p.add_argument("--flow", required=True, type=Path,
                   help="Path to a FlowSpec JSON/YAML file.")
    p.add_argument("--log-dir", type=Path, default=None)
    p.add_argument("--run-id", type=str, default=None)
    p.add_argument("--continue-on-error", action="store_true",
                   help="Keep going if a step fails. By default the flow "
                        "halts on the first failure.")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("pipelines.run_flow")

    flow = FlowSpec.from_file(args.flow)
    ctx_kwargs = {"log_dir": args.log_dir}
    if args.run_id:
        ctx_kwargs["run_id"] = args.run_id
    ctx = RunContext(**ctx_kwargs)

    ok, _ = run_flow(flow, ctx,
                     stop_on_error=not args.continue_on_error, log=log)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
