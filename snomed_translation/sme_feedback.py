"""SME-feedback analysis nodes (batch-2, 2026-08).

Two function nodes:

- ``contrast_fidelity_detect`` — deterministic, source-conditional detector
  for the top SME "Wrong" class: a contrast phrase (조영제 사용 / 조영제
  미사용) in the Korean output that the English source does not license, or
  a source contrast modifier dropped from the output. Sibling of
  ``transliteration_detect`` (same flag-CSV + metrics shape).

- ``sme_metric_separation`` — scores each SME-reviewed translation against
  the SME gold (multi-reference) with the candidate metrics GEPA could
  optimise (spacing-normalised exact, chrF, BGE-M3 cosine) and measures how
  well each separates the SME's Correct/Acceptable rows from Partial/Wrong.
  The SME's stated boundary (spacing + preferred-synonym differences
  acceptable; word-order differences not) is what a good metric must
  reproduce.
"""
from __future__ import annotations

import csv
import re
import time
from pathlib import Path
from typing import Any

import sacrebleu

from pipelines.context import RunContext
from pipelines.functions import FunctionResult

from snomed_translation.evidence_analysis import (  # shared helpers
    _auc,
    _best_threshold,
    _embed_similarity,
)
from snomed_translation.scoring import norm_text

WITH_RE = re.compile(r"\bwith contrast\b", re.IGNORECASE)
WITHOUT_RE = re.compile(r"\bwithout contrast\b", re.IGNORECASE)
ANY_CONTRAST_RE = re.compile(r"contrast", re.IGNORECASE)

KO_WITH = "조영제 사용"
KO_WITHOUT = "조영제 미사용"

ACCEPT_RATINGS = {"CORRECT", "ACCEPTABLE"}
REJECT_RATINGS = {"PARTIAL", "WRONG"}


