"""Translation stage runner.

Reuses helpers from `scripts/translation/translate_korean_with_lookup.py`
(translate_one, _auth_headers, format_pairs_table, wait_for_server). The
original script's CLI keeps working — this module is an additional path
that drives the same internals from a PipelineConfig.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from snomed_translation.config import PipelineConfig
from pipelines.context import RunContext, StageResult
from pipelines.llm_accounting import vllm_cache_scope
from snomed_translation.exemplars import ExemplarError, ensure_exemplars
from snomed_translation.llm import complete, is_agent_sdk, recommended_concurrency
from scripts.translation.translate_korean_with_lookup import (
    format_pairs_table,
    wait_for_server,
)

log = logging.getLogger(__name__)


def _template_body(template_id: str | None, default_body: str) -> str:
    """The prompt body from the version-controlled store (WIZARD_PROMPTS_DIR/<id>)
    when ``template_id`` is set and present; else the inline config default. This
    is the render path shared with GEPA (design D7) — production optimises exactly
    the template it runs. Missing store template ⇒ the default (output unchanged)."""
    if not template_id:
        return default_body
    base = os.environ.get("WIZARD_PROMPTS_DIR", "configs/prompts")
    try:
        from pipelines.prompts import load_template
        return load_template(base, template_id).body
    except FileNotFoundError:
        return default_body


_SCRIPT_NAMES = {
    "ko": "Hangul (한글)",
    "et": "Estonian (latin script)",
    "es": "Spanish (latin script)",
    "fr": "French (latin script)",
    "ja": "Japanese",
    "zh": "Chinese",
}


def script_name(code: str, name: str) -> str:
    """The human-readable script label for a language code (e.g. ko -> Hangul)."""
    return _SCRIPT_NAMES.get(code, f"the {name} script")


def render_user(user_body: str, *, paired_translations: str, english: str,
                language_name: str) -> str:
    """Render one concept's user turn (the data envelope) via the shared renderer."""
    from pipelines.prompts import render
    return render(user_body, {"paired_translations": paired_translations,
                              "english": english, "language_name": language_name})


def _build_prompts(cfg: PipelineConfig) -> tuple[str, str]:
    """Render the system instruction + return the user (data-envelope) template.

    Both bodies come from the store (by id) when configured, else the inline
    config default, and render through the shared ``pipelines.prompts.render``
    (double-brace ``{{token}}``) — one path for production and GEPA."""
    from pipelines.prompts import render
    if cfg.translation.style_guide_path is None:
        raise RuntimeError(
            "translate stage requires a style guide; supply via the flow "
            "step's `style_guide_path` param, or bake one into the config's "
            "translation.style_guide_path field as a single-stage default."
        )
    style_guide = cfg.translation.style_guide_path.read_text(encoding="utf-8")
    pt = cfg.translation.prompt_templates
    system_body = _template_body(pt.system_template_id, pt.system)
    user_body = _template_body(pt.user_template_id, pt.user)
    system_prompt = render(system_body, {
        "language_name": cfg.language.name,
        "language_script_name": script_name(cfg.language.code, cfg.language.name),
        "style_guide": style_guide,
    })
    return system_prompt, user_body  # user rendered per row via render_user()


def _load_eval_rows(cfg: PipelineConfig, limit: int | None) -> list[dict]:
    """Load eval-set CSV honoring the abstract→physical column mapping."""
    if cfg.eval_set is None:
        raise RuntimeError(
            "translate stage requires an eval set; pass --eval-set to "
            "snomed_translation.run, or bake one into the config's eval_set block."
        )
    csv_path = cfg.eval_set.csv
    cols = cfg.eval_set.columns
    rows = []
    with csv_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "sctid": row[cols.sctid],
                "preferred_term": row[cols.source_term],
                # reference is optional — present in some splits, absent in fresh runs
                "reference": row.get(cols.reference, ""),
            })
    if limit:
        rows = rows[:limit]
    return rows


