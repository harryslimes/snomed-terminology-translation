"""Self-consistency evaluation stage (an evaluate sub-type).

Consumes a translate_consistency node's *candidates* artifact and does three
things:

1. **Judge selection** — for every concept with more than one distinct
   candidate, it replays *the full original prompt that was used to translate*
   (from the prompt sidecar the upstream node wrote), appends the candidate
   list, and asks the **same translating model** to pick the best one. Concepts
   with a single candidate skip the judge.
2. **Scoring** — the chosen translation is scored against the gold reference
   with the same scorers as the plain evaluate stage (exact + chrF, via
   :mod:`snomed_translation.scoring`).
3. **Calibration** — using the wired gold reference as the canonical answer, it
   scores *every* candidate, finds the **oracle** (the candidate closest to the
   canonical), and records whether the **LLM judge** and the **majority /
   self-consistency consensus** picks match the oracle. This is how good the
   judge / similarity metric are at picking the best candidate.

Outputs:
  * ``chosen_<tag>.csv`` — the picked translations in the standard translate
    shape (sctid, preferred_term, ko_reference, translation). Publishable as a
    data source via the node's ``publish_as`` param.
  * ``<candidates>_consistency_eval.csv`` — per-concept scores + the oracle /
    majority calibration columns (``candidate_scores`` carries every candidate's
    chrF-vs-gold for offline analysis of any other selection metric).
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from snomed_translation.config import PipelineConfig
from pipelines.context import RunContext, StageResult
from snomed_translation.scoring import best_ref_by_chrf as _best_ref_by_chrf
from snomed_translation.scoring import norm_text as _norm
from snomed_translation.stages.evaluate import _load_eval_refs
from scripts.translation.translate_korean_with_lookup import (
    translate_one,
    wait_for_server,
)

log = logging.getLogger(__name__)

_INT_RE = re.compile(r"\d+")
_BEST_RE = re.compile(r"BEST\s*[:\-]?\s*(\d+)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON\s*[:\-]?", re.IGNORECASE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_TIE = 1e-6   # chrF tolerance for "is this candidate (one of) the best"
_REASON_MAX = 300

JUDGE_INSTRUCTION = (
    "\n\nSeveral candidate translations were produced for this term:\n"
    "{numbered}\n\n"
    "Decide which single candidate is the best translation, considering the "
    "style guide and the reference examples above. You may reason first, but "
    "you MUST end your reply with exactly these two lines and nothing after "
    "them:\n"
    "BEST: <number>\n"
    "REASON: <one concise sentence, written in {language}, explaining why that "
    "candidate is the best>"
)


def _clean_reason(text: str) -> str:
    """One tidy line: collapse whitespace, drop markdown bullets, cap length."""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    line = re.sub(r"\s+", " ", line).strip().lstrip("*-•> ").strip("` ").strip()
    if len(line) > _REASON_MAX:
        line = line[:_REASON_MAX - 1].rstrip() + "…"
    return line


def _parse_judge(response: str, n: int) -> tuple[int | None, str]:
    """Parse the judge reply into (0-based choice index or None, reason text).

    Robust to thinking models that emit reasoning before the answer: the
    structured ``BEST:`` / ``REASON:`` lines are required to come last, so we
    take the **last** match of each. ``<think>`` blocks are stripped. If no
    ``REASON:`` line is present the reason is left empty rather than dumping the
    raw reasoning scaffolding.
    """
    text = _THINK_RE.sub("", response or "").strip()

    # Choice: the LAST "BEST: n" (the post-reasoning answer); else last integer.
    best = list(_BEST_RE.finditer(text))
    if best:
        raw = int(best[-1].group(1))
    else:
        ints = list(_INT_RE.finditer(text))
        raw = int(ints[-1].group()) if ints else None
    idx = None
    if raw is not None:
        i = raw - 1
        idx = i if 0 <= i < n else None

    # Reason: text after the LAST "REASON:" marker, first clean line only.
    rmatches = list(_REASON_RE.finditer(text))
    reason = _clean_reason(text[rmatches[-1].end():]) if rmatches else ""
    return idx, reason


def _load_candidates(path: Path) -> dict[str, dict]:
    """{sctid: {preferred_term, ko_reference, candidates: [{text, count}, ...]}}.

    Candidates keep their counts and stay ordered most-frequent first (the
    upstream stage writes them that way), so ``candidates[0]`` is the majority /
    self-consistency consensus.
    """
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                cands = json.loads(row.get("candidates") or "[]")
            except (json.JSONDecodeError, TypeError):
                cands = []
            out[row["sctid"]] = {
                "preferred_term": row.get("preferred_term", ""),
                "ko_reference": row.get("ko_reference", ""),
                "candidates": cands,
            }
    return out


def run(cfg: PipelineConfig, ctx: RunContext, *,
        candidates_path: Path | None = None,
        model_key: str | None = None,
        thinking: bool = False,
        explanation_language: str = "English",
        limit: int | None = None, **_) -> StageResult:
    stage = "evaluate_consistency"
    if candidates_path is None:
        return StageResult(stage=stage, ok=False,
                           message="no candidates artifact wired")
    candidates_path = Path(candidates_path)
    if not candidates_path.exists():
        return StageResult(stage=stage, ok=False,
                           message=f"candidates CSV not found: {candidates_path}")

    cand_rows = _load_candidates(candidates_path)
    refs = _load_eval_refs(cfg)

    # Prompt sidecar — written next to the candidates CSV by the upstream
    # translate_consistency stage. It carries the exact prompt to replay.
    sidecar_path = candidates_path.with_name(candidates_path.stem + ".prompts.json")
    sidecar: dict = {}
    if sidecar_path.exists():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    else:
        log.warning("[%s] prompt sidecar missing (%s) — multi-candidate "
                    "concepts will fall back to the majority candidate instead "
                    "of being judged", stage, sidecar_path)
    system_prompt = sidecar.get("system_prompt", "")
    user_prompts: dict[str, str] = sidecar.get("user_prompts", {})

    sctids = [s for s in cand_rows if s in refs]
    if limit:
        sctids = sctids[:limit]
    if not sctids:
        return StageResult(stage=stage, ok=False,
                           message="no overlap between candidates and references")

    def texts(sctid: str) -> list[str]:
        return [c.get("text", "") for c in cand_rows[sctid]["candidates"]]

    # Which concepts actually need the judge (>1 distinct candidate AND a
    # replayable prompt). The rest resolve to their majority candidate.
    judge_ids = [s for s in sctids if len(texts(s)) > 1 and s in user_prompts]
    chosen: dict[str, str] = {}
    judged: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    for s in sctids:
        cands = texts(s)
        chosen[s] = cands[0] if cands else ""   # default: majority (most frequent)
        judged[s] = False
        reasons[s] = ""

    if judge_ids:
        judge_model = model_key or sidecar.get("model_key") or \
            cfg.translation.default_model_key
        if judge_model is None or judge_model not in cfg.models:
            return StageResult(stage=stage, ok=False,
                               message=f"judge model {judge_model!r} not in "
                                        "the models catalogue")
        base_url = os.getenv("VLLM_BASE_URL",
                             cfg.model_base_url(judge_model).rsplit("/v1", 1)[0])
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        model_id = cfg.models[judge_model].hf_id
        # Thinking is requested up front (so the reason is real reasoning, not a
        # post-hoc rationalisation) and is the on/off comparison knob. Both
        # forms are sent — vLLM reads chat_template_kwargs; the top-level flag
        # matches the catalogue convention. Thinking needs more output budget.
        judge_params = {
            "temperature": 0.0,
            "max_tokens": 4096 if thinking else 1024,
            "chat_template_kwargs": {"enable_thinking": bool(thinking)},
            "enable_thinking": bool(thinking),
        }
        concurrency = max(1, cfg.evaluation.judge.concurrency)
        log.info("[%s] judging %d/%d multi-candidate concepts with %s "
                 "(thinking=%s, explanation=%s)", stage, len(judge_ids),
                 len(sctids), judge_model, thinking, explanation_language)
        wait_for_server(base_url)

        def judge(sctid: str) -> tuple[str, str, bool, str]:
            cands = texts(sctid)
            numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(cands))
            user = user_prompts[sctid] + JUDGE_INSTRUCTION.format(
                numbered=numbered, language=explanation_language)
            try:
                resp = translate_one(base_url, model_id, system_prompt, user,
                                     judge_params)
                idx, reason = _parse_judge(resp, len(cands))
            except Exception as exc:  # noqa: BLE001 — fall back, don't crash
                log.error("judge %s -> ERROR %s", sctid[:12], exc)
                idx, reason = None, ""
            if idx is None:
                return sctid, cands[0], False, reason   # unparseable → majority
            return sctid, cands[idx], True, reason

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(judge, s): s for s in judge_ids}
            for fut in as_completed(futures):
                if ctx.is_cancelled():
                    log.warning("[%s] cancelled — using fallbacks for the rest",
                                stage)
                    break
                sctid, pick, was_judged, reason = fut.result()
                chosen[sctid] = pick
                judged[sctid] = was_judged
                reasons[sctid] = reason

    # --- Score the chosen translation + calibrate every candidate vs gold. ---
    n = 0
    sum_exact = 0
    sum_chrf = 0.0
    n_judged = 0
    # calibration accumulators, over multi-candidate concepts only
    n_multi = 0
    judge_hits = 0
    majority_hits = 0
    sum_chosen_chrf = 0.0
    sum_majority_chrf = 0.0
    sum_oracle_chrf = 0.0
    out_rows = []
    chosen_rows = []
    for sctid in sctids:
        all_refs = refs[sctid]["all_references"]
        if not all_refs:
            continue
        refs_norm = {_norm(r) for r in all_refs}
        cands = cand_rows[sctid]["candidates"]
        cand_texts = [c.get("text", "") for c in cands]
        if not cand_texts:
            continue
        # Per-candidate chrF vs the canonical reference(s).
        scores = [_best_ref_by_chrf(t, all_refs)[1] for t in cand_texts]
        oracle_chrf = max(scores)
        oracle_idx = scores.index(oracle_chrf)
        oracle_text = cand_texts[oracle_idx]
        majority_text = cand_texts[0]            # most frequent (consensus)
        majority_chrf = scores[0]
        cand_text = chosen[sctid]
        chosen_chrf = (scores[cand_texts.index(cand_text)]
                       if cand_text in cand_texts else
                       _best_ref_by_chrf(cand_text, all_refs)[1])

        exact = 1 if _norm(cand_text) in refs_norm else 0
        best_ref, best_chrf = _best_ref_by_chrf(cand_text, all_refs)
        is_multi = len(cand_texts) > 1
        chose_oracle = int(chosen_chrf >= oracle_chrf - _TIE)
        majority_is_oracle = int(majority_chrf >= oracle_chrf - _TIE)

        out_rows.append({
            "sctid": sctid,
            "candidate": cand_text,
            "best_ref": best_ref,
            "exact": exact,
            "chrf": best_chrf,
            "n_candidates": len(cand_texts),
            "judged": int(judged[sctid]),
            "oracle_candidate": oracle_text,
            "oracle_chrf": round(oracle_chrf, 2),
            "chose_oracle": chose_oracle,
            "majority_candidate": majority_text,
            "majority_chrf": round(majority_chrf, 2),
            "majority_is_oracle": majority_is_oracle,
            "thinking": int(bool(thinking)),
            "reason": reasons.get(sctid, ""),
            "candidate_scores": json.dumps(
                [{"text": t, "count": c.get("count"), "chrf": round(s, 2)}
                 for t, c, s in zip(cand_texts, cands, scores)],
                ensure_ascii=False),
        })
        chosen_rows.append({
            "sctid": sctid,
            "preferred_term": cand_rows[sctid]["preferred_term"],
            "ko_reference": cand_rows[sctid]["ko_reference"],
            "translation": cand_text,
        })

        sum_exact += exact
        sum_chrf += best_chrf
        n_judged += int(judged[sctid])
        n += 1
        if is_multi:
            n_multi += 1
            judge_hits += chose_oracle
            majority_hits += majority_is_oracle
            sum_chosen_chrf += chosen_chrf
            sum_majority_chrf += majority_chrf
            sum_oracle_chrf += oracle_chrf

    if n == 0:
        return StageResult(stage=stage, ok=False, message="no scorable rows")

    mean_exact = sum_exact / n
    mean_chrf = sum_chrf / n
    enabled = {s.kind: s for s in cfg.evaluation.scorers}
    composite = 0.0
    weight_sum = 0.0
    for kind, spec in enabled.items():
        if kind == "exact_match":
            composite += spec.weight * mean_exact
            weight_sum += spec.weight
        elif kind == "chrf":
            composite += spec.weight * (mean_chrf / 100.0)
            weight_sum += spec.weight
    composite = composite / weight_sum if weight_sum > 0 else 0.0

    out_dir = candidates_path.parent
    tag = cfg.translation.output_tag
    # Tag by this eval node (not the candidates file): two evaluate_consistency
    # nodes can consume the SAME candidates artifact (e.g. thinking on vs off),
    # so the scored CSV must be per-node or the second clobbers the first.
    out_path = out_dir / f"eval_{tag}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "sctid", "candidate", "best_ref", "exact", "chrf", "n_candidates",
            "judged", "oracle_candidate", "oracle_chrf", "chose_oracle",
            "majority_candidate", "majority_chrf", "majority_is_oracle",
            "thinking", "reason", "candidate_scores"])
        w.writeheader()
        w.writerows(out_rows)

    chosen_path = out_dir / f"chosen_{tag}.csv"
    with chosen_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sctid", "preferred_term",
                                          "ko_reference", "translation"])
        w.writeheader()
        w.writerows(chosen_rows)

    # Calibration summary (over multi-candidate concepts only — single-candidate
    # concepts are trivially "correct" and would inflate the rates).
    judge_acc = judge_hits / n_multi if n_multi else None
    majority_acc = majority_hits / n_multi if n_multi else None
    log.info("[%s] n=%d exact=%.1f%% chrF=%.1f composite=%.3f | multi=%d "
             "judge_acc=%s majority_acc=%s",
             stage, n, 100 * mean_exact, mean_chrf, composite, n_multi,
             f"{judge_acc:.2f}" if judge_acc is not None else "n/a",
             f"{majority_acc:.2f}" if majority_acc is not None else "n/a")

    metrics = {
        "n": float(n),
        "n_judged": float(n_judged),
        "exact_match_pct": 100 * mean_exact,
        "mean_chrf": mean_chrf,
        "composite_score": composite,
        "n_multi_candidate": float(n_multi),
    }
    if n_multi:
        metrics.update({
            "judge_oracle_accuracy": judge_acc,
            "majority_oracle_accuracy": majority_acc,
            "mean_chrf_chosen_multi": sum_chosen_chrf / n_multi,
            "mean_chrf_majority_multi": sum_majority_chrf / n_multi,
            "mean_chrf_oracle_multi": sum_oracle_chrf / n_multi,
        })

    return StageResult(
        stage=stage,
        ok=True,
        outputs={"scored_csv": out_path, "chosen_csv": chosen_path},
        output_paths=[out_path, chosen_path],
        metrics=metrics,
        message=(f"n={n} exact={100 * mean_exact:.1f}% chrF={mean_chrf:.1f} "
                 f"composite={composite:.3f} | {n_multi} multi-candidate "
                 f"(thinking {'on' if thinking else 'off'})"
                 + (f", judge picks best {judge_acc:.0%} vs majority "
                    f"{majority_acc:.0%}" if n_multi else "")),
    )
