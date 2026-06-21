"""Formula score stage (a flow-level evaluate sub-type).

Collapses the metric vectors of one or more upstream evaluate nodes into a
single comparable scalar via a safe arithmetic expression — e.g.
``0.7*eval_think.composite_score + 0.3*(eval_nothink.mean_chrf/100)``. No row
data is touched; the aggregation is across *nodes*, on the metrics they already
emitted. The scalar is reported as a metric so the run ledger can rank flow
revisions by it.
"""
from __future__ import annotations

import logging

from snomed_translation.config import PipelineConfig
from pipelines.context import RunContext, StageResult
from snomed_translation.formula import FormulaError, eval_formula

log = logging.getLogger(__name__)


def run(cfg: PipelineConfig, ctx: RunContext, *,
        expression: str, variables: dict[str, float],
        output_name: str = "score", **_) -> StageResult:
    if not variables:
        return StageResult(
            stage="evaluate_formula", ok=False,
            message="no upstream metrics to score over — is an evaluate node "
                    "wired into this score node, and did it produce metrics?")
    try:
        value = eval_formula(expression, variables)
    except FormulaError as exc:
        avail = ", ".join(sorted(variables)) or "(none)"
        return StageResult(
            stage="evaluate_formula", ok=False,
            message=f"formula error: {exc}. Available variables: {avail}")
    log.info("formula %s = %.4f  [vars: %s]", expression, value,
             ", ".join(f"{k}={v:g}" for k, v in sorted(variables.items())
                       if "." in k))
    return StageResult(
        stage="evaluate_formula", ok=True,
        metrics={output_name: value},
        message=f"{output_name}={value:.4f}  ({expression})")
