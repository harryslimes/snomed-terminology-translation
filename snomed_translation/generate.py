"""Generic "prompt + template data -> one text result" via the Claude Agent SDK.

The thin counterpart of the translate/score nodes: render a prompt template with
wired/where-given context, send it to a SOTA Claude model through the **Claude
Agent SDK** (reusing the host's Claude Code subscription auth — no API key, no
in-app token cost beyond your allowance), and capture the model's text reply as a
single scalar artifact written to a file.

The first use is *instruction-prompt induction*: feed a pruned corpus of EN->KO
SNOMED pairs + hierarchy + clinician/model critiques and ask Opus (thinking) to
write a translation instruction guide. The produced file is a ``text`` artifact
that doubles as a ``style_guide`` kind, so it wires straight into a ``translate``
node or seeds GEPA's ``optimize`` node.

Templating mirrors ``score_workflow_llm``: ``{{context}}`` inserts the assembled
context (wired ``context`` inputs + any ``context_paths`` files, concatenated);
``{{name}}`` inserts a single wired input's rendered text by its port name.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from pipelines.context import RunContext
from pipelines.functions import FunctionResult

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"{{\s*([\w.]+)\s*}}")


# ---------------------------------------------------------------------------
# Rendering context inputs to text.
# ---------------------------------------------------------------------------
def _value_to_text(value: Any) -> str:
    """Render one wired input (a path, a resolved-dataset dict, or raw text)."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for k in ("_primary", "dataset", "rows", "path", "text", "style_guide"):
            v = value.get(k)
            if isinstance(v, str):
                value = v
                break
        else:
            return str(value)
    s = str(value)
    p = Path(s)
    if len(s) < 4096 and p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    return s


def assemble_context(inputs: dict[str, Any], context_paths: list[str],
                     max_chars: int) -> tuple[str, dict[str, str]]:
    """Concatenate every wired ``context`` input + every ``context_paths`` file
    into one block, and also return a per-port rendered map for ``{{name}}``."""
    per_port = {port: _value_to_text(val) for port, val in inputs.items()
                if val is not None}
    parts: list[str] = [t for t in per_port.values() if t]
    for cp in context_paths:
        cp = cp.strip()
        if not cp:
            continue
        p = Path(cp)
        if not p.exists():
            raise FileNotFoundError(f"context_paths entry not found: {cp}")
        parts.append(p.read_text(encoding="utf-8", errors="replace"))
    block = "\n\n".join(parts)
    if max_chars and len(block) > max_chars:
        block = block[:max_chars] + f"\n\n[...truncated at {max_chars} chars...]"
    return block, per_port


def render_prompt(template: str, context: str, per_port: dict[str, str]) -> str:
    repl: dict[str, str] = dict(per_port)
    repl["context"] = context

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key not in repl:
            raise KeyError(key)
        return repl[key]

    return _TOKEN_RE.sub(_sub, template)


# ---------------------------------------------------------------------------
# Claude Agent SDK call (async, driven synchronously from the runner).
# ---------------------------------------------------------------------------
# Minimal default system prompt. We deliberately do NOT use the Claude Code
# preset (that would inject the full agent system prompt); a plain string fully
# overrides it. Override per-call with the `system` param.
_DEFAULT_SYSTEM = (
    "You are an expert assistant. Follow the user's instructions exactly and "
    "output only what is requested, with no preamble or sign-off."
)


async def _aquery(prompt: str, *, model: str, system: str | None,
                  thinking: bool, max_thinking_tokens: int, effort: str | None,
                  cwd: str | None) -> str:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        TextBlock,
        query,
    )
    # Minimise everything sent to the model: no tool definitions (`tools=[]`),
    # no project CLAUDE.md / skills / settings (`setting_sources=[]`), no MCP
    # schemas (`mcp_servers={}`), and a short overriding system prompt. The only
    # context is our prompt + the minimal system line.
    opts: dict[str, Any] = {
        "model": model,
        "system_prompt": system or _DEFAULT_SYSTEM,
        "tools": [],
        "allowed_tools": [],
        "mcp_servers": {},
        "setting_sources": [],
        "permission_mode": "default",
        "max_turns": 1,
    }
    if cwd:
        opts["cwd"] = cwd
    if thinking:
        budget = max_thinking_tokens or 16000
        opts["thinking"] = {"type": "enabled", "budget_tokens": budget}
        opts["max_thinking_tokens"] = budget
        if effort:
            opts["effort"] = effort   # 'low' | 'medium' | 'high' | 'max'
    else:
        opts["thinking"] = {"type": "disabled"}
    options = ClaudeAgentOptions(**opts)

    # Drain the stream fully (do NOT break early — closing the async generator
    # mid-iteration raises "aclose(): asynchronous generator is already running").
    chunks: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
    return "".join(chunks).strip()


