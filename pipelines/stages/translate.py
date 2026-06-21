"""Translation stage runner.

Reuses helpers from `scripts/translation/translate_korean_with_lookup.py`
(translate_one, _auth_headers, format_pairs_table, wait_for_server). The
original script's CLI keeps working — this module is an additional path
that drives the same internals from a PipelineConfig.
"""
from __future__ import annotations

import csv
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

from pipelines.config import PipelineConfig
from pipelines.context import RunContext, StageResult
from pipelines.exemplars import ExemplarError, ensure_exemplars
from scripts.translation.translate_korean_with_lookup import (
    translate_one,
    format_pairs_table,
    wait_for_server,
)

log = logging.getLogger(__name__)


def _build_prompts(cfg: PipelineConfig) -> tuple[str, str]:
    """Render system + user prompt templates with language placeholders."""
    if cfg.translation.style_guide_path is None:
        raise RuntimeError(
            "translate stage requires a style guide; supply via the flow "
            "step's `style_guide_path` param, or bake one into the config's "
            "translation.style_guide_path field as a single-stage default."
        )
    style_guide = cfg.translation.style_guide_path.read_text(encoding="utf-8")
    script_name = {
        "ko": "Hangul (한글)",
        "et": "Estonian (latin script)",
        "es": "Spanish (latin script)",
        "fr": "French (latin script)",
        "ja": "Japanese",
        "zh": "Chinese",
    }.get(cfg.language.code, f"the {cfg.language.name} script")

    fmt_kwargs = dict(
        language_name=cfg.language.name,
        language_script_name=script_name,
        style_guide=style_guide,
    )
    return (
        cfg.translation.prompt_templates.system.format(**fmt_kwargs),
        cfg.translation.prompt_templates.user,  # leaves {paired_translations} and {english} for later
    )


def _load_eval_rows(cfg: PipelineConfig, limit: int | None) -> list[dict]:
    """Load eval-set CSV honoring the abstract→physical column mapping."""
    if cfg.eval_set is None:
        raise RuntimeError(
            "translate stage requires an eval set; pass --eval-set to "
            "pipelines.run, or bake one into the config's eval_set block."
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


def run(cfg: PipelineConfig, ctx: RunContext, *,
        limit: int | None = None, resume: bool = False,
        temperature: float | None = None, **_) -> StageResult:
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
    base_url = os.getenv("VLLM_BASE_URL", cfg.model_base_url(model_key).rsplit("/v1", 1)[0])
    # translate_one appends /v1/chat/completions — strip /v1 from our helper
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    model_id = model.hf_id
    concurrency = candidate.concurrency
    llm_params = dict(candidate.llm_params)
    if temperature is not None:
        llm_params["temperature"] = temperature
    log.info("Translating with candidate model=%s concurrency=%s temperature=%s "
             "llm_param_keys=%s", model_key, concurrency,
             llm_params.get("temperature"), list(llm_params.keys()))

    # Auth env propagation (existing translate_one's _auth_headers reads OPENAI_API_KEY /
    # DASHSCOPE_API_KEY / VLLM_API_KEY from env). We just need the right env var set.
    if candidate.api_key_env and os.getenv(candidate.api_key_env):
        os.environ.setdefault("VLLM_API_KEY", os.environ[candidate.api_key_env])

    # Prompts
    system_prompt, user_template = _build_prompts(cfg)
    log.info("system_prompt=%d chars (style guide loaded from %s)",
             len(system_prompt), cfg.translation.style_guide_path)

    # Wait for endpoint
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
        lookup_cache = ensure_exemplars(cfg, remaining)
    except ExemplarError as exc:
        return StageResult(stage="translate", ok=False,
                           message=f"exemplars unavailable: {exc}")

    # Translation
    write_lock = Lock()
    completed = [0]
    errors = [0]
    t0 = time.monotonic()
    mode = "a" if resume and done_sctids else "w"
    outf = out_path.open(mode, encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf, fieldnames=["sctid", "preferred_term", "ko_reference", "translation"],
    )
    if mode == "w":
        writer.writeheader()

    def process_row(row: dict) -> dict:
        english = row["preferred_term"]
        pairs = lookup_cache.get(row["sctid"], [])[: cfg.translation.lookup_topn]
        pairs_table = format_pairs_table(pairs)
        user_prompt = user_template.format(
            paired_translations=pairs_table,
            english=english,
            language_name=cfg.language.name,
        )
        try:
            t = translate_one(base_url, model_id, system_prompt, user_prompt, llm_params)
        except Exception as exc:
            log.error("%s -> ERROR %s", english[:40], exc)
            t = f"ERROR: {exc}"
        return {
            "sctid": row["sctid"],
            "preferred_term": english,
            "ko_reference": row["reference"],
            "translation": t,
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(process_row, row): row for row in remaining}
        for fut in as_completed(futures):
            if ctx.is_cancelled():
                log.warning("Cancelled — aborting remaining work")
                break
            result = fut.result()
            with write_lock:
                writer.writerow(result)
                outf.flush()
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
    elapsed = time.monotonic() - t0

    return StageResult(
        stage="translate",
        ok=errors[0] == 0,
        outputs={"output_csv": out_path},
        output_paths=[out_path],
        metrics={
            "n_translated": float(completed[0]),
            "n_errors": float(errors[0]),
            "elapsed_seconds": elapsed,
            "throughput_rps": completed[0] / elapsed if elapsed > 0 else 0,
        },
        message=f"{completed[0]} translations, {errors[0]} errors, {elapsed:.0f}s",
    )
