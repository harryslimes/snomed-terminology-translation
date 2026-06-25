"""KO->EN back-translation for the round-trip confidence method.

Self-contained chat-completions call (no dependency on scripts/) so it can run
inside a flow's function runner. The back-translated English is then looked up
against the SNOMED index (snomed_retrieve) to test whether the round trip
recovers the original concept.
"""
from __future__ import annotations

from typing import Iterable

import requests

DEFAULT_SYSTEM = (
    "You are a medical terminologist. Translate the given Korean SNOMED CT "
    "clinical term into its standard English medical term. Output ONLY the "
    "English term, with no notes, no quotes, no semantic tag."
)


def chat(base_url: str, model_id: str, system: str, user: str, *,
         temperature: float = 0.0, max_tokens: int = 48,
         timeout: tuple[float, float | None] = (10, None)) -> str:
    """One chat-completion turn → the first line of the reply, stripped."""
    r = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        json={"model": model_id, "temperature": temperature,
              "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=timeout)
    r.raise_for_status()
    content = (r.json()["choices"][0]["message"].get("content") or "").strip()
    return content.splitlines()[0].strip().strip('".') if content else ""


def back_translate_terms(terms: Iterable[str], *, base_url: str, model_id: str,
                         system: str = DEFAULT_SYSTEM, temperature: float = 0.0,
                         max_tokens: int = 48) -> list[str]:
    """Back-translate each Korean term to English (one chat call per term)."""
    return [chat(base_url, model_id, system, t, temperature=temperature,
                 max_tokens=max_tokens) for t in terms]