def run_query(prompt: str, *, model: str = "opus", system: str | None = None,
              thinking: bool = True, max_thinking_tokens: int = 0,
              effort: str | None = "high", cwd: str | None = None) -> str:
    return asyncio.run(_aquery(prompt, model=model, system=system,
                               thinking=thinking,
                               max_thinking_tokens=max_thinking_tokens,
                               effort=effort, cwd=cwd))


# ---------------------------------------------------------------------------
# FunctionRunner.
# ---------------------------------------------------------------------------
def resolve_prompt(params: dict[str, Any],
                   ctx: RunContext) -> tuple[str | None, str | None, str | None]:
    """Return ``(template_str, template_id, version)``. When ``prompt_template``
    (a stored template id) is set it wins over the inline ``prompt``; the loaded
    body + its content-hash version are returned so the run pins the exact
    revision it used (design D4). Prompts dir: ``WIZARD_PROMPTS_DIR`` env, else
    ``<configs_dir>/prompts``."""
    tid = params.get("prompt_template")
    if tid:
        import os
        from pipelines.prompts import load_template
        base = os.environ.get("WIZARD_PROMPTS_DIR")
        if not base:
            cfg = getattr(ctx, "configs_dir", None)
            base = str(Path(cfg) / "prompts") if cfg else "configs/prompts"
        t = load_template(base, str(tid))
        return t.body, str(tid), t.current_version
    return params.get("prompt"), None, None


def generate_text(ctx: RunContext, inputs: dict[str, Any],
                  params: dict[str, Any]) -> FunctionResult:
    try:
        template, tmpl_id, tmpl_ver = resolve_prompt(params, ctx)
    except FileNotFoundError as exc:
        return FunctionResult(ok=False, message=str(exc))
    if not template:
        return FunctionResult(
            ok=False, message="generate_text needs a `prompt` or `prompt_template`")
    context_paths = [s for s in str(params.get("context_paths") or "").split(",")]
    max_chars = int(params.get("max_context_chars") or 400_000)
    try:
        context, per_port = assemble_context(inputs, context_paths, max_chars)
    except FileNotFoundError as exc:
        return FunctionResult(ok=False, message=str(exc))
    try:
        rendered = render_prompt(template, context, per_port)
    except KeyError as exc:
        avail = ", ".join(sorted(per_port)) or "(none)"
        return FunctionResult(
            ok=False,
            message=f"prompt references unknown token {exc}. "
                    f"Available: {{context}}, plus wired ports: {avail}")

    model = str(params.get("model") or "opus")
    thinking = bool(params.get("thinking", True))
    max_think = int(params.get("max_thinking_tokens") or 0)
    effort = str(params.get("effort") or "high") if thinking else None
    system = params.get("system") or None
    try:
        reply = run_query(rendered, model=model, system=system, thinking=thinking,
                          max_thinking_tokens=max_think, effort=effort,
                          cwd=str(ctx.configs_dir) if ctx.configs_dir else None)
    except Exception as exc:  # noqa: BLE001 — surface as a stage failure
        return FunctionResult(ok=False, message=f"Agent SDK call failed: {exc}")
    if not reply:
        return FunctionResult(ok=False, message="model returned no text")

    tag = str(params.get("output_tag") or "generated")
    ext = str(params.get("output_ext") or "md").lstrip(".")
    out_dir = Path(ctx.log_dir) if ctx.log_dir else Path(".")
    out = out_dir / f"{tag}.{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(reply, encoding="utf-8")
    outputs: dict[str, Any] = {"text": str(out), "style_guide": str(out)}
    if tmpl_id:                       # pin the exact template revision the run used
        outputs["prompt_template"] = tmpl_id
        outputs["prompt_version"] = tmpl_ver or ""
    return FunctionResult(
        ok=True,
        outputs=outputs,
        metrics={"context_chars": float(len(context)),
                 "output_chars": float(len(reply))},
        message=f"generated {len(reply)} chars via {model} -> {out.name}")