def _apply_thinking(llm_params: dict, thinking: bool | None,
                    use_sdk: bool = False, style: str | None = None) -> dict:
    """Force reasoning/thinking mode on or off, using the API's own convention.

    Providers disagree, and getting it wrong fails in two different ways:
      * ``sdk``              -> ``thinking: bool``          (Claude Agent SDK)
      * ``enable_thinking``  -> ``enable_thinking`` + ``chat_template_kwargs``
                                (vLLM, DashScope/Qwen)
      * ``reasoning_effort`` -> ``reasoning_effort: none``  (DeepSeek)

    Sending Claude's ``thinking`` key to DashScope returns 400; sending
    ``enable_thinking`` to DeepSeek is SILENTLY IGNORED (verified 2026-08-10:
    reasoning tokens kept flowing), which is the more dangerous failure. So the
    convention is declared per model (``thinking_style`` in the catalogue)
    rather than guessed. ``thinking=None`` inherits the model's own default.
    """
    if thinking is None:
        return llm_params
    out = dict(llm_params)
    on = bool(thinking)
    style = style or ("sdk" if use_sdk else "enable_thinking")
    # Clear every convention first so a stale key can't re-enable reasoning.
    for key in ("thinking", "enable_thinking", "reasoning_effort"):
        out.pop(key, None)
    ctk = {k: v for k, v in (out.get("chat_template_kwargs") or {}).items()
           if k != "enable_thinking"}
    if style == "sdk":
        out["thinking"] = on
    elif style == "reasoning_effort":
        out["reasoning_effort"] = "medium" if on else "none"
    else:
        out["enable_thinking"] = on
        ctk["enable_thinking"] = on
    if ctk:
        out["chat_template_kwargs"] = ctk
    else:
        out.pop("chat_template_kwargs", None)
    if not on:
        # An effort/budget left behind would re-enable reasoning on some backends.
        out.pop("effort", None)
        out.pop("max_thinking_tokens", None)
    return out


