"""A ``dspy.LM`` that routes to our unified ``complete()`` provider.

DSPy (and therefore GEPA) only knows how to call OpenAI/LiteLLM endpoints, so it
could not use the endpoint-less Agent-SDK models (Claude Fable/Opus/Sonnet) that
``snomed_translation.llm.complete`` speaks. This closes that gap generically:
``dspy_lm_for(model_key, cfg)`` returns a ``dspy.LM`` for ANY ``models.json``
entry — a ``ProviderLM`` (→ ``complete`` → Agent SDK) for ``claude_agent_sdk``
backends, or the existing ``dspy.LM("openai/<hf_id>", api_base=…)`` LiteLLM path
for served HTTP backends. So GEPA's task LM, reflection LM, and judge can each be
any catalogued model.
"""
from __future__ import annotations

import os
from typing import Any

import dspy

from snomed_translation.config import ModelSpec, PipelineConfig
from snomed_translation.llm import complete, is_agent_sdk


def _split_messages(prompt: str | None,
                    messages: list[dict[str, Any]] | None) -> tuple[str | None, str]:
    """Collapse DSPy's prompt/messages into a ``(system, user)`` pair for
    ``complete``. System-role turns join into the system prompt; everything else
    is concatenated (role-tagged) into one user turn."""
    if messages:
        sys_parts, user_parts = [], []
        for m in messages:
            content = m.get("content")
            if isinstance(content, list):  # multimodal blocks → take text bits
                content = " ".join(b.get("text", "") for b in content
                                   if isinstance(b, dict))
            content = str(content or "")
            role = m.get("role", "user")
            if role == "system":
                sys_parts.append(content)
            elif role == "assistant":
                user_parts.append(f"[assistant]\n{content}")
            else:
                user_parts.append(content)
        return ("\n\n".join(sys_parts) or None), "\n\n".join(user_parts)
    return None, str(prompt or "")


class ProviderLM(dspy.LM):
    """dspy.LM backed by ``complete()`` (Agent SDK). We override ``__call__`` so
    DSPy's LiteLLM machinery is never touched — the base ``__init__`` only stores
    config."""

    def __init__(self, spec: ModelSpec, model_key: str, *,
                 temperature: float = 1.0, max_tokens: int = 4000, **params: Any):
        super().__init__(model=f"provider/{model_key}", model_type="chat",
                         temperature=temperature, max_tokens=max_tokens, cache=False)
        self._spec = spec
        self._model_key = model_key
        self._params = {"temperature": temperature, "max_tokens": max_tokens,
                        **(spec.llm_params or {}), **params}

    def __call__(self, prompt: str | None = None,
                 messages: list[dict[str, Any]] | None = None,
                 **kwargs: Any) -> list[str]:
        system, user = _split_messages(prompt, messages)
        text = complete(self._spec, self._model_key, system, user, self._params)
        return [text]


def dspy_lm_for(model_key: str, cfg: PipelineConfig, *,
                temperature: float = 1.0, max_tokens: int = 4000,
                disable_thinking: bool = False) -> "dspy.LM":
    """A ``dspy.LM`` for any ``models.json`` model — Agent-SDK via ProviderLM,
    else the LiteLLM/vLLM path."""
    spec = cfg.models[model_key]
    if is_agent_sdk(spec):
        return ProviderLM(spec, model_key, temperature=temperature,
                          max_tokens=max_tokens)
    kwargs: dict[str, Any] = dict(
        api_base=os.getenv("VLLM_BASE_URL", cfg.model_base_url(model_key)),
        api_key=(os.environ.get(spec.api_key_env, "EMPTY")
                 if spec.api_key_env else "EMPTY"),
        temperature=temperature, max_tokens=max_tokens)
    if disable_thinking:
        kwargs["extra_body"] = {"enable_thinking": False}
    model_id = spec.hf_id or spec.model_path or model_key
    return dspy.LM(f"openai/{model_id}", **kwargs)
