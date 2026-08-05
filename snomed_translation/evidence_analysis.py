"""Tracked calibration analyses for SME evidence and targeted error signals.

These runners turn analyses that previously lived in notes or one-off scripts
into reusable flow blocks.  They deliberately keep the human SME rating as the
independent outcome and write row-level audit CSVs alongside headline metrics.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from pipelines.context import RunContext
from pipelines.functions import FunctionResult


def _dataset_path(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("_primary", "dataset", "rows", "path"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


def _read_rows(value: Any) -> tuple[str | None, list[dict[str, str]]]:
    path = _dataset_path(value)
    if not path or not Path(path).exists():
        return path, []
    with Path(path).open(encoding="utf-8") as handle:
        return path, list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _auc(scores: Iterable[float], labels: Iterable[int]) -> float:
    """Mann-Whitney AUC; labels=1 means the higher-score class."""
    pairs = [(float(score), int(label)) for score, label in zip(scores, labels)
             if math.isfinite(float(score))]
    pos = [score for score, label in pairs if label == 1]
    neg = [score for score, label in pairs if label == 0]
    if not pos or not neg:
        return float("nan")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0
               for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def _pct(numerator: int | float, denominator: int | float) -> float:
    return 100.0 * float(numerator) / float(denominator) if denominator else 0.0


def _effective_sme_reference(row: dict[str, str]) -> str:
    """SME correction when supplied; accepted candidate otherwise.

    An ACCEPTABLE row with no correction is itself a human-authorised valid
    rendering.  Non-acceptable rows require a correction to enter the semantic
    calibration set.
    """
    corrected = (row.get("sme_corrected_ko") or "").strip()
    if corrected:
        return corrected
    if (row.get("sme_rating") or "").strip().upper() == "ACCEPTABLE":
        return (row.get("pipeline_translation_ko") or "").strip()
    return ""


def _embed_similarity(left: list[str], right: list[str]) -> list[float]:
    from agent.qdrant_store import BGEM3Embedder

    embedder = BGEM3Embedder()

    def encode(texts: list[str]) -> np.ndarray:
        dense, _ = embedder.encode_documents(texts)
        arr = np.asarray(dense, dtype=np.float32)
        return arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)

    a = encode(left)
    b = encode(right)
    return [float(value) for value in np.sum(a * b, axis=1)]


def semantic_partial_credit_calibration(
    ctx: RunContext, inputs: dict[str, Any], params: dict[str, Any]
) -> FunctionResult:
    """Reproduce the large-set heuristic and validate it against SME ratings."""
    scores_path, score_rows = _read_rows(inputs.get("scores"))
    sme_path, sme_rows = _read_rows(inputs.get("sme_labels"))
    if not score_rows:
        return FunctionResult(ok=False, message=f"no score rows in {scores_path}")
    if not sme_rows:
        return FunctionResult(ok=False, message=f"no SME rows in {sme_path}")

    threshold = float(params.get("threshold") or 0.784)
    nonexact = [row for row in score_rows if int(float(row.get("exact") or 0)) == 0]
    above = [row for row in nonexact
             if float(row.get("sim_ko") or "nan") >= threshold]
    direct_auc = _auc(
        [float(row.get("sim_en") or "nan") for row in nonexact],
        [int(float(row.get("sim_ko") or 0) >= threshold) for row in nonexact],
    )
    rank_auc = _auc(
        [float(row.get("rr_en") or "nan") for row in nonexact],
        [int(float(row.get("sim_ko") or 0) >= threshold) for row in nonexact],
    )

    calibration: list[dict[str, Any]] = []
    left: list[str] = []
    right: list[str] = []
    source_rows: list[dict[str, str]] = []
    for row in sme_rows:
        candidate = (row.get("pipeline_translation_ko") or "").strip()
        reference = _effective_sme_reference(row)
        if candidate and reference:
            left.append(candidate)
            right.append(reference)
            source_rows.append(row)
    if not source_rows:
        return FunctionResult(ok=False, message="no SME rows have usable references")

    try:
        similarities = _embed_similarity(left, right)
    except Exception as exc:
        return FunctionResult(ok=False, message=f"SME embedding failed: {exc}")

    labels: list[int] = []
    predictions: list[int] = []
    for row, candidate, reference, similarity in zip(
        source_rows, left, right, similarities
    ):
        acceptable = int((row.get("sme_rating") or "").upper() == "ACCEPTABLE")
        predicted = int(similarity >= threshold)
        labels.append(acceptable)
        predictions.append(predicted)
        calibration.append({
            "sctid": row.get("sctid", ""),
            "english_term": row.get("english_term", ""),
            "candidate_ko": candidate,
            "effective_sme_reference_ko": reference,
            "sme_rating": row.get("sme_rating", ""),
            "ko_similarity": round(similarity, 6),
            "above_threshold": predicted,
            "threshold_correct": int(predicted == acceptable),
        })

    tp = sum(p == 1 and y == 1 for p, y in zip(predictions, labels))
    tn = sum(p == 0 and y == 0 for p, y in zip(predictions, labels))
    fp = sum(p == 1 and y == 0 for p, y in zip(predictions, labels))
    fn = sum(p == 0 and y == 1 for p, y in zip(predictions, labels))
    best_threshold, best = _best_threshold(similarities, labels)
    output = Path(ctx.log_dir) / "semantic_partial_credit_sme_audit.csv"
    _write_rows(output, calibration)

    metrics = {
        "large_n": float(len(score_rows)),
        "large_nonexact_n": float(len(nonexact)),
        "large_nonexact_above_threshold_n": float(len(above)),
        "large_nonexact_above_threshold_pct": _pct(len(above), len(nonexact)),
        "large_heuristic_understatement_pct": _pct(len(above), len(score_rows)),
        "direct_en_ko_auc_vs_ko_heuristic": direct_auc,
        "rank_normalized_auc_vs_ko_heuristic": rank_auc,
        "sme_n": float(len(labels)),
        "sme_ko_similarity_auc": _auc(similarities, labels),
        "sme_threshold_accuracy_pct": _pct(tp + tn, len(labels)),
        "sme_threshold_sensitivity_pct": _pct(tp, tp + fn),
        "sme_threshold_specificity_pct": _pct(tn, tn + fp),
        "sme_acceptable_below_threshold": float(fn),
        "sme_nonacceptable_above_threshold": float(fp),
        "threshold": threshold,
        "sme_best_threshold": float(best_threshold),
        "sme_best_balanced_accuracy_pct": 100.0 * best["balanced"],
        "sme_best_precision_pct": 100.0 * best["precision"],
        "sme_best_recall_pct": 100.0 * best["recall"],
        "sme_best_specificity_pct": 100.0 * best["specificity"],
    }
    return FunctionResult(
        ok=True,
        outputs={"audit": str(output)},
        metrics=metrics,
        message=(f"large n={len(score_rows)} heuristic penalty="
                 f"{metrics['large_heuristic_understatement_pct']:.1f}%; "
                 f"SME n={len(labels)} AUC={metrics['sme_ko_similarity_auc']:.3f} "
                 f"threshold accuracy={metrics['sme_threshold_accuracy_pct']:.1f}%"),
    )


# (Sino-Korean form, native-Korean form, anatomical category).  Direction is
# inferred from candidate -> SME effective rendering; both directions matter.
_REGISTER_PAIRS = [
    ("상완", "위팔", "arm_segment"),
    ("전완", "아래팔", "forearm_segment"),
    ("하지", "다리", "whole_lower_limb"),
    ("상지", "팔", "whole_upper_limb"),
    ("좌측", "왼쪽", "laterality"),
    ("우측", "오른쪽", "laterality"),
    ("양측", "양쪽", "bilateral"),
    ("고관절", "엉덩관절", "joint"),
    ("종골", "발꿈치뼈", "bone"),
    ("경골", "정강뼈", "bone"),
    ("비골", "종아리뼈", "bone"),
    ("요추", "허리뼈", "spine"),
    ("경추", "목뼈", "spine"),
    ("흉추", "등뼈", "spine"),
    ("견갑골", "어깨뼈", "bone"),
    ("대퇴", "넓적다리", "thigh"),
]

# These edits can look like register changes in aggregate, but actually repair
# anatomical extent while staying in native Korean.  Keep them out of the
# Sino↔native direction totals.
_SCOPE_PAIRS = [
    ("위팔", "팔", "upper_arm_to_whole_upper_limb"),
    ("아래 다리", "다리", "lower_leg_to_whole_lower_limb"),
]


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[^가-힣]+", text) if token}


def register_feedback_analysis(
    ctx: RunContext, inputs: dict[str, Any], params: dict[str, Any]
) -> FunctionResult:
    """Audit whether SME register edits have one global direction."""
    path, rows = _read_rows(inputs.get("sme_labels"))
    if not rows:
        return FunctionResult(ok=False, message=f"no SME rows in {path}")

    audit: list[dict[str, Any]] = []
    sino_to_native = 0
    native_to_sino = 0
    ambiguous_or_parallel = 0
    scope_corrections = 0
    register_rows: set[str] = set()
    sonnet_overaccept = 0
    sonnet_compared = 0
    for row in rows:
        candidate = (row.get("pipeline_translation_ko") or "").strip()
        reference = _effective_sme_reference(row)
        if not candidate or not reference or candidate == reference:
            continue
        candidate_tokens = _tokens(candidate)
        reference_tokens = _tokens(reference)
        row_has_shift = False
        for sino, native, category in _REGISTER_PAIRS:
            direction = ""
            # A correction such as "목뼈/등뼈/허리뼈 OR 경추/흉추/요추"
            # permits both coherent registers. It is evidence for parallelism,
            # not for either global direction.
            if sino in reference_tokens and native in reference_tokens:
                if sino in candidate_tokens or native in candidate_tokens:
                    ambiguous_or_parallel += 1
                    row_has_shift = True
                    audit.append({
                        "sctid": row.get("sctid", ""),
                        "english_term": row.get("english_term", ""),
                        "category": category,
                        "direction": "parallel_alternatives_allowed",
                        "candidate_ko": candidate,
                        "effective_sme_reference_ko": reference,
                        "sme_rating": row.get("sme_rating", ""),
                        "sonnet_label": row.get("sonnet_label", ""),
                        "sme_notes": row.get("sme_notes", ""),
                    })
                continue
            if sino in candidate_tokens and native in reference_tokens:
                direction = "sino_to_native"
                sino_to_native += 1
            elif native in candidate_tokens and sino in reference_tokens:
                direction = "native_to_sino"
                native_to_sino += 1
            if not direction:
                continue
            row_has_shift = True
            audit.append({
                "sctid": row.get("sctid", ""),
                "english_term": row.get("english_term", ""),
                "category": category,
                "direction": direction,
                "candidate_ko": candidate,
                "effective_sme_reference_ko": reference,
                "sme_rating": row.get("sme_rating", ""),
                "sonnet_label": row.get("sonnet_label", ""),
                "sme_notes": row.get("sme_notes", ""),
            })
        for narrow, whole, category in _SCOPE_PAIRS:
            if narrow in candidate and whole in reference and narrow not in reference:
                row_has_shift = True
                scope_corrections += 1
                audit.append({
                    "sctid": row.get("sctid", ""),
                    "english_term": row.get("english_term", ""),
                    "category": category,
                    "direction": "anatomical_scope_correction",
                    "candidate_ko": candidate,
                    "effective_sme_reference_ko": reference,
                    "sme_rating": row.get("sme_rating", ""),
                    "sonnet_label": row.get("sonnet_label", ""),
                    "sme_notes": row.get("sme_notes", ""),
                })
        if row_has_shift:
            sid = row.get("sctid", "")
            register_rows.add(sid)
            sonnet = (row.get("sonnet_label") or "").upper()
            sme = (row.get("sme_rating") or "").upper()
            if sonnet:
                sonnet_compared += 1
                if sonnet == "ACCEPTABLE" and sme != "ACCEPTABLE":
                    sonnet_overaccept += 1

    output = Path(ctx.log_dir) / "register_feedback_audit.csv"
    _write_rows(output, audit)
    total_shifts = sino_to_native + native_to_sino
    metrics = {
        "sme_n": float(len(rows)),
        "register_shift_rows": float(len(register_rows)),
        "register_shift_instances": float(total_shifts),
        "sino_to_native": float(sino_to_native),
        "native_to_sino": float(native_to_sino),
        "parallel_alternatives_allowed": float(ambiguous_or_parallel),
        "anatomical_scope_corrections": float(scope_corrections),
        "sino_to_native_pct": _pct(sino_to_native, total_shifts),
        "native_to_sino_pct": _pct(native_to_sino, total_shifts),
        "sonnet_compared_register_rows": float(sonnet_compared),
        "sonnet_overaccept_register_rows": float(sonnet_overaccept),
        "sonnet_overaccept_register_pct": _pct(sonnet_overaccept, sonnet_compared),
        "mixed_direction": float(bool(sino_to_native and native_to_sino)),
    }
    return FunctionResult(
        ok=True,
        outputs={"audit": str(output)},
        metrics=metrics,
        message=(f"{len(register_rows)} SME rows contain mapped register shifts: "
                 f"Sino->native={sino_to_native}, native->Sino={native_to_sino}, "
                 f"scope={scope_corrections}, parallel={ambiguous_or_parallel}; "
                 f"Sonnet overaccepted {sonnet_overaccept}/{sonnet_compared}"),
    )


def _best_threshold(scores: list[float], labels: list[int]) -> tuple[float, dict[str, float]]:
    candidates = sorted(set([round(x, 3) for x in scores] +
                            [round(x, 2) for x in np.arange(0.40, 0.91, 0.01)]))
    best: tuple[tuple[float, float, float], float, dict[str, float]] | None = None
    for threshold in candidates:
        pred = [int(score >= threshold) for score in scores]
        tp = sum(p and y for p, y in zip(pred, labels))
        tn = sum((not p) and (not y) for p, y in zip(pred, labels))
        fp = sum(p and (not y) for p, y in zip(pred, labels))
        fn = sum((not p) and y for p, y in zip(pred, labels))
        recall = tp / (tp + fn) if tp + fn else 0.0
        specificity = tn / (tn + fp) if tn + fp else 0.0
        precision = tp / (tp + fp) if tp + fp else 0.0
        balanced = (recall + specificity) / 2.0
        stats = {"recall": recall, "specificity": specificity,
                 "precision": precision, "balanced": balanced,
                 "tp": float(tp), "tn": float(tn),
                 "fp": float(fp), "fn": float(fn)}
        key = (balanced, precision, threshold)
        if best is None or key > best[0]:
            best = (key, threshold, stats)
    assert best is not None
    return best[1], best[2]


def transliteration_recall_calibration(
    ctx: RunContext, inputs: dict[str, Any], params: dict[str, Any]
) -> FunctionResult:
    """Measure precision/recall on an explicitly labelled observed audit set."""
    from snomed_translation.transliteration import phonetic_echo

    audit_path, rows = _read_rows(inputs.get("audit"))
    if not rows:
        return FunctionResult(ok=False, message=f"no audit rows in {audit_path}")
    current = float(params.get("current_threshold") or 0.70)
    scored: list[dict[str, Any]] = []
    scores: list[float] = []
    labels: list[int] = []
    for row in rows:
        english = (row.get("english") or "").strip()
        korean = (row.get("korean") or "").strip()
        label = int(row.get("is_transliteration_error") or 0)
        score = phonetic_echo(english, korean)
        scores.append(score)
        labels.append(label)
        scored.append({**row, "echo": round(score, 6),
                       "current_flag": int(score >= current)})

    best_threshold, best = _best_threshold(scores, labels)
    current_pred = [int(score >= current) for score in scores]
    current_tp = sum(p and y for p, y in zip(current_pred, labels))
    current_fp = sum(p and not y for p, y in zip(current_pred, labels))
    current_fn = sum(not p and y for p, y in zip(current_pred, labels))
    current_tn = sum(not p and not y for p, y in zip(current_pred, labels))

    _, frontier = _read_rows(inputs.get("frontier"))
    frontier_current = 0
    frontier_best = 0
    if frontier:
        for row in frontier:
            english = (row.get("preferred_term") or row.get("english") or
                       row.get("english_term") or "").strip()
            korean = (row.get("translation") or row.get("korean") or
                      row.get("pipeline_translation_ko") or "").strip()
            if not english or not korean:
                continue
            score = phonetic_echo(english, korean)
            frontier_current += int(score >= current)
            frontier_best += int(score >= best_threshold)

    output = Path(ctx.log_dir) / "transliteration_recall_audit.csv"
    _write_rows(output, scored)
    positive_n = sum(labels)
    negative_n = len(labels) - positive_n
    metrics = {
        "audit_n": float(len(labels)),
        "positive_n": float(positive_n),
        "negative_n": float(negative_n),
        "current_threshold": current,
        "current_precision_pct": _pct(current_tp, current_tp + current_fp),
        "current_recall_pct": _pct(current_tp, current_tp + current_fn),
        "current_specificity_pct": _pct(current_tn, current_tn + current_fp),
        "current_false_negatives": float(current_fn),
        "current_false_positives": float(current_fp),
        "best_threshold": float(best_threshold),
        "best_precision_pct": 100.0 * best["precision"],
        "best_recall_pct": 100.0 * best["recall"],
        "best_specificity_pct": 100.0 * best["specificity"],
        "best_balanced_accuracy_pct": 100.0 * best["balanced"],
        "frontier_n": float(len(frontier)),
        "frontier_current_threshold_flags": float(frontier_current),
        "frontier_best_threshold_flags": float(frontier_best),
    }
    return FunctionResult(
        ok=True,
        outputs={"audit": str(output)},
        metrics=metrics,
        message=(f"audit n={len(labels)} positives={positive_n}; threshold "
                 f"{current:.2f} recall={metrics['current_recall_pct']:.1f}% "
                 f"precision={metrics['current_precision_pct']:.1f}%; best "
                 f"threshold={best_threshold:.3f}"),
    )