def _dataset_path(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("path") or value.get("csv")
    if isinstance(value, str):
        return value
    return None


def _roles(value: Any) -> dict:
    if isinstance(value, dict):
        return value.get("roles") or {}
    return {}


def _col(params: dict, roles: dict, param_key: str, role_key: str,
         default: str) -> str:
    return str(params.get(param_key) or roles.get(role_key) or default)


# ---------------------------------------------------------------------------
# contrast_fidelity_detect
# ---------------------------------------------------------------------------


def contrast_issue(en: str, ko: str) -> str:
    """Deterministic contrast-fidelity verdict for one (source, output) pair.

    Returns "" (clean/ambiguous), "hallucinated", "wrong_polarity" or
    "dropped". Sources mentioning contrast outside the with/without modifier
    forms ("contrast procedure", "double contrast …") are treated as
    ambiguous and never flagged.
    """
    has_with = bool(WITH_RE.search(en))
    has_without = bool(WITHOUT_RE.search(en))
    if ANY_CONTRAST_RE.search(en) and not (has_with or has_without):
        return ""
    ko_without = KO_WITHOUT in ko
    ko_with = KO_WITH in ko
    if not (has_with or has_without):
        return "hallucinated" if "조영제" in ko else ""
    if has_with:
        if ko_without:
            return "wrong_polarity"
        return "" if ko_with else "dropped"
    if ko_with and not ko_without:
        return "wrong_polarity"
    return "" if ko_without else "dropped"


def contrast_fidelity_detect(ctx: RunContext, inputs: dict[str, Any],
                             params: dict[str, Any]) -> FunctionResult:
    """Flag contrast-phrase mismatches between source and output.

    Cases (deterministic):
      hallucinated  — source has NO occurrence of "contrast" at all, output
                      contains 조영제.
      wrong_polarity — source says "with contrast" but output has 조영제
                      미사용, or "without contrast" but output has 조영제
                      사용.
      dropped       — source says "with/without contrast" but the required
                      조영제 phrase is absent from the output.
    Sources that mention contrast in other constructions ("contrast
    procedure", "double contrast …") are skipped as ambiguous — the goal is
    high precision.
    """
    t0 = time.monotonic()
    tpath = _dataset_path(inputs.get("translations"))
    if not tpath or not Path(tpath).exists():
        return FunctionResult(
            ok=False, message="contrast_fidelity_detect: no `translations` dataset wired")
    roles = _roles(inputs.get("translations"))
    id_col = _col(params, roles, "id_col", "sctid", "sctid")
    en_col = _col(params, roles, "en_col", "en", "en")
    ko_col = _col(params, roles, "ko_col", "target", "translation")
    label_col = str(params.get("label_col") or "sme_rating")

    out_rows: list[dict] = []
    with Path(tpath).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        has_label = label_col in (reader.fieldnames or [])
        for r in reader:
            en, ko = (r.get(en_col) or "").strip(), (r.get(ko_col) or "").strip()
            if not en or not ko:
                continue
            issue = contrast_issue(en, ko)
            row = {id_col: (r.get(id_col) or "").strip(), "english": en,
                   "korean": ko, "issue": issue, "flag": int(bool(issue))}
            if has_label:
                row["sme_rating"] = (r.get(label_col) or "").strip().upper()
            out_rows.append(row)

    if not out_rows:
        return FunctionResult(
            ok=False, message=f"contrast_fidelity_detect: no usable rows in {tpath} "
                              f"(en_col={en_col!r}, ko_col={ko_col!r})")

    out = Path(ctx.log_dir) / "contrast_fidelity_flags.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    n = len(out_rows)
    flagged = [r for r in out_rows if r["flag"]]
    by_issue: dict[str, int] = {}
    for r in flagged:
        by_issue[r["issue"]] = by_issue.get(r["issue"], 0) + 1
    elapsed = time.monotonic() - t0
    metrics = {"n_rows": float(n), "n_flagged": float(len(flagged)),
               "flag_rate_pct": round(100.0 * len(flagged) / n, 3),
               "elapsed_seconds": round(elapsed, 3)}
    for issue, count in by_issue.items():
        metrics[f"n_{issue}"] = float(count)
    if out_rows and "sme_rating" in out_rows[0]:
        fp = sum(1 for r in flagged if r["sme_rating"] in ACCEPT_RATINGS)
        tp = sum(1 for r in flagged if r["sme_rating"] in REJECT_RATINGS)
        metrics["flagged_sme_acceptable"] = float(fp)
        metrics["flagged_sme_nonacceptable"] = float(tp)
        metrics["flag_precision_pct"] = (
            round(100.0 * tp / len(flagged), 3) if flagged else 0.0)
    msg = (f"flagged {len(flagged)}/{n} contrast-fidelity issue(s) "
           + (f"({', '.join(f'{k}={v}' for k, v in sorted(by_issue.items()))})"
              if by_issue else "(clean)"))
    return FunctionResult(ok=True, outputs={"flags": str(out)},
                          metrics=metrics, message=msg)


# ---------------------------------------------------------------------------
# sme_metric_separation
# ---------------------------------------------------------------------------


def sme_metric_separation(ctx: RunContext, inputs: dict[str, Any],
                          params: dict[str, Any]) -> FunctionResult:
    """How well does each candidate metric reproduce the SME's verdicts?"""
    lpath = _dataset_path(inputs.get("labels"))
    if not lpath or not Path(lpath).exists():
        return FunctionResult(
            ok=False, message="sme_metric_separation: no `labels` dataset wired")
    cand_col = str(params.get("candidate_col") or "reviewed_ko")
    ref_col = str(params.get("reference_col") or "ko_reference")
    allrefs_col = str(params.get("allrefs_col") or "ko_all")
    label_col = str(params.get("label_col") or "sme_rating")
    sep = str(params.get("multi_ref_separator") or "|")

    rows: list[dict] = []
    with Path(lpath).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cand = (r.get(cand_col) or "").strip()
            refs_raw = (r.get(allrefs_col) or r.get(ref_col) or "").strip()
            refs = [x for x in refs_raw.split(sep) if x.strip()]
            rating = (r.get(label_col) or "").strip().upper()
            if not cand or not refs or rating not in ACCEPT_RATINGS | REJECT_RATINGS:
                continue
            rows.append({"sctid": (r.get("sctid") or "").strip(),
                         "candidate": cand, "refs": refs, "rating": rating})
    if not rows:
        return FunctionResult(ok=False,
                              message=f"sme_metric_separation: no usable rows in {lpath}")

    labels = [int(r["rating"] in ACCEPT_RATINGS) for r in rows]

    exact_scores = [
        float(any(norm_text(r["candidate"]) == norm_text(ref) for ref in r["refs"]))
        for r in rows]
    chrf_scores = [
        max(sacrebleu.sentence_chrf(r["candidate"], [ref]).score
            for ref in r["refs"]) / 100.0
        for r in rows]

    # BGE-M3 cosine vs each ref, keep the max — one batched call per side.
    pairs = [(i, ref) for i, r in enumerate(rows) for ref in r["refs"]]
    sims = _embed_similarity([rows[i]["candidate"] for i, _ in pairs],
                             [ref for _, ref in pairs])
    cos_scores = [0.0] * len(rows)
    for (i, _), sim in zip(pairs, sims):
        cos_scores[i] = max(cos_scores[i], sim)

    def class_means(scores: list[float]) -> tuple[float, float]:
        pos = [s for s, y in zip(scores, labels) if y == 1]
        neg = [s for s, y in zip(scores, labels) if y == 0]
        return (sum(pos) / len(pos) if pos else float("nan"),
                sum(neg) / len(neg) if neg else float("nan"))

    metrics: dict[str, float] = {"n_rows": float(len(rows)),
                                 "n_acceptable": float(sum(labels)),
                                 "n_not_acceptable": float(len(labels) - sum(labels))}
    audit_cols: dict[str, list[float]] = {}
    for name, scores in (("exact", exact_scores), ("chrf", chrf_scores),
                         ("cosine", cos_scores)):
        pos_mean, neg_mean = class_means(scores)
        metrics[f"{name}_auc"] = round(_auc(scores, labels), 4)
        metrics[f"{name}_mean_acceptable"] = round(pos_mean, 4)
        metrics[f"{name}_mean_not_acceptable"] = round(neg_mean, 4)
        audit_cols[name] = scores
    thr, thr_stats = _best_threshold(cos_scores, labels)
    metrics["cosine_best_threshold"] = round(float(thr), 4)
    metrics["cosine_best_threshold_balanced_acc"] = round(
        float(thr_stats["balanced"]), 4)

    # The honest view: identity pairs (candidate string == a gold ref) make
    # separation trivial, because for Correct rows the gold IS the reviewed
    # translation. Restrict to rows where the candidate differs from every
    # reference as a raw string — positives there are exactly the "acceptable
    # variation" (spacing / preferred-synonym) the SME wants accepted, and a
    # metric only earns its keep by separating those from Partial/Wrong.
    nonident = [i for i, r in enumerate(rows)
                if all(r["candidate"] != ref for ref in r["refs"])]
    metrics["n_nonidentical"] = float(len(nonident))
    ni_labels = [labels[i] for i in nonident]
    metrics["n_nonidentical_acceptable"] = float(sum(ni_labels))
    if ni_labels and 0 < sum(ni_labels) < len(ni_labels):
        for name, scores in (("exact", exact_scores), ("chrf", chrf_scores),
                             ("cosine", cos_scores)):
            ni_scores = [scores[i] for i in nonident]
            metrics[f"{name}_auc_nonidentical"] = round(
                _auc(ni_scores, ni_labels), 4)
        ni_thr, ni_stats = _best_threshold(
            [cos_scores[i] for i in nonident], ni_labels)
        metrics["cosine_nonidentical_threshold"] = round(float(ni_thr), 4)
        metrics["cosine_nonidentical_balanced_acc"] = round(
            float(ni_stats["balanced"]), 4)

    out = Path(ctx.log_dir) / "sme_metric_separation_audit.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sctid", "candidate", "canonical_ref", "n_refs", "rating",
                    "exact", "chrf", "cosine"])
        for i, r in enumerate(rows):
            w.writerow([r["sctid"], r["candidate"], r["refs"][0], len(r["refs"]),
                        r["rating"], exact_scores[i], round(chrf_scores[i], 4),
                        round(cos_scores[i], 4)])

    msg = (f"{len(rows)} rows: AUC exact={metrics['exact_auc']} "
           f"chrf={metrics['chrf_auc']} cosine={metrics['cosine_auc']} "
           f"(cosine thr {metrics['cosine_best_threshold']} -> "
           f"balanced acc {metrics['cosine_best_threshold_balanced_acc']})")
    return FunctionResult(ok=True, outputs={"audit": str(out)},
                          metrics=metrics, message=msg)
