"""Batched reference-free acceptability judging with singleton agreement metrics."""
from __future__ import annotations

import csv
import json
import random
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pipelines.context import RunContext
from pipelines.functions import FunctionResult

from snomed_translation.acceptability import (
    DEFAULT_SYSTEM,
    _col,
    _dataset_path,
    _is_claude,
    _roles,
)


_RUBRIC = DEFAULT_SYSTEM.split("Output STRICT JSON only", 1)[0].rstrip()
DEFAULT_BATCH_SYSTEM = _RUBRIC + """

You will receive a JSON object with an `items` array. Judge every item independently.
Return STRICT JSON only, with exactly one result for every input `i`, in the same order:
{"items":[{"i":0,"label":"ACCEPTABLE|PARTIAL|WRONG","score":0.0,"reason":"short reason"}]}
Do not merge, skip, renumber, or compare items. Keep each reason under 18 words.
label: ACCEPTABLE = usable as-is; PARTIAL = mostly right but needs an edit; WRONG = wrong meaning or core concept.
score: confidence in clinical correctness (ACCEPTABLE >=0.85, PARTIAL 0.4-0.85, WRONG <0.4).
Judge only from your own knowledge. Do not look anything up."""


def _json_values(text: str):
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            yield value
        except (json.JSONDecodeError, TypeError):
            continue


def _parse_batch(text: str, expected: int) -> dict[int, dict[str, Any]]:
    """Return valid decisions keyed by the input's within-batch integer index."""
    items: Any = None
    for value in _json_values(text):
        candidate = value.get("items") if isinstance(value, dict) else value
        if isinstance(candidate, list):
            items = candidate
            break
    if not isinstance(items, list):
        return {}

    parsed: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        label = str(item.get("label", "")).strip().upper()
        if index < 0 or index >= expected or label not in {
            "ACCEPTABLE", "PARTIAL", "WRONG"
        }:
            continue
        try:
            score: float | str = float(item["score"])
        except (KeyError, TypeError, ValueError):
            score = ""
        parsed[index] = {
            "label": label,
            "score": score,
            "reason": str(item.get("reason", "")).strip()[:300],
        }
    return parsed


