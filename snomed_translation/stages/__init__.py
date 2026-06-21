"""Translation stage runners + a local name → runner lookup.

The app's generic engine no longer knows the translation stages (it dispatches
to registered :class:`~pipelines.functions.FunctionSpec` runners instead). This
lookup is the plugin's own, used by the legacy single-stage CLI
(:mod:`snomed_translation.run`) and the function adapters in
:mod:`snomed_translation.functions`. Imports are lazy so a bare ``--help`` does
not drag in the heavy translate/evaluate dependencies.
"""
from __future__ import annotations

import importlib
from typing import Callable

from pipelines.context import StageResult

StageRunner = Callable[..., StageResult]

_LAZY_IMPORTS: dict[str, str] = {
    "translate": "snomed_translation.stages.translate",
    "evaluate": "snomed_translation.stages.evaluate",
    "optimize": "snomed_translation.stages.optimize",
    "translate_consistency": "snomed_translation.stages.translate_consistency",
    "evaluate_consistency": "snomed_translation.stages.evaluate_consistency",
    "evaluate_formula": "snomed_translation.stages.evaluate_formula",
    "score_workflow_llm": "snomed_translation.stages.score_workflow_llm",
}


def get_stage(name: str) -> StageRunner:
    if name not in _LAZY_IMPORTS:
        raise KeyError(f"Unknown stage {name!r}. Known: {sorted(_LAZY_IMPORTS)}")
    module = importlib.import_module(_LAZY_IMPORTS[name])
    return module.run


def list_stages() -> list[str]:
    return sorted(_LAZY_IMPORTS)
