"""Registry mapping stage name → runner callable.

Stage runners have a uniform signature:
    run(cfg: PipelineConfig, ctx: RunContext, **kwargs) -> StageResult

Stages are registered lazily (imported on first lookup) so that an unused
stage's heavy deps (e.g. dspy, BGE-M3) don't load when running a different
stage.
"""
from __future__ import annotations

from typing import Callable

from pipelines.config import PipelineConfig
from pipelines.context import RunContext, StageResult


StageRunner = Callable[..., StageResult]


_LAZY_IMPORTS: dict[str, str] = {
    "translate": "pipelines.stages.translate",
    "evaluate": "pipelines.stages.evaluate",
    "optimize": "pipelines.stages.optimize",
    "translate_consistency": "pipelines.stages.translate_consistency",
    "evaluate_consistency": "pipelines.stages.evaluate_consistency",
    "evaluate_formula": "pipelines.stages.evaluate_formula",
    "score_workflow_llm": "pipelines.stages.score_workflow_llm",
}


def get_stage(name: str) -> StageRunner:
    if name not in _LAZY_IMPORTS:
        raise KeyError(
            f"Unknown stage {name!r}. Known: {sorted(_LAZY_IMPORTS)}"
        )
    import importlib
    module = importlib.import_module(_LAZY_IMPORTS[name])
    return module.run


def list_stages() -> list[str]:
    return sorted(_LAZY_IMPORTS)
