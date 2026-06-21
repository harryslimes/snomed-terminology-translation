"""Dependency-light text-scoring helpers shared by the evaluate stage and the
DSPy/GEPA harness.

These used to live in scripts/optimization/dspy_translate.py, which imports
dspy → LiteLLM at module load; the evaluate stage only needs these two pure
functions, so they live here to keep evaluation free of that import chain
(and its Bedrock/SageMaker "botocore missing" warnings).
"""
from __future__ import annotations

import sacrebleu


def norm_text(s: str) -> str:
    """Normalize for exact-match: strip whitespace internally and externally."""
    return s.replace(" ", "").strip()


def best_ref_by_chrf(candidate: str, refs: list[str]) -> tuple[str, float]:
    """Return (best_ref, best_chrf_0_to_100)."""
    best_score = -1.0
    best_ref = refs[0]
    for r in refs:
        s = sacrebleu.sentence_chrf(candidate, [r]).score
        if s > best_score:
            best_score = s
            best_ref = r
    return best_ref, best_score
