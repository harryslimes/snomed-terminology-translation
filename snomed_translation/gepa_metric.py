"""GEPA reward metric with a semantic (BGE-M3) score + a bounded LLM judge.

The default GEPA metric (`dspy_translate.make_metric`) scores non-exact
translations by chrF — a surface-form measure that penalises valid-but-divergent
Korean. This replaces the non-exact term with **BGE-M3 semantic cosine to the
gold reference** (max over refs), the measure that actually tracked quality in
the concept-context work, and adds an OPTIONAL **LLM judge** (e.g. Claude Fable
via the Agent SDK) that writes GEPA's reflective *feedback*.

Cost control is deliberate: the dense reward is a local embedding lookup (free);
the judge is called ONLY in GEPA's reflection path (`pred_name`/`pred_trace`
set), ONLY when the score is below ``judge_threshold``, is **capped** at
``max_judge_calls`` per run, and is **cached** by (term, candidate). So a whole
GEPA run makes tens of judge calls, not hundreds — gemma does the bulk work, the
judge is the sparse "why is this wrong + what rule fixes it" voice.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_JUDGE_SYSTEM = (
    "You are an expert judge of English→Korean SNOMED CT medical-terminology "
    "translations. Given the English term, a candidate Korean translation, and "
    "accepted gold Korean references, say concisely WHY the candidate is wrong or "
    "suboptimal and state the GENERAL, transferable translation RULE that would "
    "fix it — phrased so it could be added to a translation style guide. Focus on "
    "conventions (word order / head-final, nominalisation -술 vs bare stem, Sino- "
    "vs pure-Korean vocabulary, laterality, canonical modality forms, scope "
    "preservation, particles/spacing), not one-off substitutions. 2-3 sentences."
)


def _judge_user(term: str, candidate: str, refs: list[str]) -> str:
    return (f"English term: {term}\n"
            f"Candidate Korean: {candidate}\n"
            f"Accepted gold Korean: {' | '.join(refs[:4])}\n\n"
            "Why is the candidate wrong/suboptimal, and what general rule fixes it?")


def make_semantic_metric(*, judge_spec: Any = None, judge_key: str | None = None,
                         hard_rules: Any = None, max_judge_calls: int = 40,
                         judge_threshold: float = 0.9,
                         semantic_weight: float = 1.0, chrf_weight: float = 0.0):
    """GEPA metric closure. ``judge_spec`` is a ModelSpec (or None to disable the
    LLM judge and fall back to rule-based feedback). Returns a callable with the
    DSPy/GEPA metric signature that yields a float on validation and
    ``{score, feedback}`` in reflection."""
    import numpy as np

    from snomed_translation.hard_rules import (
        find_violations, load_hard_rules, penalty_for)
    from snomed_translation.scoring import best_ref_by_chrf, norm_text as _norm
    from snomed_translation.llm import complete

    # BGE-M3 must run on CPU during GEPA: the GPU is held by the gemma vLLM task
    # LM (loading BGE-M3 on CUDA hits OOM). CPU encode of short terms is fine, and
    # every vector is cached by text so repeated candidates/refs are free.
    from FlagEmbedding import BGEM3FlagModel
    try:
        _model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, devices="cpu")
    except TypeError:  # older FlagEmbedding uses `device=`
        _model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, device="cpu")
    _vec: dict[str, "np.ndarray"] = {}

    def _enc1(text: str) -> "np.ndarray":
        if text in _vec:
            return _vec[text]
        out = _model.encode([text or " "], batch_size=1, max_length=256,
                            return_dense=True, return_sparse=False,
                            return_colbert_vecs=False)
        v = np.array(out["dense_vecs"][0], np.float32)
        v = v / (float(np.linalg.norm(v)) + 1e-9)
        _vec[text] = v
        return v

    def _semantic(candidate: str, refs: list[str]) -> float:
        hv = _enc1(candidate)
        return max(float(hv @ _enc1(r)) for r in refs)

    enforced = [r for r in load_hard_rules(hard_rules) if r.enforce]
    w_sum = semantic_weight + chrf_weight
    state = {"judge_calls": 0}
    judge_cache: dict[tuple, str] = {}

    def _metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
        candidate = (getattr(pred, "korean", None) or str(pred)).strip()
        refs = [r for r in (gold.ko_all or gold.ko_reference).split("|") if r.strip()]
        reflecting = not (pred_name is None and pred_trace is None)
        if not refs:
            return ({"score": 0.0, "feedback": "no reference available"}
                    if reflecting else 0.0)

        exact = 1.0 if _norm(candidate) in {_norm(r) for r in refs} else 0.0
        if exact == 1.0:
            score = 1.0
        else:
            sem = _semantic(candidate, refs)
            chrf = best_ref_by_chrf(candidate, refs)[1] / 100.0 if chrf_weight else 0.0
            score = (semantic_weight * sem + chrf_weight * chrf) / w_sum

        violations = (find_violations(candidate, enforced)
                      if (enforced and exact != 1.0) else [])
        if violations:
            score = max(0.0, score - penalty_for(violations))

        if not reflecting:
            return float(score)

        # --- reflection: build feedback (rule-based, + Fable judge when low) ---
        parts = [f"candidate: {candidate}",
                 f"accepted gold references: {' | '.join(refs[:4])}",
                 f"semantic score: {score:.2f}"]
        if violations:
            parts.append("HARD RULE violations (MUST fix): "
                         + "; ".join(m for _, m in violations))
        feedback = " | ".join(parts)

        # Fire the judge ONLY on GEPA's genuine reflection calls — not on
        # evaluate()'s whole-valset scoring (pred_name="evaluate"), which would
        # burn the budget on measurement instead of optimisation.
        if (judge_spec is not None and pred_name not in (None, "evaluate")
                and score < judge_threshold
                and state["judge_calls"] < max_judge_calls):
            key = (gold.preferred_term, candidate)
            if key in judge_cache:
                feedback = judge_cache[key]
            else:
                state["judge_calls"] += 1
                try:
                    verdict = complete(
                        judge_spec, judge_key or "judge", _JUDGE_SYSTEM,
                        _judge_user(gold.preferred_term, candidate, refs),
                        {"thinking": False})
                    feedback = f"{feedback}\nJUDGE: {verdict.strip()}"
                    judge_cache[key] = feedback
                except Exception as exc:  # never let a judge hiccup kill GEPA
                    log.warning("judge call failed: %s", exc)
                    feedback = f"{feedback}\n(judge unavailable: {exc})"
        return {"score": float(score), "feedback": feedback}

    _metric.judge_calls = lambda: state["judge_calls"]  # for reporting
    return _metric
