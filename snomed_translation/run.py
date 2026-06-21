"""CLI entry point: `python -m snomed_translation.run --config X --stage Y`.

This is the unified launcher used by both the wizard's subprocess runner and
manual command-line invocations.

Per-run overrides (eval set, output tag, concurrency) are applied in-memory
to the loaded ``PipelineConfig`` before the stage runs. The pipeline file
keeps its inline defaults; flags only override for this invocation.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from snomed_translation.config import EvalSetSpec, PipelineConfig
from pipelines.context import RunContext
from snomed_translation.stages import get_stage, list_stages


def _apply_run_overrides(
    cfg: PipelineConfig,
    *,
    eval_set_path: Path | None,
    output_tag: str | None,
    concurrency: int | None,
    model_key: str | None,
    log: logging.Logger,
) -> None:
    """Mutate ``cfg`` in-place with run-specific overrides.

    Stages read from ``cfg`` as usual; they don't need to know an override
    happened. Logs each override so reproducibility is auditable from a job
    transcript.
    """
    if eval_set_path is not None:
        override = EvalSetSpec.from_file(eval_set_path)
        log.info("Override eval_set from %s (csv=%s)", eval_set_path, override.csv)
        cfg.eval_set = override
    if output_tag is not None:
        log.info("Override translation.output_tag: %s -> %s",
                 cfg.translation.output_tag, output_tag)
        cfg.translation.output_tag = output_tag
    if model_key is not None:
        # Validate against the whitelist before swapping. resolve_candidate
        # raises clearly if the key isn't a candidate.
        cfg.translation.resolve_candidate(model_key)
        log.info("Override translation.default_model_key: %s -> %s",
                 cfg.translation.default_model_key, model_key)
        cfg.translation.default_model_key = model_key
    if concurrency is not None:
        # Concurrency override applies to the resolved candidate — that's
        # the actual run-time setting the translate stage will read.
        target = cfg.translation.resolve_candidate()
        log.info("Override candidate(%s).concurrency: %s -> %s",
                 target.model_key, target.concurrency, concurrency)
        target.concurrency = concurrency


def main() -> int:
    p = argparse.ArgumentParser(description="Run a single pipeline stage from a config file.")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--stage", required=True, choices=list_stages())
    p.add_argument("--log-dir", type=Path, default=None)
    p.add_argument("--run-id", type=str, default=None)
    p.add_argument("--limit", type=int, default=None,
                   help="Stage-specific row limit (translate/evaluate use it).")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--eval-set", type=Path, default=None,
                   help="Standalone eval-set JSON/YAML to use for this run. "
                        "Overrides the pipeline's inline eval_set block.")
    p.add_argument("--output-tag", type=str, default=None,
                   help="Override translation.output_tag for this run "
                        "(controls the output CSV filename).")
    p.add_argument("--concurrency", type=int, default=None,
                   help="Override translation.concurrency for this run.")
    p.add_argument("--model-key", type=str, default=None,
                   help="Pick a model from translation.candidate_model_keys "
                        "for this run. Must match one of the pipeline's "
                        "whitelisted candidates.")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("snomed_translation.run")

    cfg = PipelineConfig.from_file(args.config)
    _apply_run_overrides(
        cfg,
        eval_set_path=args.eval_set,
        output_tag=args.output_tag,
        concurrency=args.concurrency,
        model_key=args.model_key,
        log=log,
    )

    ctx_kwargs = {"log_dir": args.log_dir}
    if args.run_id:
        ctx_kwargs["run_id"] = args.run_id
    ctx = RunContext(**ctx_kwargs)

    log.info("Running stage=%s for language=%s (run_id=%s)",
             args.stage, cfg.language.code, ctx.run_id)

    stage_runner = get_stage(args.stage)
    t0 = time.monotonic()
    result = stage_runner(cfg, ctx, limit=args.limit, resume=args.resume)
    elapsed = time.monotonic() - t0

    log.info("Stage %s %s in %.1fs: %s",
             result.stage, "OK" if result.ok else "FAILED", elapsed, result.message)
    for path in result.output_paths:
        log.info("  output: %s", path)
    for metric, value in result.metrics.items():
        log.info("  metric: %s = %s", metric, value)

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
