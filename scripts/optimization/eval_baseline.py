#!/usr/bin/env python3
"""Baseline DSPy evaluation: run the v5 (or any) style guide through the DSPy
scaffold on a chosen split, and report mean score / exact-match / chrF.

This is the smoke test that the DSPy scaffold gives results consistent with
the existing translation pipeline. Run it BEFORE invoking GEPA.

Usage:
    python scripts/optimization/eval_baseline.py \
        --style-guide style_guide/style_guide_ko_v5.md \
        --split data/evals/korean/dspy_splits/dev.csv \
        --output data/evals/korean/dspy_baseline_v5_dev.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import dspy  # noqa: E402

from scripts.optimization.dspy_translate import (  # noqa: E402
    build_lm, build_translator, evaluate, load_split,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--style-guide", required=True)
    p.add_argument("--split", required=True)
    p.add_argument("--lookup-cache",
                   default="data/sme_review/2026-04-24/lookup_cache.json")
    p.add_argument("--output", default=None,
                   help="Optional per-row CSV output.")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--base-url", default=None,
                   help="Override LM API base. Include /v1 suffix.")
    p.add_argument("--model-id", default=None,
                   help="Override model id (e.g. 'qwen3.7-max').")
    p.add_argument("--api-key-env", default=None,
                   help="Env var holding the API key (e.g. DASHSCOPE_API_KEY).")
    p.add_argument("--max-tokens", type=int, default=128)
    p.add_argument("--disable-thinking", action="store_true",
                   help="For Qwen-style thinking models: send enable_thinking=false.")
    p.add_argument("--drop-stop", action="store_true",
                   help="Drop stop sequences (needed for reasoning models that emit \\n\\n in reasoning).")
    p.add_argument("--topn", type=int, default=5)
    args = p.parse_args()

    import os
    if args.base_url:
        os.environ["VLLM_BASE_URL"] = args.base_url

    lm_kwargs = {"max_tokens": args.max_tokens}
    if args.model_id:
        lm_kwargs["model_id"] = args.model_id
    if args.base_url:
        lm_kwargs["base_url"] = args.base_url
    if args.api_key_env:
        lm_kwargs["api_key"] = os.environ[args.api_key_env]
    if args.disable_thinking:
        # Dashscope respects top-level enable_thinking; vLLM (with
        # --reasoning-parser qwen3) needs chat_template_kwargs.
        lm_kwargs["extra_body"] = {
            "enable_thinking": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    if args.drop_stop:
        lm_kwargs["drop_stop_sequences"] = True

    lm = build_lm(**lm_kwargs)
    dspy.settings.configure(lm=lm)
    translator = build_translator(
        style_guide_path=args.style_guide,
        lookup_cache_path=args.lookup_cache,
        topn=args.topn,
    )

    examples = load_split(args.split)
    if args.limit:
        examples = examples[: args.limit]

    print(f"Evaluating {len(examples)} examples from {args.split}")
    print(f"  style guide: {args.style_guide}")
    print(f"  lookup cache: {args.lookup_cache}")
    t0 = time.monotonic()
    result = evaluate(translator, examples, verbose=True)
    elapsed = time.monotonic() - t0

    print(f"\n=== Result ({result['n']} examples, {elapsed:.0f}s) ===")
    print(f"  mean composite score: {result['mean_score']:.3f}")
    print(f"  exact-match (ignoring spaces): {result['exact_match_pct']:.1f}%")
    print(f"  mean chrF: {result['mean_chrf']:.1f}")

    # Break down by source (KR vs SME) if mixed
    kr = [r for r in result["rows"] if r["source"] == "KR"]
    sme = [r for r in result["rows"] if r["source"] == "SME"]
    if kr and sme:
        kr_exact = sum(r["exact"] for r in kr) / len(kr) * 100
        sme_exact = sum(r["exact"] for r in sme) / len(sme) * 100
        kr_chrf = sum(r["chrf"] for r in kr) / len(kr)
        sme_chrf = sum(r["chrf"] for r in sme) / len(sme)
        print(f"\n  By source:")
        print(f"    KR (n={len(kr):>3d}): exact={kr_exact:5.1f}%  chrF={kr_chrf:5.1f}")
        print(f"    SME (n={len(sme):>3d}): exact={sme_exact:5.1f}%  chrF={sme_chrf:5.1f}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        fields = ["sctid", "preferred_term", "candidate", "best_ref",
                  "score", "exact", "chrf", "source", "sme_rating", "feedback"]
        with open(args.output, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for row in result["rows"]:
                w.writerow({k: row.get(k, "") for k in fields})
        print(f"\nPer-row results written to {args.output}")


if __name__ == "__main__":
    main()
