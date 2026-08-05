"""Count the tokens generate_text would actually send to the LLM.

It reconstructs the EXACT request the ``generate_text`` node builds — the system
prompt + the rendered user prompt (template body with ``{{context}}`` filled from
the corpus/context files, honouring ``max_context_chars``) — using the same
plugin code paths (``snomed_translation.generate``), then counts tokens.

Two ways to point it at a payload:

    # 1) From the flow (default) — resolves the generate_text node's wired
    #    prompt_source + text_source (or its params) exactly as a run would:
    python scripts/data_prep/token_count.py                      # flow ko_instruction_induction
    python scripts/data_prep/token_count.py --flow my_flow

    # 2) Ad-hoc — a template id (or inline prompt file) + context file(s):
    python scripts/data_prep/token_count.py \
        --prompt-template ko_instruction_induction \
        --context data/evals/korean/induction_corpus.md

Counting: Anthropic's tokenizer is not public offline, so unless the ``anthropic``
package + ``ANTHROPIC_API_KEY`` are present (then this uses the exact
``messages.count_tokens`` endpoint), the count is an ESTIMATE via tiktoken
(OpenAI o200k_base — the closest available BPE). For this EN+Korean text the true
Claude count typically runs a bit HIGHER (CJK costs more tokens), so treat the
tiktoken number as a floor and budget headroom. The method used is printed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Resolve repo layout from this file: .../snomed-terminology-translation/scripts/data_prep/
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = PLUGIN_ROOT.parent
APP_ROOT = WORKSPACE / "semi-automated-research"


def _default_dir(env: str, rel: str) -> Path:
    return Path(os.environ.get(env) or (PLUGIN_ROOT / "configs" / rel))


def _load_template_body(pid: str, prompts_dir: Path) -> str:
    from pipelines.prompts import load_template
    return load_template(str(prompts_dir), pid).body


def _resolve_from_flow(flow_id: str, flows_dir: Path, prompts_dir: Path
                       ) -> tuple[str, list[str], int, str]:
    """Return (template_body, context_files, max_context_chars, source_desc) for a
    flow's generate_text node — following wired prompt_source/text_source nodes."""
    from pipelines.flow import FlowSpec, ref_node_id
    fp = None
    for ext in (".json", ".yaml", ".yml"):
        cand = flows_dir / f"{flow_id}{ext}"
        if cand.exists():
            fp = cand
            break
    if fp is None:
        sys.exit(f"flow {flow_id!r} not found under {flows_dir}")
    flow = FlowSpec.from_file(fp)
    by_id = {n.id: n for n in flow.nodes}
    gen = next((n for n in flow.nodes
                if n.params.get("function") == "generate_text"), None)
    if gen is None:
        sys.exit(f"flow {flow_id!r} has no generate_text node")

    # --- prompt: wired prompt_source wins, else params ---
    body = desc = None
    if "prompt" in gen.inputs:
        up = by_id.get(ref_node_id(gen.inputs["prompt"]))
        if up and up.params.get("function") == "prompt_source":
            tid = up.params.get("prompt_template")
            body, desc = _load_template_body(tid, prompts_dir), f"prompt_source→{tid}"
    if body is None and gen.params.get("prompt_template"):
        tid = gen.params["prompt_template"]
        body, desc = _load_template_body(tid, prompts_dir), f"prompt_template={tid}"
    if body is None and gen.params.get("prompt"):
        body, desc = gen.params["prompt"], "inline prompt param"
    if body is None:
        sys.exit("generate_text node has no resolvable prompt")

    # --- context: wired text_source path(s) + context_paths param ---
    ctx_files: list[str] = []
    if "context" in gen.inputs:
        up = by_id.get(ref_node_id(gen.inputs["context"]))
        if up and up.params.get("function") == "text_source" and up.params.get("path"):
            ctx_files.append(up.params["path"])
    ctx_files += [s.strip() for s in
                  str(gen.params.get("context_paths") or "").split(",") if s.strip()]
    max_chars = int(gen.params.get("max_context_chars") or 400_000)
    return body, ctx_files, max_chars, f"flow {flow_id} ({desc})"


def _count_tiktoken(text: str) -> tuple[int | None, str]:
    try:
        import tiktoken
    except Exception:
        return None, "tiktoken-unavailable"
    for enc_name in ("o200k_base", "cl100k_base"):
        try:
            enc = tiktoken.get_encoding(enc_name)
            return len(enc.encode(text)), f"tiktoken/{enc_name} (estimate)"
        except Exception:
            continue
    return None, "tiktoken-no-encoding"


