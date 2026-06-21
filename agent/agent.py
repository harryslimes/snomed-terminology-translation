"""
LangGraph-based agentic translation loop for SNOMED CT EN→ET.

Supports two LLM backends:
  - Claude (Sonnet + Opus) via Anthropic API  [default if ANTHROPIC_API_KEY set]
  - vLLM (OpenAI-compatible)                  [--vllm-url flag]

Cohere reranking and SerpAPI web search are used when their API keys are
present, otherwise gracefully skipped.
"""

from __future__ import annotations

import json
import logging
import os
import re
from ast import literal_eval
from dataclasses import dataclass

import requests
from langgraph.graph import END, START, StateGraph

from models import State
from prompt_templates import (
    forced_revision_template,
    initial_translation_template,
    reflection_template,
)
from utils import get_best_translation, render_paired_translations

logger = logging.getLogger("snomed")
logger.setLevel(logging.INFO)


# ── LLM backend abstraction ────────────────────────────────────────────────


@dataclass
class AgentConfig:
    """Runtime configuration injected into the graph via closure."""

    backend: str = "claude"  # "claude" or "vllm"
    vllm_url: str = "http://localhost:8000"
    vllm_model: str = "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4"
    tools_server: str = "http://localhost:8008"
    use_cohere: bool = False
    use_web_search: bool = False
    use_paired_translations: bool = True
    min_reflection_steps: int = 0  # force at least N enrichment+reflection rounds
    cohere_client: object | None = None


def _call_vllm(config: AgentConfig, prompt: str, max_tokens: int = 512) -> str:
    """Call a vLLM OpenAI-compatible chat endpoint."""
    # Rough token estimate: ~2.5 chars/token for mixed EN/ET medical text.
    # Leave room for max_tokens generation within the model's context window.
    max_prompt_chars = (8192 - max_tokens - 200) * 2
    if len(prompt) > max_prompt_chars:
        logger.warning(
            "Truncating prompt from %d to %d chars to fit context window",
            len(prompt), max_prompt_chars,
        )
        prompt = prompt[:max_prompt_chars]
    payload = {
        "model": config.vllm_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a medical terminology translator for SNOMED CT "
                    "(English → Estonian). Always respond with valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    resp = requests.post(
        f"{config.vllm_url}/v1/chat/completions", json=payload, timeout=120
    )
    if resp.status_code != 200:
        logger.error("vLLM error %d: %s", resp.status_code, resp.text[:500])
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    # Strip thinking blocks if present
    if "<think>" in content:
        content = content.split("</think>")[-1]
    return content.strip()


def _parse_json(raw: str) -> dict:
    """Robustly parse JSON from LLM output."""
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    try:
        return literal_eval(raw)
    except Exception:
        pass
    logger.warning("Failed to parse JSON, using raw: %s", raw[:120])
    return {
        "reasoning": "JSON parse failed",
        "translation": raw.split("\n")[0].strip('"').strip("'"),
        "confident": "NO",
        "changed": "YES",
        "unverified_words": "",
    }


def _invoke_llm(config: AgentConfig, prompt: str, *, role: str = "small") -> dict:
    """
    Invoke the configured LLM and return parsed JSON dict.

    role: "small" (initial/forced revision) or "big" (reflection).
    With vLLM the same model is used for both roles.
    """
    if config.backend == "vllm":
        raw = _call_vllm(config, prompt)
        return _parse_json(raw)
    else:
        # Claude backend
        from langchain.chat_models import init_chat_model

        if role == "big":
            model = init_chat_model(
                model="claude-opus-4-20250514",
                api_key=os.getenv("ANTHROPIC_API_KEY"),
            )
        else:
            model = init_chat_model(
                model="claude-sonnet-4-20250514",
                api_key=os.getenv("ANTHROPIC_API_KEY"),
            )
        response = model.invoke(prompt)
        json_ = literal_eval(
            response.content.replace("```json", "").replace("```", "")
        )
        token_usage = response.response_metadata.get("usage", None)
        json_["token_counts"] = token_usage
        return json_


# ── Graph node factories ───────────────────────────────────────────────────
# Each factory takes an AgentConfig and returns a node function that closes
# over it, so the graph stays a pure StateGraph(State).


