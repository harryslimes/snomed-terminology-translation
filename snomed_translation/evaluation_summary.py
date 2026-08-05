"""Aggregate full-pool translation evaluation metrics into a run report."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from pipelines.context import RunContext
from pipelines.functions import FunctionResult

def _metrics(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, raw in value.items():
        try:
            out[str(key)] = float(raw)
        except (TypeError, ValueError):
            pass
    return out

def translation_evaluation_summary(ctx: RunContext, inputs: dict[str, Any],
                                   params: dict[str, Any]) -> FunctionResult:
    translation = _metrics(inputs.get("translation_metrics"))
    judge = _metrics(inputs.get("judge_metrics"))
    transliteration = _metrics(inputs.get("transliteration_metrics"))
    if not translation or not judge or not transliteration:
        return FunctionResult(ok=False, message="summary needs translation, judge, and transliteration metrics")
    translation_s = translation.get("elapsed_seconds", 0.0)
    judge_s = judge.get("elapsed_seconds", 0.0)
    transliteration_s = transliteration.get("elapsed_seconds", 0.0)
    total_s = translation_s + judge_s + transliteration_s
    rows = translation.get("n_translated", judge.get("n_judged", 0.0))
    metrics = {
        "n_translated": rows,
        "translation_errors": translation.get("n_errors", 0.0),
        "translation_seconds": round(translation_s, 3),
        "translation_throughput_rps": translation.get("throughput_rps", 0.0),
        "judge_seconds": round(judge_s, 3),
        "judge_throughput_rps": judge.get("throughput_rps", 0.0),
        "transliteration_seconds": round(transliteration_s, 3),
        "transliteration_throughput_rps": transliteration.get("throughput_rps", 0.0),
        "measured_stage_seconds": round(total_s, 3),
        "measured_stage_hours": round(total_s / 3600.0, 4),
        "end_to_end_throughput_rps": round(rows / total_s, 4) if total_s else 0.0,
        "judged_acceptable": judge.get("judged_acceptable", 0.0),
        "judged_partial": judge.get("judged_partial", 0.0),
        "judged_wrong": judge.get("judged_wrong", 0.0),
        "judge_parse_fail": judge.get("judge_parse_fail", 0.0),
        "transliteration_flags": transliteration.get("n_flagged", 0.0),
        "transliteration_flag_rate_pct": transliteration.get("flag_rate_pct", 0.0),
    }
    report = Path(ctx.log_dir) / "translation_evaluation_summary.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"metrics": metrics,
                                  "timing_definition": "sum of measured translate, transliteration, and judge stage runtimes; excludes datasource/style-guide/report overhead"},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    return FunctionResult(ok=True, outputs={"report": str(report)}, metrics=metrics,
                          message=f"{int(rows)} translated; measured stages {total_s:.1f}s")
