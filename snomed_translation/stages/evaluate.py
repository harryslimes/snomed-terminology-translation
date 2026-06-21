"""Evaluation stage runner.

Scores a translations CSV against the eval set's reference column using the
scorer mix declared in `cfg.evaluation.scorers`. Multi-reference (`all_references`)
is honoured when `cfg.evaluation.multi_ref` is true.

Uses snomed_translation.scoring (shared with the DSPy/GEPA harness) so scoring is
bit-identical to the DSPy-driven eval path — without importing dspy/LiteLLM.
"""
from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

import sacrebleu

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from snomed_translation.config import PipelineConfig
from pipelines.context import RunContext, StageResult
from snomed_translation.scoring import best_ref_by_chrf as _best_ref_by_chrf
from snomed_translation.scoring import norm_text as _norm

log = logging.getLogger(__name__)


def _load_eval_refs(cfg: PipelineConfig) -> dict[str, dict]:
    """Return {sctid: {reference, all_references: [..]}} from the eval set."""
    if cfg.eval_set is None:
        raise RuntimeError(
            "evaluate stage requires an eval set; pass --eval-set to "
            "snomed_translation.run, or bake one into the config's eval_set block."
        )
    out: dict[str, dict] = {}
    cols = cfg.eval_set.columns
    sep = cfg.eval_set.multi_ref_separator
    with cfg.eval_set.csv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sctid = row[cols.sctid]
            ref = row.get(cols.reference, "")
            all_refs_raw = row.get(cols.all_references) if cfg.evaluation.multi_ref else ref
            all_refs = [r for r in (all_refs_raw or ref).split(sep) if r.strip()] or [ref]
            out[sctid] = {"reference": ref, "all_references": all_refs}
    return out


def _load_translations(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["sctid"]] = (row.get("translation") or "").strip()
    return out


def run(cfg: PipelineConfig, ctx: RunContext, *,
        translations_path: Path | None = None,
        limit: int | None = None, **_) -> StageResult:
    """Score a translations CSV. Defaults to the file the translate stage
    just wrote."""
    if translations_path is None:
        translations_path = cfg.paths.output_dir / cfg.translation.output_filename_pattern.format(
            output_tag=cfg.translation.output_tag,
        )
    translations_path = Path(translations_path)
    if not translations_path.exists():
        return StageResult(stage="evaluate", ok=False,
                           message=f"Translations CSV not found: {translations_path}")

    refs = _load_eval_refs(cfg)
    translations = _load_translations(translations_path)
    sctids = [s for s in refs if s in translations]
    if limit:
        sctids = sctids[:limit]

    enabled_scorers = {s.kind: s for s in cfg.evaluation.scorers}
    n = 0
    sum_exact = 0
    sum_chrf = 0.0
    rows = []
    for sctid in sctids:
        cand = translations[sctid]
        all_refs = refs[sctid]["all_references"]
        if not all_refs:
            continue
        cand_norm = _norm(cand)
        refs_norm = {_norm(r) for r in all_refs}
        exact = 1 if cand_norm in refs_norm else 0
        best_ref, best_chrf = _best_ref_by_chrf(cand, all_refs)
        rows.append({
            "sctid": sctid,
            "candidate": cand,
            "best_ref": best_ref,
            "exact": exact,
            "chrf": best_chrf,
        })
        sum_exact += exact
        sum_chrf += best_chrf
        n += 1

    if n == 0:
        return StageResult(stage="evaluate", ok=False,
                           message="No overlap between translations and references")

    mean_exact = sum_exact / n
    mean_chrf = sum_chrf / n
    composite = 0.0
    weight_sum = 0.0
    for kind, spec in enabled_scorers.items():
        if kind == "exact_match":
            composite += spec.weight * mean_exact
            weight_sum += spec.weight
        elif kind == "chrf":
            composite += spec.weight * (mean_chrf / 100.0)
            weight_sum += spec.weight
        # other scorers land in Phase 4
    composite = composite / weight_sum if weight_sum > 0 else 0.0

    out_path = translations_path.with_name(translations_path.stem + "_eval.csv")
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sctid", "candidate", "best_ref", "exact", "chrf"])
        w.writeheader()
        w.writerows(rows)

    log.info("Evaluated %d rows: exact=%.1f%%  chrF=%.1f  composite=%.3f",
             n, 100 * mean_exact, mean_chrf, composite)

    return StageResult(
        stage="evaluate",
        ok=True,
        outputs={"scored_csv": out_path},
        output_paths=[out_path],
        metrics={
            "n": float(n),
            "exact_match_pct": 100 * mean_exact,
            "mean_chrf": mean_chrf,
            "composite_score": composite,
        },
        message=f"n={n} exact={100 * mean_exact:.1f}% chrF={mean_chrf:.1f} composite={composite:.3f}",
    )