def make_prepare_initial_hints(config: AgentConfig):
    def prepare_initial_hints(state: State):
        base = config.tools_server
        snomed = requests.get(
            f"{base}/snomed_graph", params={"sctid": state["sctid"]}
        ).json()

        style = requests.get(
            f"{base}/style_guide",
            params={"hierarchy": snomed.get("hierarchy", "Unknown")},
        ).json()
        style_text = style["general"] + "\n\n" + style["specific"]

        paired = []
        if config.use_paired_translations:
            paired = requests.get(
                f"{base}/paired_translations_en_to_ee",
                params={
                    "preferred_term": snomed.get("preferred_term", "Unknown"),
                    "max_results": 3,
                },
            ).json()

        return {
            **snomed,
            "style_guidelines": style_text,
            "sctid": state["sctid"],
            "en_to_ee_paired_translations": paired,
        }

    return prepare_initial_hints


def make_initial_translation(config: AgentConfig):
    def initial_translation(state: State):
        prompt = initial_translation_template.format(
            preferred_term=state["preferred_term"],
            hierarchy=state["hierarchy"],
            synonyms=" | ".join(state["synonyms"]),
            parent_concepts=" | ".join(state["parent_concepts"]),
            related_concepts=" | ".join(state["related_concepts"]),
            en_to_ee_paired_translations=render_paired_translations(
                state["en_to_ee_paired_translations"]
            ),
            style_guidelines=state["style_guidelines"],
        )
        json_ = _invoke_llm(config, prompt, role="small")
        logger.info(
            "Initial Translation (confident: %s): %s",
            json_.get("confident"),
            json_.get("translation"),
        )
        return {"initial_translation": json_}

    return initial_translation


def make_enrichment_step(config: AgentConfig):
    def enrichment_step(state: State):
        base = config.tools_server
        current_translation = get_best_translation(state)["translation"]

        hints = requests.get(
            f"{base}/sonaveeb",
            params={"estonian_term": current_translation, "max_results": 3},
        ).json()

        paired = []
        if config.use_paired_translations:
            paired = requests.get(
                f"{base}/paired_translations_ee_to_en",
                params={"preferred_term": current_translation, "max_results": 3},
            ).json()

        extracts = []
        for source in ["eesti_arst", "kliinikum", "haiglateliit"]:
            extracts.extend(
                requests.get(
                    f"{base}/{source}",
                    params={
                        "estonian_term": current_translation,
                        "max_results": state["max_extracts"],
                    },
                ).json()
            )

        # Cohere reranking (optional)
        if extracts and config.use_cohere and config.cohere_client is not None:
            ranking = config.cohere_client.rerank(
                model="rerank-v3.5",
                query=current_translation,
                documents=[e["passage"] for e in extracts],
                top_n=state["max_extracts"],
            )
            filtered_extracts = [
                {**extracts[r.index], "relevancy_score": r.relevance_score}
                for r in ranking.results
                if r.relevance_score >= state["min_extract_relevancy_score"]
            ]
        else:
            # Without reranking, just take the top N
            filtered_extracts = extracts[: state["max_extracts"]]

        # Truncate long passages to avoid blowing the context window
        for e in filtered_extracts:
            if len(e.get("passage", "")) > 500:
                e["passage"] = e["passage"][:500] + "..."

        # Web search (optional)
        if config.use_web_search:
            google_snippets = requests.get(
                f"{base}/web_search",
                params={
                    "estonian_term": current_translation,
                    "max_results": state["max_search_results"],
                },
            ).json()
        else:
            google_snippets = []

        return {
            "dictionary_hints": hints,
            "extracts": filtered_extracts,
            "google_scholar_search_snippets": google_snippets,
            "ee_to_en_paired_translations": paired,
        }

    return enrichment_step


