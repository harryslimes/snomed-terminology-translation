"""Unified LLM provider layer: one ``complete()`` for every backend.

A model in ``models.json`` is either an OpenAI-compatible HTTP endpoint (vLLM /
llama.cpp / Dashscope — reached via ``base_url``) or the endpoint-less
``claude_agent_sdk`` backend (Claude Opus/Sonnet via the Claude Code Agent SDK on
the host subscription, no host/port/key). Every node that needs an LLM —
translate, judge, back-translate, generate_text — calls :func:`complete` with a
``(system, user)`` pair and the model's ``ModelSpec``; this module dispatches on
``ModelSpec.backend`` so the call sites stay backend-agnostic.

Backend capability gaps are handled here, not at the call sites:
  * The Agent SDK has no ``stop`` sequences, ``temperature`` or ``max_tokens`` —
    those HTTP ``llm_params`` are dropped (with a one-time debug log) rather than
    erroring; Claude + ``max_turns=1`` does not over-generate the way a base
    model does, so stop tokens are not load-bearing for it.
  * The SDK spawns a subprocess per call and is subscription-rate-limited, so it
    must NOT be driven at HTTP-style 16-way concurrency; callers read
    :func:`is_agent_sdk` / :func:`recommended_concurrency` to cap it.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from snomed_translation.config import ModelSpec

log = logging.getLogger(__name__)

AGENT_SDK_BACKENDS = {"claude_agent_sdk", "claude_code", "agent_sdk"}


def is_agent_sdk(spec: ModelSpec) -> bool:
    return (spec.backend or "").lower() in AGENT_SDK_BACKENDS


def recommended_concurrency(spec: ModelSpec, requested: int) -> int:
    """Cap concurrency for endpoint-less SDK models (subprocess-per-call +
    subscription rate limits); HTTP endpoints keep the caller's value."""
    if is_agent_sdk(spec):
        return max(1, min(requested, int(os.getenv("AGENT_SDK_CONCURRENCY", "2"))))
    return requested


def http_base_url(spec: ModelSpec) -> str:
    """Root URL (no ``/v1``) for an HTTP backend — ``translate_one`` appends
    ``/v1/chat/completions``. Honours the ``VLLM_BASE_URL`` global override, the
    same knob the translate stage uses to retarget a remote endpoint."""
    override = os.getenv("VLLM_BASE_URL")
    if override:
        return override[:-3] if override.endswith("/v1") else override
    host = spec.host or "localhost"
    if spec.port == 443:
        return f"https://{host}"
    return f"http://{host}:{spec.port}"


def _model_id(spec: ModelSpec, model_key: str) -> str:
    return spec.hf_id or spec.model_path or model_key


# Which HTTP llm_params the Agent SDK cannot honour (dropped, not passed on).
_SDK_UNSUPPORTED = ("stop", "temperature", "max_tokens", "top_p",
                    "chat_template_kwargs", "enable_thinking", "frequency_penalty",
                    "presence_penalty")


def _complete_agent_sdk(spec: ModelSpec, model_key: str, system: str | None,
                        user: str, params: dict[str, Any],
                        ctx: Any = None, node: str | None = None) -> str:
    from snomed_translation.generate import run_query
    p = {**(spec.llm_params or {}), **(params or {})}   # per-call params win
    dropped = [k for k in _SDK_UNSUPPORTED if k in p]
    if dropped:
        log.debug("agent_sdk model %s: dropping unsupported params %s",
                  model_key, dropped)
    # `thinking` is opt-in for Claude; accept either an explicit `thinking` flag
    # or the served-model `enable_thinking` convention.
    thinking = bool(p.get("thinking", p.get("enable_thinking", False)))
    return run_query(
        user,
        model=spec.model or model_key,
        system=system,
        thinking=thinking,
        max_thinking_tokens=int(p.get("max_thinking_tokens") or 0),
        effort=p.get("effort") if thinking else None,
        ctx=ctx, node=node,   # token accounting (run_query records SDK usage)
    )


def _complete_http(spec: ModelSpec, model_key: str, system: str | None,
                   user: str, params: dict[str, Any],
                   timeout: Any, ctx: Any = None, node: str | None = None) -> str:
    from scripts.translation.translate_korean_with_lookup import translate_one
    text, usage = translate_one(
        http_base_url(spec), _model_id(spec, model_key),
        system or "", user, dict(params or {}), timeout=timeout, return_usage=True)
    if ctx is not None:
        from pipelines.llm_accounting import record_completion
        record_completion(ctx, model=model_key, usage=usage, node=node)
    return text


def complete(spec: ModelSpec, model_key: str, system: str | None, user: str,
             params: dict[str, Any] | None = None, *,
             timeout: Any = (10, None), ctx: Any = None,
             node: str | None = None) -> str:
    """Run one chat completion against ``spec``'s backend and return the text.

    ``params`` are the per-call ``llm_params`` (temperature/max_tokens/stop for
    HTTP; thinking/effort/max_thinking_tokens for the SDK). Unsupported keys for a
    given backend are ignored, so a flow can carry one param bundle across models.

    Pass ``ctx`` (a RunContext) to record this call's token usage into the run —
    complete() is the single provider choke point, so any node routing LLM calls
    through it gets token accounting (in usage.json) for free.
    """
    params = params or {}
    if is_agent_sdk(spec):
        return _complete_agent_sdk(spec, model_key, system, user, params,
                                   ctx=ctx, node=node)
    return _complete_http(spec, model_key, system, user, params, timeout,
                          ctx=ctx, node=node)
