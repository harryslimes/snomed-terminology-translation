"""DSPy scaffold for SNOMED EN→KO radiology translation prompt optimization.

Wraps the production translator (gemma4-26b on local vLLM + BGE-M3 RAG exemplars)
as a `dspy.Module`. The style-guide text is stored as the optimizable
`Signature.instructions` field so that GEPA can mutate it.

The module mirrors the production prompt structure from
`scripts/translation/translate_korean_with_lookup.py` so that an optimized
instruction string can be lifted back into production by saving it as a new
style-guide file.

Usage:
    from scripts.optimization.dspy_translate import (
        build_lm, build_translator, load_split, metric
    )

    lm = build_lm()
    translator = build_translator(
        style_guide_path="style_guide/style_guide_ko_v5.md",
        lookup_cache_path="data/sme_review/2026-04-24/lookup_cache.json",
    )
    dev = load_split("data/evals/korean/dspy_splits/dev.csv")
    # baseline eval:
    scores = [metric(ex, translator(ex.preferred_term, ex.exemplars))['score']
              for ex in dev]
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Iterable

import dspy
import sacrebleu

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# LM configuration — local vLLM, OpenAI-compatible.
# ---------------------------------------------------------------------------

DEFAULT_MODEL_ID = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
DEFAULT_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8083/v1")


def build_lm(
    model_id: str = DEFAULT_MODEL_ID,
    base_url: str = DEFAULT_BASE_URL,
    max_tokens: int = 128,
    temperature: float = 0.0,
    top_p: float | None = None,
    top_k: int | None = None,
    api_key: str = "EMPTY",
    extra_body: dict | None = None,
    drop_stop_sequences: bool = False,
) -> dspy.LM:
    """OpenAI-compatible LM client.

    Defaults are tuned for our local vLLM gemma4-26b. To target a remote
    endpoint (e.g. Dashscope qwen3.7-max):

        build_lm(
            model_id="qwen3.7-max",
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            api_key=os.environ["DASHSCOPE_API_KEY"],
            extra_body={"enable_thinking": False},  # disable thinking on Qwen
            max_tokens=256,
            drop_stop_sequences=True,  # reasoning models can break on stops
        )
    """
    kwargs = dict(
        api_base=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if top_p is not None:
        kwargs["top_p"] = top_p
    if not drop_stop_sequences:
        kwargs["stop"] = ["\n\n", "English:"]
    # top_k is non-OpenAI; route through extra_body for vLLM.
    eb = dict(extra_body or {})
    if top_k is not None:
        eb["top_k"] = top_k
    if eb:
        kwargs["extra_body"] = eb
    return dspy.LM(f"openai/{model_id}", **kwargs)


# ---------------------------------------------------------------------------
# Signature — the optimizable surface.
# GEPA mutates `signature.instructions`; the input/output fields are fixed.
# ---------------------------------------------------------------------------


def build_signature(instructions: str,
                    with_hard_rules: bool = False) -> dspy.Signature:
    """Build the translation signature with the given (mutable) instructions.

    GEPA mutates ``instructions`` only. When ``with_hard_rules`` is set we add a
    constant ``hard_rules`` *input* field; input values are supplied per call by
    the module and are never part of the optimisable surface, so the frozen
    rule block survives every reflective mutation verbatim.
    """
    fields = ("english_term, exemplars, hard_rules -> korean"
              if with_hard_rules else "english_term, exemplars -> korean")
    sig = dspy.Signature(fields, instructions=instructions)
    return sig


# ---------------------------------------------------------------------------
# Module — wraps the BGE-M3 exemplar lookup + LM call.
# ---------------------------------------------------------------------------


class SnomedKoreanTranslator(dspy.Module):
    """Looks up top-N exemplars from a pre-built BGE-M3 cache, then translates.

    The lookup is keyed by sctid (matches the production translator). For
    rows whose sctid is not in the cache (rare), we fall back to an empty
    exemplar table — GEPA's mutation should still proceed.
    """

    def __init__(self, signature: dspy.Signature, lookup_cache: dict,
                 topn: int = 5, hard_rules_block: str = ""):
        super().__init__()
        self.predictor = dspy.Predict(signature)
        self.lookup_cache = lookup_cache
        self.topn = topn
        # Constant, injected per call into the (non-optimisable) hard_rules
        # input field. Empty string => signature has no hard_rules field.
        self.hard_rules_block = hard_rules_block

    def _format_exemplars(self, sctid: str) -> str:
        pairs = (self.lookup_cache.get(sctid) or [])[: self.topn]
        if not pairs:
            return "(no similar translations found)"
        lines = ["|English|Korean|", "|---|---|"]
        for en, ko in pairs:
            lines.append(f"|{en}|{ko}|")
        return "\n".join(lines)

    def forward(self, sctid: str, preferred_term: str) -> dspy.Prediction:  # type: ignore[override]
        # Argument name must match dspy.Example.with_inputs("sctid", "preferred_term").
        exemplars = self._format_exemplars(sctid)
        kwargs = dict(english_term=preferred_term, exemplars=exemplars)
        if self.hard_rules_block:
            kwargs["hard_rules"] = self.hard_rules_block
        result = self.predictor(**kwargs)
        # Strip whitespace / quotes the way the production translator does.
        ko = (result.korean or "").strip().strip('"').strip("'").strip()
        return dspy.Prediction(korean=ko)


def build_translator(
    style_guide_path: str | Path,
    lookup_cache_path: str | Path,
    topn: int = 5,
    hard_rules: "dict | Path | str | None" = None,
) -> SnomedKoreanTranslator:
    """Construct the translator with the style guide as the seed instruction.

    ``hard_rules`` (path/dict/None) supplies frozen constraints: any rule with
    ``freeze: true`` is rendered into a constant ``hard_rules`` input field that
    GEPA cannot mutate. None/empty => behaviour identical to the pre-hard-rules
    path (2-input signature).
    """
    from pipelines.hard_rules import frozen_block, load_hard_rules

    instructions = Path(style_guide_path).read_text(encoding="utf-8")
    lookup_cache = json.loads(Path(lookup_cache_path).read_text(encoding="utf-8"))
    block = frozen_block(load_hard_rules(hard_rules))
    return SnomedKoreanTranslator(
        signature=build_signature(instructions, with_hard_rules=bool(block)),
        lookup_cache=lookup_cache,
        topn=topn,
        hard_rules_block=block,
    )


# ---------------------------------------------------------------------------
# Metric — multi-reference (ko_all), blended exact-match + chrF, with
# natural-language feedback for GEPA's reflective mutation.
# ---------------------------------------------------------------------------


# Canonical home is pipelines.scoring (shared with the evaluate stage, which
# must stay free of this module's dspy import chain). Same names, same maths.
from pipelines.scoring import best_ref_by_chrf as _best_ref_by_chrf  # noqa: E402
from pipelines.scoring import norm_text as _norm  # noqa: E402


# Default Korean hints — used when no hints file is supplied. Kept here so
# that existing GEPA runs continue to behave identically. Move to
# configs/hints/ko.yaml when running through the pipelines.* framework.
_DEFAULT_KO_HINTS: dict = {
    "solid_compounds": [
        "자기공명영상", "컴퓨터단층촬영", "초음파검사",
        "혈관조영술", "정맥조영술", "관절조영",
    ],
    "native_vs_sino": [
        ("팔", "상지"), ("팔", "위팔"),
        ("다리", "하지"), ("허리", "요부"),
        ("후복막", "복막뒤"), ("신경얼기", "신경총"),
    ],
    "front_markers": ["조영제 사용", "조영제 미사용"],
    "suffix_preservation": [("조영술", "조영"), ("조영상", "조영")],
}


def _load_hints(hints: dict | Path | str | None) -> dict:
    """Load a hints dict from YAML file path, dict, or None (=KO default)."""
    if hints is None:
        return _DEFAULT_KO_HINTS
    if isinstance(hints, dict):
        return hints
    import yaml
    return yaml.safe_load(Path(hints).read_text(encoding="utf-8")) or {}


def _generate_hints(candidate: str, best_ref: str, hints_data: dict) -> list[str]:
    """Pure function: compute rule-violation hints between candidate and ref.

    Driven by a hints dict (see configs/hints/ko.yaml for the Korean instance).
    Returns a list of human-readable hint strings, deduplicated.
    """
    out: list[str] = []

    for compound in hints_data.get("solid_compounds", []):
        if compound in best_ref.replace(" ", "") and compound in candidate.replace(" ", ""):
            if compound not in candidate and any(c in candidate for c in compound):
                out.append(f"fixed compound '{compound}' was internally spaced in candidate")

    for pair in hints_data.get("native_vs_sino", []):
        native, sino = pair[0], pair[1]
        if sino in candidate and native in best_ref:
            out.append(f"candidate used Sino form '{sino}' where reference uses native '{native}'")
        elif native in candidate and sino in best_ref:
            out.append(f"candidate used native '{native}' where reference uses Sino form '{sino}'")

    for marker in hints_data.get("front_markers", []):
        if marker in best_ref and marker in candidate:
            if not candidate.lstrip().startswith(marker):
                out.append(f"front marker '{marker}' should appear at the FRONT of the term")

    for pair in hints_data.get("suffix_preservation", []):
        long_form, root = pair[0], pair[1]
        if long_form in best_ref and long_form not in candidate and root in candidate:
            out.append(f"derivational suffix in '{long_form}' was dropped from candidate (kept only '{root}')")

    return list(dict.fromkeys(out))  # dedupe, preserve order


def make_metric(hints: dict | Path | str | None = None,
                hard_rules: "dict | Path | str | None" = None):
    """Factory returning a GEPA-compatible metric closure.

    `hints` (configs/hints/<lang>.yaml) drives the reflective-feedback string
    only — it never moves the score. `hard_rules` (configs/hard_rules/<lang>.yaml)
    is different: every ``enforce: true`` rule the candidate violates subtracts
    its ``penalty`` from the [0,1] score, so GEPA loses the incentive to explore
    the disallowed form. Both default to None for backward-compatible behaviour
    (bundled Korean hints, no penalties).
    """
    from pipelines.hard_rules import find_violations, load_hard_rules, penalty_for

    hints_data = _load_hints(hints)
    enforced_rules = [r for r in load_hard_rules(hard_rules) if r.enforce]

    def _metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
        candidate = (getattr(pred, "korean", None) or str(pred)).strip()
        refs = [r for r in (gold.ko_all or gold.ko_reference).split("|") if r.strip()]
        if not refs:
            return {"score": 0.0, "feedback": "no reference available"}

        cand_norm = _norm(candidate)
        refs_norm = {_norm(r) for r in refs}
        exact = 1.0 if cand_norm in refs_norm else 0.0
        best_ref, best_chrf = _best_ref_by_chrf(candidate, refs)
        score = 0.5 * exact + 0.5 * (best_chrf / 100.0)

        # Hard-rule penalty. Exact matches hit an accepted reference, so by
        # definition they don't violate a rule — skip the check (and avoid
        # penalising a reference the data itself blessed).
        violations = (find_violations(candidate, enforced_rules)
                      if (enforced_rules and exact != 1.0) else [])
        if violations:
            score = max(0.0, score - penalty_for(violations))

        # Plain-validation call: return just the (penalised) float score.
        if pred_name is None and pred_trace is None:
            return float(score)

        if exact == 1.0:
            return {
                "score": score,
                "feedback": f"exact match against accepted reference '{best_ref}'",
            }

        parts: list[str] = [
            f"candidate: {candidate}",
            f"closest accepted reference (chrF={best_chrf:.0f}): {best_ref}",
        ]
        if len(refs) > 1:
            others = [r for r in refs if r != best_ref][:3]
            parts.append("other accepted references: " + " | ".join(others))

        sme_notes = getattr(gold, "sme_notes", "") or ""
        if sme_notes.strip():
            parts.append(f"SME note: {sme_notes.strip()}")
        sme_rating = getattr(gold, "sme_rating", "") or ""
        if sme_rating.strip():
            parts.append(f"SME rating of similar machine output: {sme_rating.strip()}")

        if best_chrf < 70 and _norm(candidate) != _norm(best_ref):
            hint_lines = _generate_hints(candidate, best_ref, hints_data)
            if hint_lines:
                parts.append("possible rule violations: " + "; ".join(hint_lines))

        if violations:
            parts.append(
                "HARD RULE violations (score penalised, MUST fix): "
                + "; ".join(msg for _, msg in violations)
            )

        return {"score": score, "feedback": " | ".join(parts)}

    return _metric


# Module-level default: behaves identically to the pre-refactor metric so
# existing scripts (eval_baseline.py, run_gepa.py) keep working unchanged.
metric = make_metric(None)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_split(path: str | Path) -> list[dspy.Example]:
    """Load a split CSV produced by Phase 0 into dspy.Examples."""
    examples = []
    for row in csv.DictReader(Path(path).open(encoding="utf-8")):
        ex = dspy.Example(
            sctid=row["sctid"],
            preferred_term=row["preferred_term"],
            ko_reference=row["ko_reference"],
            ko_all=row["ko_all"] or row["ko_reference"],
            modality=row.get("modality", ""),
            source=row.get("source", ""),
            sme_rating=row.get("sme_rating", ""),
            sme_notes=row.get("sme_notes", ""),
        ).with_inputs("sctid", "preferred_term")
        examples.append(ex)
    return examples


def evaluate(translator: SnomedKoreanTranslator,
             examples: Iterable[dspy.Example],
             verbose: bool = False,
             concurrency: int = 8) -> dict:
    """Run the translator over examples; return aggregate metric stats.

    This duplicates a tiny subset of `dspy.Evaluate`'s functionality so that
    the same scoring code can be used both for ad-hoc baselines and as the
    GEPA optimizer's objective.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    examples = list(examples)

    def _score_one(ex):
        try:
            pred = translator(sctid=ex.sctid, preferred_term=ex.preferred_term)
        except Exception as exc:
            return {"sctid": ex.sctid, "preferred_term": ex.preferred_term,
                    "candidate": f"ERROR: {exc}", "score": 0.0, "exact": 0,
                    "chrf": 0.0, "source": ex.source, "sme_rating": ex.sme_rating,
                    "feedback": str(exc)[:200]}
        m = metric(ex, pred, pred_name="evaluate", pred_trace=[])
        cand = pred.korean
        cand_norm = _norm(cand)
        refs_norm = {_norm(r) for r in (ex.ko_all or "").split("|") if r.strip()}
        exact = 1 if cand_norm in refs_norm else 0
        refs_list = [r for r in (ex.ko_all or "").split("|") if r.strip()] or [ex.ko_reference]
        _, best_chrf = _best_ref_by_chrf(cand, refs_list)
        return {
            "sctid": ex.sctid,
            "preferred_term": ex.preferred_term,
            "candidate": cand,
            "best_ref": ex.ko_reference,
            "score": m["score"],
            "exact": exact,
            "chrf": best_chrf,
            "source": ex.source,
            "sme_rating": ex.sme_rating,
            "feedback": m["feedback"][:240],
        }

    rows = [None] * len(examples)
    score_sum = 0.0
    exact_sum = 0
    chrf_sum = 0.0
    n_done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(_score_one, ex): i for i, ex in enumerate(examples)}
        for fut in as_completed(futs):
            i = futs[fut]
            r = fut.result()
            rows[i] = r
            score_sum += r["score"]
            exact_sum += r["exact"]
            chrf_sum += r["chrf"]
            n_done += 1
            if verbose and n_done % 25 == 0:
                print(f"  evaluated {n_done}/{len(examples)}: avg score so far = {score_sum/n_done:.3f}")
    n = len(examples)
    return {
        "n": n,
        "mean_score": score_sum / max(n, 1),
        "exact_match_pct": 100.0 * exact_sum / max(n, 1),
        "mean_chrf": chrf_sum / max(n, 1),
        "rows": rows,
    }
