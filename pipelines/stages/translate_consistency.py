"""Self-consistency translation stage.

A translate_consistency node *is* a translate node, run N times per concept.
It reuses the plain translate stage's internals (prompt building, eval-row
loading, exemplar lookup, the single-call helper) unchanged — the only new
behaviour is sampling each concept ``samples`` times and recording the
distinct results as a *candidates* artifact.

Output (``candidates_<tag>.csv``), one row per concept:
    sctid, preferred_term, ko_reference, n_samples, n_distinct, candidates,
    top_candidate
where ``candidates`` is a JSON list of ``{"text", "count"}`` (distinct results,
most frequent first) and ``top_candidate`` is the most frequent one (a
convenience for humans — NOT the final answer).

Crucially, **no scoring or selection happens here** — that is the job of the
evaluate_consistency stage. This stage also writes a prompt sidecar
(``candidates_<tag>.prompts.json``: the system prompt, the judging model key,
and each concept's rendered user prompt) so the judge can replay *the full
original prompt that was used* when picking the best candidate.
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipelines.config import PipelineConfig
from pipelines.context import RunContext, StageResult
from pipelines.exemplars import ExemplarError, ensure_exemplars
from pipelines.scoring import norm_text
from pipelines.stages.translate import _build_prompts, _load_eval_rows
from scripts.translation.translate_korean_with_lookup import (
    format_pairs_table,
    translate_one,
    wait_for_server,
)

log = logging.getLogger(__name__)


def _group_candidates(samples: list[str]) -> list[dict]:
    """Collapse N raw samples into distinct candidates with counts.

    Grouping is by normalised text (so trivial whitespace differences merge,
    matching the exact-match scorer), but the *representative* kept is the
    first raw spelling seen for each group. ERROR rows are dropped. Result is
    ordered most-frequent first, ties broken by first appearance.
    """
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for s in samples:
        if not s or s.startswith("ERROR"):
            continue
        key = norm_text(s)
        if not key:
            continue
        if key in groups:
            groups[key]["count"] += 1
        else:
            groups[key] = {"text": s, "count": 1}
    return sorted(groups.values(), key=lambda g: -g["count"])


def run(cfg: PipelineConfig, ctx: RunContext, *,
        samples: int = 5, temperature: float | None = None,
        limit: int | None = None, resume: bool = False, **_) -> StageResult:
    """Translate every concept ``samples`` times; write a candidates CSV."""
    stage = "translate_consistency"
    samples = max(1, int(samples))

    # --- Model + prompt + endpoint setup (mirrors the translate stage). ---
    try:
        candidate = cfg.translation.resolve_candidate()
    except RuntimeError as exc:
        return StageResult(stage=stage, ok=False, message=str(exc))
    model_key = candidate.model_key
    if model_key not in cfg.models:
        return StageResult(stage=stage, ok=False,
                           message=f"model_key {model_key!r} resolved from "
                                    "candidates but not in cfg.models")
    model = cfg.models[model_key]
    base_url = os.getenv("VLLM_BASE_URL",
                         cfg.model_base_url(model_key).rsplit("/v1", 1)[0])
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    model_id = model.hf_id
    concurrency = candidate.concurrency
    llm_params = dict(candidate.llm_params)
    if temperature is not None:
        llm_params["temperature"] = temperature
    if samples > 1 and float(llm_params.get("temperature", 0.0)) == 0.0:
        log.warning("samples=%d but temperature=0 — every sample will be "
                    "identical; set a temperature > 0 on the node for "
                    "self-consistency", samples)
    if candidate.api_key_env and os.getenv(candidate.api_key_env):
        os.environ.setdefault("VLLM_API_KEY", os.environ[candidate.api_key_env])

    system_prompt, user_template = _build_prompts(cfg)
    log.info("[%s] model=%s samples=%d temperature=%s concurrency=%d", stage,
             model_key, samples, llm_params.get("temperature"), concurrency)
    wait_for_server(base_url)

    rows = _load_eval_rows(cfg, limit)
    log.info("[%s] eval set: %d rows × %d samples = %d calls",
             stage, len(rows), samples, len(rows) * samples)

    out_dir = ctx.artifacts_dir() or cfg.paths.output_dir
    out_path = out_dir / f"candidates_{cfg.translation.output_tag}.csv"
    prompts_path = out_path.with_name(out_path.stem + ".prompts.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done_sctids: set[str] = set()
    if resume and out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done_sctids.add(r["sctid"])
        log.info("[%s] resuming: %d already done", stage, len(done_sctids))

    remaining = [r for r in rows if r["sctid"] not in done_sctids]
    if not remaining:
        return StageResult(stage=stage, ok=True,
                           outputs={"candidates_csv": out_path,
                                    "prompts_json": prompts_path},
                           output_paths=[out_path],
                           message=f"Nothing to do ({len(rows)} already complete)")

    try:
        lookup_cache = ensure_exemplars(cfg, remaining)
    except ExemplarError as exc:
        return StageResult(stage=stage, ok=False,
                           message=f"exemplars unavailable: {exc}")

    # Render each concept's user prompt once; sample it N times. The rendered
    # prompt is stashed for the prompt sidecar so the judge can replay it.
    user_prompts: dict[str, str] = {}
    for row in remaining:
        pairs = lookup_cache.get(row["sctid"], [])[: cfg.translation.lookup_topn]
        user_prompts[row["sctid"]] = user_template.format(
            paired_translations=format_pairs_table(pairs),
            english=row["preferred_term"],
            language_name=cfg.language.name,
        )

    # Flatten into (sctid, sample_index) tasks for even concurrency.
    tasks = [(row["sctid"], i) for row in remaining for i in range(samples)]
    by_sctid: dict[str, list[str]] = {row["sctid"]: [] for row in remaining}
    lock = Lock()
    completed = [0]
    errors = [0]
    t0 = time.monotonic()

    def call(sctid: str) -> str:
        try:
            return translate_one(base_url, model_id, system_prompt,
                                 user_prompts[sctid], llm_params)
        except Exception as exc:  # noqa: BLE001 — one bad sample mustn't kill the run
            log.error("%s sample -> ERROR %s", sctid[:12], exc)
            return f"ERROR: {exc}"

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(call, sctid): sctid for sctid, _ in tasks}
        for fut in as_completed(futures):
            if ctx.is_cancelled():
                log.warning("[%s] cancelled — aborting remaining work", stage)
                break
            sctid = futures[fut]
            result = fut.result()
            with lock:
                by_sctid[sctid].append(result)
                completed[0] += 1
                if result.startswith("ERROR"):
                    errors[0] += 1
                if completed[0] % 100 == 0:
                    elapsed = time.monotonic() - t0
                    rate = completed[0] / elapsed if elapsed > 0 else 0
                    log.info("[%s] %d/%d calls (%.1f req/s, %d errors)", stage,
                             completed[0], len(tasks), rate, errors[0])

    # --- Write the candidates artifact + prompt sidecar. ---
    by_term = {row["sctid"]: row for row in remaining}
    fieldnames = ["sctid", "preferred_term", "ko_reference",
                  "n_samples", "n_distinct", "candidates", "top_candidate"]
    mode = "a" if resume and done_sctids else "w"
    n_multi = 0
    with out_path.open(mode, encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == "w":
            writer.writeheader()
        for sctid, raw_samples in by_sctid.items():
            cands = _group_candidates(raw_samples)
            n_distinct = len(cands)
            if n_distinct > 1:
                n_multi += 1
            writer.writerow({
                "sctid": sctid,
                "preferred_term": by_term[sctid]["preferred_term"],
                "ko_reference": by_term[sctid]["reference"],
                "n_samples": sum(c["count"] for c in cands),
                "n_distinct": n_distinct,
                "candidates": json.dumps(cands, ensure_ascii=False),
                "top_candidate": cands[0]["text"] if cands else "",
            })

    sidecar = {
        "system_prompt": system_prompt,
        "model_key": model_key,
        "samples": samples,
        "user_prompts": {sctid: user_prompts[sctid] for sctid in by_sctid},
    }
    prompts_path.write_text(json.dumps(sidecar, ensure_ascii=False),
                            encoding="utf-8")

    elapsed = time.monotonic() - t0
    return StageResult(
        stage=stage,
        ok=errors[0] == 0,
        outputs={"candidates_csv": out_path, "prompts_json": prompts_path},
        output_paths=[out_path],
        metrics={
            "n_concepts": float(len(by_sctid)),
            "n_calls": float(completed[0]),
            "n_errors": float(errors[0]),
            "n_multi_candidate": float(n_multi),
            "elapsed_seconds": elapsed,
        },
        message=(f"{len(by_sctid)} concepts × {samples} samples, "
                 f"{n_multi} with multiple distinct results, "
                 f"{errors[0]} errors, {elapsed:.0f}s"),
    )