def _count_anthropic(system: str, user: str, model: str) -> tuple[int | None, str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "no-api-key"
    try:
        import anthropic
    except Exception:
        return None, "anthropic-not-installed"
    try:
        client = anthropic.Anthropic()
        r = client.messages.count_tokens(
            model=model, system=system,
            messages=[{"role": "user", "content": user}])
        return int(r.input_tokens), f"anthropic/count_tokens({model}) EXACT"
    except Exception as exc:
        return None, f"anthropic-error: {exc}"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Count tokens generate_text would send.")
    p.add_argument("--flow", default="ko_instruction_induction",
                   help="Flow id whose generate_text node to reconstruct "
                        "(default ko_instruction_induction). Ignored if "
                        "--prompt-template/--prompt-file is given.")
    p.add_argument("--prompt-template", help="Stored template id (ad-hoc mode).")
    p.add_argument("--prompt-file", help="Inline prompt body file (ad-hoc mode).")
    p.add_argument("--context", action="append", default=[],
                   help="Context file(s) filling {{context}} (repeatable, ad-hoc).")
    p.add_argument("--max-context-chars", type=int, default=None,
                   help="Truncation guard (ad-hoc; default 400000 or the flow's).")
    p.add_argument("--system", default=None,
                   help="Override the system prompt (default: generate_text's).")
    p.add_argument("--model", default="claude-opus-4-20250514",
                   help="Model id for the exact anthropic count path.")
    p.add_argument("--flows-dir", default=None)
    p.add_argument("--prompts-dir", default=None)
    args = p.parse_args(argv)

    # Make the app importable and reproduce the node's runtime cwd so relative
    # data/ context paths resolve through the app's `data` symlink exactly.
    sys.path.insert(0, str(APP_ROOT))
    if APP_ROOT.is_dir():
        os.chdir(APP_ROOT)

    from snomed_translation.generate import (
        _DEFAULT_SYSTEM, assemble_context, render_prompt)

    flows_dir = Path(args.flows_dir) if args.flows_dir else _default_dir(
        "WIZARD_FLOWS_DIR", "flows")
    prompts_dir = Path(args.prompts_dir) if args.prompts_dir else _default_dir(
        "WIZARD_PROMPTS_DIR", "prompts")

    if args.prompt_template or args.prompt_file:
        if args.prompt_file:
            body = Path(args.prompt_file).read_text(encoding="utf-8")
            source = f"prompt-file {args.prompt_file}"
        else:
            body = _load_template_body(args.prompt_template, prompts_dir)
            source = f"prompt-template {args.prompt_template}"
        ctx_files = list(args.context)
        max_chars = args.max_context_chars or 400_000
    else:
        body, ctx_files, flow_max, source = _resolve_from_flow(
            args.flow, flows_dir, prompts_dir)
        max_chars = args.max_context_chars or flow_max

    context, per_port = assemble_context({}, ctx_files, max_chars)
    user = render_prompt(body, context, per_port)
    system = args.system if args.system is not None else _DEFAULT_SYSTEM
    full = system + "\n" + user

    a_tokens, a_method = _count_anthropic(system, user, args.model)
    t_tokens, t_method = _count_tiktoken(full)
    tokens, method = (a_tokens, a_method) if a_tokens is not None else (t_tokens, t_method)

    def fmt(n): return f"{n:,}" if isinstance(n, int) else "n/a"
    print(f"source          : {source}")
    print(f"context files   : {ctx_files or '(none)'}")
    truncated = "  [TRUNCATED to max_context_chars]" if len(context) >= max_chars else ""
    print(f"max_context_chars: {max_chars:,}{truncated}")
    print("-" * 60)
    print(f"system chars    : {len(system):,}")
    print(f"prompt chars    : {len(user):,}  (context {len(context):,} + template)")
    print(f"total chars     : {len(full):,}")
    print("-" * 60)
    print(f"token count     : {fmt(tokens)}   [{method}]")
    if a_tokens is not None and t_tokens is not None:
        print(f"  tiktoken est. : {fmt(t_tokens)}   [{t_method}]")
    elif a_tokens is None:
        print("  (exact Anthropic count needs the `anthropic` pkg + "
              "ANTHROPIC_API_KEY; add both for messages.count_tokens.)")
        print(f"  chars/token   : {len(full)/t_tokens:.2f}" if t_tokens else "")


if __name__ == "__main__":
    main()