def make_reflection_step(config: AgentConfig):
    def reflection_step(state: State):
        prompt = reflection_template.format(
            preferred_term=state["preferred_term"],
            estonian_term=get_best_translation(state)["translation"],
            dictionary_hints=" | ".join(
                [
                    f"* **{hint['term']}**: {hint['definition']}\n"
                    for hint in state["dictionary_hints"][-1]
                ]
            ),
            extracts="\n***\n".join(
                [
                    f"**{e['source']}**\n{e['passage']}\n"
                    for e in state["extracts"][-1]
                ]
            ),
            google_scholar_search_snippets="\n***\n".join(
                [
                    f"**{snippet['title']}**\n{snippet['snippet']}\n"
                    for snippet in state["google_scholar_search_snippets"][-1]
                ]
            ),
            style_guidelines=state["style_guidelines"],
            ee_to_en_paired_translations=render_paired_translations(
                state["ee_to_en_paired_translations"][-1]
            ),
        )
        json_ = _invoke_llm(config, prompt, role="big")
        logger.info(
            "Reflection (confident: %s): %s",
            json_.get("confident"),
            json_.get("translation"),
        )
        return {"revised_translations": json_}

    return reflection_step


def make_forced_revision_step(config: AgentConfig):
    def forced_revision_step(state: State):
        prompt = forced_revision_template.format(
            preferred_term=state["preferred_term"],
            estonian_term=get_best_translation(state)["translation"],
            hierarchy=state["hierarchy"],
            synonyms=" | ".join(state["synonyms"]),
            parent_concepts=" | ".join(state["parent_concepts"]),
            related_concepts=" | ".join(state["related_concepts"]),
            unverified_words=get_best_translation(state)["unverified_words"],
        )
        json_ = _invoke_llm(config, prompt, role="small")
        logger.info(
            "Forced Revision: %s", json_.get("translation")
        )
        return {"forced_revisions": json_}

    return forced_revision_step


# ── Routing ────────────────────────────────────────────────────────────────


def make_route_continue_or_end(config: AgentConfig):
    def route_continue_or_end(state: State):
        total_steps = len(state["revised_translations"])
        at_max = total_steps >= state["max_reflection_steps"]
        confident = get_best_translation(state)["confident"] == "YES"
        forced_minimum = total_steps < config.min_reflection_steps

        if forced_minimum:
            return "not_confident"
        if confident or at_max:
            return "confident_or_max_iter"
        return "not_confident"

    return route_continue_or_end


# ── Graph builder ──────────────────────────────────────────────────────────


def build_agent(config: AgentConfig | None = None):
    """Build and compile the LangGraph agent with the given config."""
    if config is None:
        config = AgentConfig()

    route = make_route_continue_or_end(config)

    graph_builder = StateGraph(State)
    graph_builder.add_node("prepare_initial_hints", make_prepare_initial_hints(config))
    graph_builder.add_node("initial_translation_step", make_initial_translation(config))
    graph_builder.add_node("enrichment_step", make_enrichment_step(config))
    graph_builder.add_node("reflection_step", make_reflection_step(config))
    graph_builder.add_node("forced_revision_step", make_forced_revision_step(config))

    graph_builder.add_edge(START, "prepare_initial_hints")
    graph_builder.add_edge("prepare_initial_hints", "initial_translation_step")
    graph_builder.add_conditional_edges(
        "initial_translation_step",
        route,
        {"not_confident": "enrichment_step", "confident_or_max_iter": END},
    )
    graph_builder.add_edge("enrichment_step", "reflection_step")
    graph_builder.add_conditional_edges(
        "reflection_step",
        route,
        {"not_confident": "forced_revision_step", "confident_or_max_iter": END},
    )
    graph_builder.add_edge("forced_revision_step", "enrichment_step")

    return graph_builder.compile()


# ── Backwards compatibility ────────────────────────────────────────────────
# Old code did `from agent import agent` — keep that working when
# ANTHROPIC_API_KEY is set.

def _make_default_agent():
    """Create the default agent at import time for backwards compat."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    cohere_key = os.getenv("COHERE_API_KEY")
    serpapi_key = os.getenv("SERPAPI_API_KEY")

    cohere_client = None
    if cohere_key:
        try:
            import cohere
            cohere_client = cohere.ClientV2(api_key=cohere_key)
        except ImportError:
            pass

    config = AgentConfig(
        backend="claude" if api_key else "vllm",
        use_cohere=cohere_client is not None,
        use_web_search=bool(serpapi_key),
        cohere_client=cohere_client,
    )
    return build_agent(config)


agent = _make_default_agent()
