from __future__ import annotations

import csv
from pathlib import Path

from pipelines.context import RunContext
from snomed_translation import evidence_analysis as E


def _write(path: Path, fields: list[str], rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_semantic_partial_credit_tracks_large_and_sme_metrics(tmp_path, monkeypatch):
    scores = _write(tmp_path / "scores.csv",
                    ["sctid", "exact", "sim_ko", "sim_en", "rr_en"], [
        {"sctid": "1", "exact": 1, "sim_ko": 1, "sim_en": .8, "rr_en": 1},
        {"sctid": "2", "exact": 0, "sim_ko": .9, "sim_en": .7, "rr_en": .8},
        {"sctid": "3", "exact": 0, "sim_ko": .5, "sim_en": .6, "rr_en": .7},
    ])
    sme = _write(tmp_path / "sme.csv",
                 ["sctid", "english_term", "pipeline_translation_ko",
                  "sme_rating", "sme_corrected_ko"], [
        {"sctid": "a", "english_term": "A", "pipeline_translation_ko": "가",
         "sme_rating": "ACCEPTABLE", "sme_corrected_ko": ""},
        {"sctid": "b", "english_term": "B", "pipeline_translation_ko": "나",
         "sme_rating": "WRONG", "sme_corrected_ko": "다"},
    ])
    monkeypatch.setattr(E, "_embed_similarity", lambda left, right: [.95, .4])
    result = E.semantic_partial_credit_calibration(
        RunContext(run_id="t", log_dir=tmp_path / "run"),
        {"scores": str(scores), "sme_labels": str(sme)}, {"threshold": .784})
    assert result.ok
    assert result.metrics["large_heuristic_understatement_pct"] == 100 / 3
    assert result.metrics["sme_threshold_accuracy_pct"] == 100


def test_register_feedback_detects_mixed_direction(tmp_path):
    sme = _write(tmp_path / "sme.csv",
                 ["sctid", "english_term", "pipeline_translation_ko",
                  "sme_rating", "sme_corrected_ko", "sonnet_label", "sme_notes"], [
        {"sctid": "1", "english_term": "left limb",
         "pipeline_translation_ko": "좌측 하지 검사", "sme_rating": "PARTIAL",
         "sme_corrected_ko": "왼쪽 다리 검사", "sonnet_label": "ACCEPTABLE"},
        {"sctid": "2", "english_term": "lumbar spine",
         "pipeline_translation_ko": "허리뼈 검사", "sme_rating": "PARTIAL",
         "sme_corrected_ko": "요추 검사", "sonnet_label": "PARTIAL"},
    ])
    result = E.register_feedback_analysis(
        RunContext(run_id="t", log_dir=tmp_path / "run"),
        {"sme_labels": str(sme)}, {})
    assert result.ok
    assert result.metrics["mixed_direction"] == 1
    assert result.metrics["sino_to_native"] == 2
    assert result.metrics["native_to_sino"] == 1


def test_transliteration_calibration_reports_missed_positive(tmp_path):
    audit = _write(tmp_path / "audit.csv",
                   ["sctid", "english", "korean", "is_transliteration_error"], [
        {"sctid": "1", "english": "Tenogram", "korean": "테노그램",
         "is_transliteration_error": 1},
        {"sctid": "2", "english": "Cineswallow", "korean": "시네스왈로",
         "is_transliteration_error": 1},
        {"sctid": "3", "english": "Fluoroscopy skull", "korean": "머리뼈 투시",
         "is_transliteration_error": 0},
    ])
    result = E.transliteration_recall_calibration(
        RunContext(run_id="t", log_dir=tmp_path / "run"),
        {"audit": str(audit)}, {"current_threshold": .70})
    assert result.ok
    assert result.metrics["positive_n"] == 2
    assert result.metrics["current_false_negatives"] >= 1
