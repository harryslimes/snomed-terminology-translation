"""LLM score stage (a flow-level evaluate sub-type).

The non-deterministic counterpart of the formula score node: the user writes a
prompt, the upstream metric vector is templated into it, and a model returns a
single scalar. Useful when "which run is better" is a judgement that doesn't
reduce to a fixed weighting (the model can reason before answering — only the
final SCORE line is consumed).

Templating: ``{{name}}`` inserts a variable's value (``{{composite_score}}`` or
``{{eval_think.composite_score}}``); ``{{metrics}}`` inserts the full namespaced
metric list as ``name = value`` lines.

Determinism caveat: the call is pinned to temperature 0, but model output can
still drift across versions — keep the deterministic formula node as the spine
for anything that must be reproducibly rank-ordered.
"""
from __future__ import annotations

import logging
import os
import re

from snomed_translation.config import PipelineConfig
from pipelines.context import RunContext, StageResult

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"{{\s*([\w.]+)\s*}}")
_SCORE_RE = re.compile(r"SCORE\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

_SYSTEM = (
    "You are a scoring function for a translation experiment. You are given "
    "evaluation metrics for one run and must return a single numeric score "
    "reflecting how good the run is. You may reason briefly first, but your "
    "final line MUST be exactly 'SCORE: <number>'."
)


def render_prompt(template: str, variables: dict[str, float]) -> str:
    """Substitute ``{{name}}`` / ``{{metrics}}`` tokens. Raises KeyError naming
    the first unknown token so typos surface instead of silently passing."""
    table = "\n".join(f"{k} = {v:g}" for k, v in sorted(variables.items())
                      if "." in k)
    repl: dict[str, object] = dict(variables)
    repl["metrics"] = table

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key not in repl:
            raise KeyError(key)
        val = repl[key]
        return val if isinstance(val, str) else f"{val:g}"

    return _TOKEN_RE.sub(_sub, template)


def extract_score(text: str) -> float | None:
    """Pull the scalar from a model reply: prefer an explicit ``SCORE: x``,
    else fall back to the last number (after stripping any <think> block)."""
    cleaned = _THINK_RE.sub("", text or "")
    m = _SCORE_RE.search(cleaned)
    if m:
        return float(m.group(1))
    nums = _NUM_RE.findall(cleaned)
    return float(nums[-1]) if nums else None


def run(cfg: PipelineConfig, ctx: RunContext, *,
        prompt: str, variables: dict[str, float], model_key: str,
        output_name: str = "score", thinking: bool = False, **_) -> StageResult:
    if not variables:
        return StageResult(
            stage="score_workflow_llm", ok=False,
            message="no upstream metrics to score over")
    # Imported lazily: pulls in the vLLM HTTP client only when this stage runs.
    from scripts.translation.translate_korean_with_lookup import (
        translate_one,
        wait_for_server,
    )
    try:
        user = render_prompt(prompt, variables)
    except KeyError as exc:
        avail = ", ".join(sorted(variables)) or "(none)"
        return StageResult(
            stage="score_workflow_llm", ok=False,
            message=f"prompt references unknown variable {exc}. "
                    f"Available: {avail}, plus {{metrics}}")

    base_url = os.getenv("VLLM_BASE_URL",
                         cfg.model_base_url(model_key).rsplit("/v1", 1)[0])
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    model_id = cfg.models[model_key].hf_id
    params = {
        "temperature": 0.0,
        "max_tokens": 2048 if thinking else 512,
        "chat_template_kwargs": {"enable_thinking": bool(thinking)},
        "enable_thinking": bool(thinking),
    }
    wait_for_server(base_url)
    try:
        resp = translate_one(base_url, model_id, _SYSTEM, user, params)
    except Exception as exc:  # noqa: BLE001 — surface as a stage failure
        return StageResult(stage="score_workflow_llm", ok=False,
                           message=f"LLM call failed: {exc}")
    value = extract_score(resp)
    if value is None:
        return StageResult(
            stage="score_workflow_llm", ok=False,
            message=f"could not parse a numeric score from model output: "
                    f"{resp[:200]!r}")
    log.info("LLM score %s = %.4f", output_name, value)
    return StageResult(
        stage="score_workflow_llm", ok=True,
        metrics={output_name: value},
        message=f"{output_name}={value:.4f} (LLM {model_key})")
