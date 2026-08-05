"""Metric-triggered correction round for EN->KO SNOMED translations."""
from __future__ import annotations

import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import sacrebleu

from pipelines.context import RunContext
from pipelines.llm_accounting import record_completion
from pipelines.functions import FunctionResult
from snomed_translation.acceptability import _is_claude


DEFAULT_SYSTEM = """You are a senior Korean SNOMED CT terminologist correcting a machine translation.
Preserve the complete clinical meaning and every modifier. Prefer established Korean medical terminology; do not merely spell the English pronunciation in Hangul when an established Korean term exists. Korean is head-final, so attach modifiers unambiguously and place the action or modality last.

You receive the English source, current Korean translation, and automated review evidence. Correct only the defects supported by that evidence. Return STRICT JSON only:
{"translation": "<corrected Korean term>", "reason": "<one short sentence>"}
"""


def _dataset_path(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("_primary", "dataset", "rows", "path", "flags", "judgements"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


def _roles(value: Any) -> dict[str, str]:
    return value.get("roles", {}) if isinstance(value, dict) else {}


def _read_index(value: Any, id_col: str) -> dict[str, dict]:
    path = _dataset_path(value)
    if not path or not Path(path).exists():
        return {}
    with Path(path).open(encoding="utf-8") as handle:
        return {(row.get(id_col) or "").strip(): row for row in csv.DictReader(handle)}


def _parse(text: str) -> tuple[str, str]:
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            value = json.loads(match.group(0))
            translation = str(value.get("translation") or "").strip()
            if translation:
                return translation, str(value.get("reason") or "")[:300]
        except Exception:
            pass
    return "", text.strip()[:200]


def _correct_local(prompt: str, *, model: str, base_url: str,
                   system: str, max_tokens: int,
                   ctx: "RunContext | None" = None) -> tuple[str, str]:
    import urllib.request
    body = json.dumps({
        "model": model, "temperature": 0.0, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
    }).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    response = json.loads(urllib.request.urlopen(request, timeout=180).read())
    record_completion(ctx, model=model, usage=response.get("usage"))
    return _parse(response["choices"][0]["message"]["content"])


def _correct_claude(prompt: str, *, model: str, system: str) -> tuple[str, str]:
    from snomed_translation.generate import run_query
    return _parse(run_query(prompt, model=model, system=system, thinking=False))


def correction_round(ctx: RunContext, inputs: dict[str, Any],
                     params: dict[str, Any]) -> FunctionResult:
    """Correct rows flagged by transliteration OR rejected by the LLM judge."""
    source_path = _dataset_path(inputs.get("translations"))
    if not source_path or not Path(source_path).exists():
        return FunctionResult(ok=False, message="correction_round: no translations dataset wired")
    model = str(params.get("model") or "").strip()
    if not model:
        return FunctionResult(ok=False, message="correction_round needs a `model`")

    roles = _roles(inputs.get("translations"))
    id_col = str(params.get("id_col") or roles.get("sctid") or "sctid")
    en_col = str(params.get("en_col") or roles.get("en") or "en")
    ko_col = str(params.get("ko_col") or roles.get("target") or "translation")
    flags = _read_index(inputs.get("transliteration_flags"), id_col)
    judgements = _read_index(inputs.get("judgements"), id_col)
    score_threshold = float(params.get("judge_score_threshold") or 0.85)
    system = str(params.get("system") or DEFAULT_SYSTEM)
    base_url = str(params.get("base_url") or "http://localhost:8086")
    max_tokens = int(params.get("max_tokens") or 260)
    concurrency = int(params.get("concurrency") or (4 if _is_claude(model) else 16))
    limit = int(params.get("limit") or 0)
    reference_col = str(params.get("reference_col") or "sme_corrected_ko")
    label_col = str(params.get("label_col") or "sme_rating")

    with Path(source_path).open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if limit:
        rows = rows[:limit]
    if not rows or en_col not in fieldnames or ko_col not in fieldnames:
        return FunctionResult(ok=False, message=(
            f"correction_round: unusable dataset (en_col={en_col!r}, ko_col={ko_col!r})"))

    def evidence(row: dict) -> tuple[bool, str, str]:
        key = (row.get(id_col) or "").strip()
        flag, judge = flags.get(key, {}), judgements.get(key, {})
        translit = str(flag.get("flag") or "0").strip() in ("1", "true", "True")
        label = str(judge.get("judge_label") or "").upper()
        try:
            low_score = float(judge.get("judge_score")) < score_threshold
        except (TypeError, ValueError):
            low_score = False
        judge_trigger = label in ("PARTIAL", "WRONG") or low_score
        trigger = translit or judge_trigger
        review = (f"transliteration_flag={int(translit)}; phonetic_echo={flag.get('echo', '')}; "
                  f"judge_label={label}; judge_score={judge.get('judge_score', '')}; "
                  f"judge_reason={judge.get('judge_reason', '')}")
        kinds = "+".join(x for x, yes in (("transliteration", translit),
                                             ("judge", judge_trigger)) if yes)
        return trigger, review, kinds

    targets = [(index, row, evidence(row)) for index, row in enumerate(rows)]
    targets = [item for item in targets if item[2][0]]

    def one(row: dict, review: str) -> tuple[str, str]:
        prompt = (f"english: {(row.get(en_col) or '').strip()}\n"
                  f"current_korean: {(row.get(ko_col) or '').strip()}\n"
                  f"automated_review: {review}")
        try:
            if _is_claude(model):
                return _correct_claude(prompt, model=model, system=system)
            return _correct_local(prompt, model=model, base_url=base_url,
                                  system=system, max_tokens=max_tokens, ctx=ctx)
        except Exception as exc:
            return "", f"correction error: {exc}"[:200]

    corrections: dict[int, tuple[str, str, str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = {executor.submit(one, row, ev[1]): (index, ev[2])
                   for index, row, ev in targets}
        for future in as_completed(futures):
            index, kinds = futures[future]
            translation, reason = future.result()
            corrections[index] = (translation, reason, kinds)

    output_rows: list[dict] = []
    parse_fail = 0
    changed = 0
    for index, row in enumerate(rows):
        out = dict(row)
        original = (row.get(ko_col) or "").strip()
        translation, reason, kinds = corrections.get(index, ("", "", ""))
        if index in corrections and not translation:
            parse_fail += 1
        corrected = translation or original
        changed += int(corrected != original)
        out["correction_original_ko"] = original
        out[ko_col] = corrected
        out["correction_trigger"] = kinds
        out["correction_applied"] = int(corrected != original)
        out["correction_reason"] = reason
        output_rows.append(out)

    output = Path(ctx.log_dir) / "corrected_translations.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    extras = ["correction_original_ko", "correction_trigger",
              "correction_applied", "correction_reason"]
    output_fields = fieldnames + [name for name in extras if name not in fieldnames]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(output_rows)

    metrics = {"n_rows": float(len(rows)), "n_triggered": float(len(targets)),
               "n_changed": float(changed), "correction_parse_fail": float(parse_fail)}
    comparable = []
    for row in output_rows:
        reference = (row.get(reference_col) or "").strip()
        if not reference and (row.get(label_col) or "").strip().upper() == "ACCEPTABLE":
            reference = (row.get("correction_original_ko") or "").strip()
        if reference:
            comparable.append(((row.get("correction_original_ko") or "").strip(),
                               (row.get(ko_col) or "").strip(), reference))
    if comparable:
        metrics["n_vs_sme_reference"] = float(len(comparable))
        baseline_exact = (100.0 * sum(original == reference
                                      for original, _, reference in comparable)
                          / len(comparable))
        corrected_exact = (100.0 * sum(candidate == reference
                                       for _, candidate, reference in comparable)
                           / len(comparable))
        baseline_chrf = sum(
            sacrebleu.sentence_chrf(original, [reference]).score
            for original, _, reference in comparable) / len(comparable)
        corrected_chrf = sum(
            sacrebleu.sentence_chrf(candidate, [reference]).score
            for _, candidate, reference in comparable) / len(comparable)
        metrics["baseline_exact_vs_sme_pct"] = round(baseline_exact, 3)
        metrics["exact_vs_sme_pct"] = round(
            corrected_exact, 3)
        metrics["delta_exact_vs_sme_pct"] = round(corrected_exact - baseline_exact, 3)
        metrics["baseline_mean_chrf_vs_sme"] = round(baseline_chrf, 3)
        metrics["mean_chrf_vs_sme"] = round(corrected_chrf, 3)
        metrics["delta_mean_chrf_vs_sme"] = round(corrected_chrf - baseline_chrf, 3)

    return FunctionResult(ok=True, outputs={"translations": str(output)}, metrics=metrics,
                          message=f"corrected {changed}/{len(rows)} rows ({len(targets)} triggered)")