def _local_query(prompt: str, *, model: str, base_url: str, system: str,
                 max_tokens: int) -> str:
    body = json.dumps({
        "model": model,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    response = json.loads(urllib.request.urlopen(request, timeout=600).read())
    return str(response["choices"][0]["message"]["content"])


def _claude_query(prompt: str, *, model: str, system: str,
                  ctx: "RunContext | None" = None) -> str:
    from snomed_translation.generate import run_query
    return run_query(prompt, model=model, system=system, thinking=False, ctx=ctx)


def acceptability_judge_batched(ctx: RunContext, inputs: dict[str, Any],
                                params: dict[str, Any]) -> FunctionResult:
    t0 = time.monotonic()
    value = inputs.get("translations")
    path = _dataset_path(value)
    if not path or not Path(path).exists():
        return FunctionResult(ok=False, message="batched judge needs translations")
    model = str(params.get("model") or "").strip()
    if not model:
        return FunctionResult(ok=False, message="batched judge needs a model")

    batch_size = max(1, int(params.get("batch_size") or 10))
    concurrency = max(1, int(params.get("concurrency") or
                             (2 if _is_claude(model) else 4)))
    attempts = max(1, int(params.get("max_attempts") or 2))
    per_item_tokens = max(30, int(params.get("max_tokens_per_item") or 90))
    max_tokens_cap = max(256, int(params.get("max_tokens") or 8192))
    base_url = str(params.get("base_url") or "http://localhost:8086")
    system = str(params.get("system") or DEFAULT_BATCH_SYSTEM)
    sample_size = max(0, int(params.get("sample_size") or 0))
    seed = int(params.get("seed") or 20260714)

    roles = _roles(value)
    id_col = _col(params, roles, "id_col", "sctid", "sctid")
    en_col = _col(params, roles, "en_col", "en", "en")
    ko_col = _col(params, roles, "ko_col", "target", "translation")
    reference_col = str(params.get("reference_label_col") or "judge_label")

    with Path(path).open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        has_reference = reference_col in (reader.fieldnames or [])
        rows = [row for row in reader
                if (row.get(en_col) or "").strip() and
                (row.get(ko_col) or "").strip()]
    if sample_size and sample_size < len(rows):
        chosen = sorted(random.Random(seed).sample(range(len(rows)), sample_size))
        rows = [rows[index] for index in chosen]
    if not rows:
        return FunctionResult(ok=False, message="batched judge found no usable rows")

    batches = [rows[start:start + batch_size]
               for start in range(0, len(rows), batch_size)]
    batch_results: list[list[dict[str, Any]] | None] = [None] * len(batches)

    def judge_batch(batch_index: int, batch: list[dict[str, str]]):
        payload = {"items": [
            {"i": index, "english": row[en_col].strip(),
             "korean": row[ko_col].strip()}
            for index, row in enumerate(batch)
        ]}
        prompt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        parsed: dict[int, dict[str, Any]] = {}
        raw = ""
        used_attempts = 0
        for used_attempts in range(1, attempts + 1):
            try:
                if _is_claude(model):
                    raw = _claude_query(prompt, model=model, system=system, ctx=ctx)
                else:
                    token_limit = min(max_tokens_cap,
                                      per_item_tokens * len(batch) + 100)
                    raw = _local_query(prompt, model=model, base_url=base_url,
                                       system=system, max_tokens=token_limit)
                parsed = _parse_batch(raw, len(batch))
            except Exception as exc:
                raw = f"judge error: {exc}"
                parsed = {}
            if len(parsed) == len(batch):
                break

        output: list[dict[str, Any]] = []
        for index, row in enumerate(batch):
            decision = parsed.get(index, {
                "label": "?", "score": "", "reason": raw.strip()[:200]
            })
            item = {
                id_col: (row.get(id_col) or "").strip(),
                "english": row[en_col].strip(),
                "korean": row[ko_col].strip(),
                "judge_label": decision["label"],
                "judge_score": decision["score"],
                "judge_reason": decision["reason"],
                "batch_index": batch_index,
                "batch_item_index": index,
            }
            if has_reference:
                item["reference_label"] = (
                    row.get(reference_col) or ""
                ).strip().upper()
            output.append(item)
        return output, used_attempts - 1, len(parsed) != len(batch)

    retries = 0
    failed_calls = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(judge_batch, index, batch): index
            for index, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            index = futures[future]
            output, batch_retries, failed = future.result()
            batch_results[index] = output
            retries += batch_retries
            failed_calls += int(failed)

    results = [item for batch in batch_results if batch for item in batch]
    output_path = Path(ctx.log_dir) / f"acceptability_batched_n{batch_size}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    elapsed = time.monotonic() - t0
    n = len(results)
    distribution = {
        label: sum(row["judge_label"] == label for row in results)
        for label in ("ACCEPTABLE", "PARTIAL", "WRONG")
    }
    parse_fail = sum(row["judge_label"] == "?" for row in results)
    parsed = n - parse_fail
    model_attempts = len(batches) + retries
    metrics: dict[str, float] = {
        "n_judged": float(n),
        "n_parsed": float(parsed),
        "n_calls": float(len(batches)),
        "n_model_attempts": float(model_attempts),
        "batch_size": float(batch_size),
        "call_reduction_pct": round(100.0 * (1.0 - len(batches) / n), 3),
        "effective_call_reduction_pct": round(
            100.0 * (1.0 - model_attempts / n), 3
        ),
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(n / elapsed, 3) if elapsed else 0.0,
        "parsed_throughput_rps": round(parsed / elapsed, 3) if elapsed else 0.0,
        "calls_per_second": round(len(batches) / elapsed, 3) if elapsed else 0.0,
        "n_retries": float(retries),
        "failed_batch_calls": float(failed_calls),
        "judge_parse_fail": float(parse_fail),
        "judge_parse_fail_pct": round(100.0 * parse_fail / n, 3),
        "judge_parse_success_pct": round(100.0 * parsed / n, 3),
        "judged_acceptable": float(distribution["ACCEPTABLE"]),
        "judged_partial": float(distribution["PARTIAL"]),
        "judged_wrong": float(distribution["WRONG"]),
        "model_is_claude": float(_is_claude(model)),
    }
    if has_reference:
        paired = [row for row in results
                  if row.get("reference_label") in {
                      "ACCEPTABLE", "PARTIAL", "WRONG"
                  } and row["judge_label"] != "?"]
        if paired:
            three_way = sum(row["judge_label"] == row["reference_label"]
                            for row in paired)
            binary = sum(
                (row["judge_label"] == "ACCEPTABLE") ==
                (row["reference_label"] == "ACCEPTABLE")
                for row in paired
            )
            metrics.update({
                "n_vs_reference": float(len(paired)),
                "agreement_3way_pct": round(100.0 * three_way / len(paired), 3),
                "agreement_binary_pct": round(100.0 * binary / len(paired), 3),
            })

    return FunctionResult(
        ok=True,
        outputs={"judgements": str(output_path)},
        metrics=metrics,
        message=(f"batched judge {n} items in {len(batches)} calls "
                 f"(N={batch_size}; A/P/W={distribution['ACCEPTABLE']}/"
                 f"{distribution['PARTIAL']}/{distribution['WRONG']}; "
                 f"parse_fail={parse_fail})"),
    )
