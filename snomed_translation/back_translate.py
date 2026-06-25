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


def translategemma_prompt(text: str, *, source_lang: str = "Korean",
                          source_code: str = "ko", target_lang: str = "English",
                          target_code: str = "en") -> str:
    """Render TranslateGemma's translation prompt for ``/v1/completions``.

    TranslateGemma (google/translategemma-*) is a translation-specialised Gemma 3
    with a bespoke chat template: it takes no system/instruction prose, only a
    structured ``{source_lang_code, target_lang_code, text}`` item. vLLM's
    OpenAI *chat* endpoint strips those custom keys, so we render the template
    body ourselves and post it to the *completions* endpoint instead."""
    return (
        f"<start_of_turn>user\nYou are a professional {source_lang} ({source_code}) "
        f"to {target_lang} ({target_code}) translator. Your goal is to accurately "
        f"convey the meaning and nuances of the original {source_lang} text while "
        f"adhering to {target_lang} grammar, vocabulary, and cultural "
        f"sensitivities.\nProduce only the {target_lang} translation, without any "
        f"additional explanations or commentary. Please translate the following "
        f"{source_lang} text into {target_lang}:\n\n\n{text.strip()}"
        f"<end_of_turn>\n<start_of_turn>model\n"
    )


def translate_completion(base_url: str, model_id: str, text: str, *,
                         source_lang: str = "Korean", source_code: str = "ko",
                         target_lang: str = "English", target_code: str = "en",
                         temperature: float = 0.0, max_tokens: int = 48,
                         timeout: tuple[float, float | None] = (10, None)) -> str:
    """One TranslateGemma translation via ``/v1/completions`` → first line."""
    r = requests.post(
        f"{base_url.rstrip('/')}/v1/completions",
        json={"model": model_id, "temperature": temperature,
              "max_tokens": max_tokens, "stop": ["<end_of_turn>"],
              "prompt": translategemma_prompt(
                  text, source_lang=source_lang, source_code=source_code,
                  target_lang=target_lang, target_code=target_code)},
        timeout=timeout)
    r.raise_for_status()
    txt = (r.json()["choices"][0].get("text") or "").strip()
    return txt.splitlines()[0].strip().strip('".') if txt else ""


def back_translate_terms(terms: Iterable[str], *, base_url: str, model_id: str,
                         system: str = DEFAULT_SYSTEM, temperature: float = 0.0,
                         max_tokens: int = 48, fmt: str = "chat",
                         source_lang: str = "Korean", source_code: str = "ko",
                         target_lang: str = "English",
                         target_code: str = "en") -> list[str]:
    """Back-translate each Korean term to English (one call per term).

    ``fmt="chat"`` (default) uses an instruction system prompt against the chat
    endpoint; ``fmt="translategemma"`` uses TranslateGemma's structured
    translation prompt against the completions endpoint."""
    if fmt == "translategemma":
        return [translate_completion(
            base_url, model_id, t, source_lang=source_lang,
            source_code=source_code, target_lang=target_lang,
            target_code=target_code, temperature=temperature,
            max_tokens=max_tokens) for t in terms]
    return [chat(base_url, model_id, system, t, temperature=temperature,
                 max_tokens=max_tokens) for t in terms]