def run(cfg: PipelineConfig, ctx: RunContext, *,
        limit: int | None = None, resume: bool = False,
        temperature: float | None = None,
        thinking: bool | None = None,
        request_timeout_seconds: float = 120.0,
        max_attempts: int = 3, **_) -> StageResult:
    """Translate every concept in the eval set; write a CSV of results."""
    try:
        candidate = cfg.translation.resolve_candidate()
    except RuntimeError as exc:
        return StageResult(stage="translate", ok=False, message=str(exc))
    model_key = candidate.model_key
    if model_key not in cfg.models:
        return StageResult(stage="translate", ok=False,
                           message=f"model_key {model_key!r} resolved from "
                                    f"candidates but not in cfg.models — check "
                                    f"the models catalogue")
    model = cfg.models[model_key]
    use_sdk = is_agent_sdk(model)
    base_url = os.getenv("VLLM_BASE_URL", cfg.model_base_url(model_key).rsplit("/v1", 1)[0])
    # translate_one appends /v1/chat/completions — strip /v1 from our helper
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    # Served model id — used to scope the vLLM prefix-cache metric (harmless for
    # Agent-SDK models, whose /metrics query simply returns nothing).
    model_id = model.hf_id or model_key
    # Endpoint-less Agent-SDK models: no server to poll, and subprocess-per-call
    # + subscription rate limits mean the HTTP fan-out must be throttled.
    concurrency = recommended_concurrency(model, candidate.concurrency)
    llm_params = dict(candidate.llm_params)
    if temperature is not None:
        llm_params["temperature"] = temperature
    llm_params = _apply_thinking(llm_params, thinking, use_sdk=use_sdk,
                                 style=getattr(model, 'thinking_style', None))
    # Effective reasoning state, resolved across the three backend conventions —
    # logged so a run never leaves it ambiguous which regime was compared.
    _effort = llm_params.get("reasoning_effort")
    effective_thinking = bool(
        llm_params.get("thinking",
                       llm_params.get("enable_thinking",
                                      (llm_params.get("chat_template_kwargs") or {})
                                      .get("enable_thinking",
                                           _effort not in (None, "none")))))
    log.info("Translating with candidate model=%s concurrency=%s temperature=%s "
             "thinking=%s (%s) llm_param_keys=%s", model_key, concurrency,
             llm_params.get("temperature"), effective_thinking,
             "node override" if thinking is not None else "model default",
             list(llm_params.keys()))

    # Auth env propagation (existing translate_one's _auth_headers reads OPENAI_API_KEY /
    # DASHSCOPE_API_KEY / VLLM_API_KEY from env). We just need the right env var set.
    if candidate.api_key_env and os.getenv(candidate.api_key_env):
        os.environ.setdefault("VLLM_API_KEY", os.environ[candidate.api_key_env])

    # Prompts
    system_prompt, user_template = _build_prompts(cfg)
    log.info("system_prompt=%d chars (style guide loaded from %s)",
             len(system_prompt), cfg.translation.style_guide_path)

    # Wait for endpoint (HTTP backends only; the Agent SDK has no endpoint)
    if not use_sdk:
        wait_for_server(base_url)

    # Load rows
    rows = _load_eval_rows(cfg, limit)
    log.info("Eval set: %d rows", len(rows))

    # Output path: run-scoped when the run has a log dir (immutable run
    # store — re-runs don't clobber earlier outputs; resume works when
    # re-running with the same --log-dir). Legacy shared dir otherwise.
    out_dir = ctx.artifacts_dir() or cfg.paths.output_dir
    out_path = out_dir / cfg.translation.output_filename_pattern.format(
        output_tag=cfg.translation.output_tag,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume
    done_sctids: set[str] = set()
    if resume and out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done_sctids.add(r["sctid"])
        log.info("Resuming: %d already done", len(done_sctids))

    remaining = [r for r in rows if r["sctid"] not in done_sctids]
    if not remaining:
        return StageResult(stage="translate", ok=True,
                           outputs={"output_csv": out_path},
                           output_paths=[out_path],
                           message=f"Nothing to do ({len(rows)} already complete)")

    # Exemplars: the wired collection is the source of truth — the on-disk
    # cache only accelerates repeat runs. Missing/stale coverage triggers a
    # live Qdrant lookup (indexing the collection first if needed); failure
    # fails the stage rather than silently translating without exemplars.
    try:
        lookup_cache, exclusions = ensure_exemplars(cfg, remaining)
    except ExemplarError as exc:
        return StageResult(stage="translate", ok=False,
                           message=f"exemplars unavailable: {exc}")

    # Self-exclusion audit: record exactly which exemplars were dropped (the
    # query concept's own canonical SNOMED entries) and quantify residual leak.
    # `excluded_exemplars_<tag>.csv` lists every dropped exemplar; the metrics
    # summarise how much the leak was (gold_removed) and any residual gold that
    # survives via an independent, non-canonical source (kept but tagged).
    from snomed_translation.scoring import norm_text as _norm
    excl_rows: list[dict] = []
    n_gold_removed = 0
    n_gold_via_other = 0
    ref_by_sctid = {r["sctid"]: (r.get("reference") or "").strip()
                    for r in remaining}
    for row in remaining:
        sid = row["sctid"]
        gold = ref_by_sctid.get(sid, "")
        gnorm = _norm(gold) if gold else None
        dropped = exclusions.get(sid, [])
        for ex in dropped:
            excl_rows.append({
                "query_sctid": sid, "query_en": row["preferred_term"],
                "excluded_en": ex[0], "excluded_ko": ex[1],
                "excluded_source": ex[2] if len(ex) > 2 else "",
                "excluded_sctid": ex[3] if len(ex) > 3 else "",
                "rank": ex[4] if len(ex) > 4 else "",
            })
        if gnorm is not None:
            if any(_norm(ex[1]) == gnorm for ex in dropped):
                n_gold_removed += 1          # leak we removed
            kept = lookup_cache.get(sid, [])
            if any(len(p) > 1 and _norm(p[1]) == gnorm for p in kept):
                n_gold_via_other += 1        # residual leak via another source
    excl_path = out_path.with_name(
        f"excluded_exemplars_{cfg.translation.output_tag or 'run'}.csv")
    try:
        with excl_path.open("w", encoding="utf-8", newline="") as ef:
            ew = csv.DictWriter(ef, fieldnames=[
                "query_sctid", "query_en", "excluded_en", "excluded_ko",
                "excluded_source", "excluded_sctid", "rank"])
            ew.writeheader()
            ew.writerows(excl_rows)
    except Exception as exc:  # reporting must never fail the run
        log.warning("could not write exclusion audit: %s", exc)
    n_self_hit = sum(1 for r in remaining if exclusions.get(r["sctid"]))
    log.info("Self-exclusion: %d exemplars dropped across %d/%d concepts; "
             "gold removed for %d; residual gold via other source for %d",
             len(excl_rows), n_self_hit, len(remaining), n_gold_removed,
             n_gold_via_other)

    # Translation
    write_lock = Lock()
    completed = [0]
    errors = [0]
    retries = [0]
    t0 = time.monotonic()
    mode = "a" if resume and done_sctids else "w"
    outf = out_path.open(mode, encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf, fieldnames=["sctid", "preferred_term", "ko_reference", "translation"],
    )
    if mode == "w":
        writer.writeheader()

    # Prompt capture: persist exactly what the model saw so a run is fully
    # reconstructable — one meta line (rendered system prompt + the user
    # template + call params), then one line per concept with the fully
    # rendered user turn (exemplars table filled in).
    prompts_path = out_path.with_name(
        f"prompts_{cfg.translation.output_tag or 'run'}.jsonl")
    promptf = prompts_path.open(mode, encoding="utf-8")
    if mode == "w":
        promptf.write(json.dumps({
            "kind": "meta", "model_key": model_key, "llm_params": llm_params,
            "thinking": effective_thinking,
            "style_guide_path": str(cfg.translation.style_guide_path),
            "lookup_topn": cfg.translation.lookup_topn,
            "system": system_prompt, "user_template": user_template,
        }, ensure_ascii=False) + "\n")

    def process_row(row: dict) -> dict:
        english = row["preferred_term"]
        pairs = lookup_cache.get(row["sctid"], [])[: cfg.translation.lookup_topn]
        pairs_table = format_pairs_table(pairs)
        user_prompt = render_user(
            user_template, paired_translations=pairs_table, english=english,
            language_name=cfg.language.name)
        try:
            # complete() (the unified provider) records this call's token usage
            # into ctx — vLLM input/output/cached OR Agent-SDK usage.
            t = complete(model, model_key, system_prompt, user_prompt, llm_params,
                         ctx=ctx)
        except Exception as exc:
            log.error("%s -> ERROR %s", english[:40], exc)
            t = f"ERROR: {exc}"
        return {
            "sctid": row["sctid"],
            "preferred_term": english,
            "ko_reference": row["reference"],
            "translation": t,
            "_user_prompt": user_prompt,
        }

    with vllm_cache_scope(ctx, base_url=base_url, model_id=model_id,
                          model_key=model_key), \
         ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(process_row, row): row for row in remaining}
        for fut in as_completed(futures):
            if ctx.is_cancelled():
                log.warning("Cancelled — aborting remaining work")
                break
            result = fut.result()
            user_prompt = result.pop("_user_prompt", "")
            with write_lock:
                writer.writerow(result)
                outf.flush()
                promptf.write(json.dumps(
                    {"kind": "row", "sctid": result["sctid"],
                     "user": user_prompt}, ensure_ascii=False) + "\n")
                completed[0] += 1
                if result["translation"].startswith("ERROR"):
                    errors[0] += 1
                if completed[0] % 50 == 0:
                    elapsed = time.monotonic() - t0
                    rate = completed[0] / elapsed if elapsed > 0 else 0
                    eta = (len(remaining) - completed[0]) / rate if rate > 0 else 0
                    log.info("Progress: %d/%d (%.0f%%) | %.1f req/s | ETA %.0fs | errors: %d",
                             completed[0], len(remaining),
                             100 * completed[0] / len(remaining), rate, eta, errors[0])

    outf.close()
    promptf.close()
    elapsed = time.monotonic() - t0

    return StageResult(
        stage="translate",
        ok=errors[0] == 0,
        outputs={"output_csv": out_path, "prompts": prompts_path},
        output_paths=[out_path, prompts_path]
        + ([excl_path] if excl_rows else []),
        metrics={
            "n_translated": float(completed[0]),
            "n_errors": float(errors[0]),
            "elapsed_seconds": elapsed,
            "throughput_rps": completed[0] / elapsed if elapsed > 0 else 0,
            # Self-exclusion audit
            "self_excluded_total": float(len(excl_rows)),
            "queries_with_self_hit": float(n_self_hit),
            "gold_removed_by_exclusion": float(n_gold_removed),
            "residual_gold_via_other_source": float(n_gold_via_other),
        },
        message=(f"{completed[0]} translations, {errors[0]} errors, {elapsed:.0f}s"
                 f"; self-excluded {len(excl_rows)} exemplars "
                 f"(gold removed for {n_gold_removed}, residual via other "
                 f"source {n_gold_via_other})"),
    )
