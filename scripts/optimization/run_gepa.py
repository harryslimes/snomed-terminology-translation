#!/usr/bin/env python3
"""Run DSPy GEPA on the SNOMED EN→KO radiology translator.

Seeds the instructions from a chosen style guide (default: v5.1) and lets
GEPA's reflective mutation propose improvements. The optimized instructions
are saved to `style_guide/style_guide_ko_<tag>.md` so they can be lifted
back into production unchanged.

Usage:
    python scripts/optimization/run_gepa.py --auto light --tag gepa_light
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import dspy  # noqa: E402
from dspy.teleprompt import GEPA  # noqa: E402

from scripts.optimization.dspy_translate import (  # noqa: E402
    build_lm, build_translator, evaluate, load_split, make_metric,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed-style-guide",
                   default="style_guide/style_guide_ko_v5_1.md")
    p.add_argument("--train-split",
                   default="data/evals/korean/dspy_splits/train.csv")
    p.add_argument("--dev-split",
                   default="data/evals/korean/dspy_splits/dev.csv")
    p.add_argument("--lookup-cache",
                   default="data/sme_review/2026-04-24/lookup_cache.json")
    p.add_argument("--auto", choices=["light", "medium", "heavy"],
                   default="light",
                   help="GEPA budget preset.")
    p.add_argument("--reflection-model", default=None,
                   help="LM for the reflective mutation step. Default: same as task LM.")
    p.add_argument("--reflection-base-url", default=None,
                   help="Override api_base for the reflection LM (e.g. Dashscope).")
    p.add_argument("--reflection-api-key-env", default=None,
                   help="Env var holding reflection LM API key (e.g. DASHSCOPE_API_KEY).")
    p.add_argument("--reflection-disable-thinking", action="store_true",
                   help="Send enable_thinking=false to a Qwen-style reflection LM.")
    p.add_argument("--hints", default=None,
                   help="YAML of reflective-feedback hints (configs/hints/ko.yaml). "
                        "Default: bundled Korean hints.")
    p.add_argument("--hard-rules", default=None,
                   help="YAML of non-negotiable hard rules (configs/hard_rules/ko.yaml). "
                        "freeze=true rules are injected into the prompt out of GEPA's "
                        "reach; enforce=true rules apply a metric penalty.")
    p.add_argument("--tag", default="gepa_light",
                   help="Output style-guide filename suffix.")
    p.add_argument("--train-limit", type=int, default=None,
                   help="Cap train set for fast iteration.")
    p.add_argument("--dev-limit", type=int, default=None)
    p.add_argument("--max-metric-calls", type=int, default=None,
                   help="Override GEPA's metric-call budget directly.")
    args = p.parse_args()

    # 1. LMs ----------------------------------------------------------------
    task_lm = build_lm()
    dspy.settings.configure(lm=task_lm)
    if args.reflection_model:
        rkwargs = {"temperature": 1.0, "max_tokens": 4000}
        if args.reflection_base_url:
            rkwargs["api_base"] = args.reflection_base_url
        if args.reflection_api_key_env:
            import os
            rkwargs["api_key"] = os.environ[args.reflection_api_key_env]
        if args.reflection_disable_thinking:
            rkwargs["extra_body"] = {"enable_thinking": False}
        reflection_lm = dspy.LM(args.reflection_model, **rkwargs)
    else:
        # Same gemma — workable for cheap exploration; not as strong as Sonnet
        # would be, but no Anthropic key needed.
        reflection_lm = dspy.LM(
            f"openai/cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit",
            api_base="http://localhost:8083/v1",
            api_key="EMPTY",
            temperature=0.7,
            max_tokens=4000,
        )

    # 2. Data ---------------------------------------------------------------
    train = load_split(args.train_split)
    dev = load_split(args.dev_split)
    if args.train_limit:
        train = train[: args.train_limit]
    if args.dev_limit:
        dev = dev[: args.dev_limit]
    print(f"train={len(train)} dev={len(dev)} (seed: {args.seed_style_guide})")

    # 3. Seed translator ----------------------------------------------------
    translator = build_translator(
        style_guide_path=args.seed_style_guide,
        lookup_cache_path=args.lookup_cache,
        hard_rules=args.hard_rules,
    )
    metric = make_metric(hints=args.hints, hard_rules=args.hard_rules)
    if args.hard_rules:
        print(f"hard rules: {args.hard_rules}")

    # 4. Pre-GEPA baseline on dev for a clean before/after ------------------
    print("\n--- Pre-GEPA dev baseline ---")
    t0 = time.monotonic()
    pre = evaluate(translator, dev)
    print(f"  mean_score={pre['mean_score']:.3f} exact={pre['exact_match_pct']:.1f}% chrF={pre['mean_chrf']:.1f}  ({time.monotonic()-t0:.0f}s)")

    # 5. GEPA ---------------------------------------------------------------
    gepa_kwargs = dict(
        metric=metric,
        reflection_lm=reflection_lm,
        track_stats=True,
    )
    if args.max_metric_calls is not None:
        gepa_kwargs["max_metric_calls"] = args.max_metric_calls
    else:
        gepa_kwargs["auto"] = args.auto

    print(f"\n--- Running GEPA (auto={args.auto!r}) ---")
    optimizer = GEPA(**gepa_kwargs)
    t_start = time.monotonic()
    optimized = optimizer.compile(
        translator,
        trainset=train,
        valset=dev,
    )
    t_elapsed = time.monotonic() - t_start
    print(f"\nGEPA done in {t_elapsed:.0f}s")

    # 6. Post-GEPA eval on dev (sanity; held-out comes later) ---------------
    print("\n--- Post-GEPA dev evaluation ---")
    post = evaluate(optimized, dev)
    print(f"  mean_score={post['mean_score']:.3f} exact={post['exact_match_pct']:.1f}% chrF={post['mean_chrf']:.1f}")
    print(f"\n  Δ mean_score: {post['mean_score'] - pre['mean_score']:+.3f}")
    print(f"  Δ exact:      {post['exact_match_pct'] - pre['exact_match_pct']:+.1f} pp")
    print(f"  Δ chrF:       {post['mean_chrf'] - pre['mean_chrf']:+.1f}")

    # 7. Save the optimized instruction (= optimized "style guide") ---------
    out_md = Path("style_guide") / f"style_guide_ko_{args.tag}.md"
    out_md.write_text(optimized.predictor.signature.instructions, encoding="utf-8")
    print(f"\nOptimized instruction → {out_md} ({len(optimized.predictor.signature.instructions)} chars)")

    # 8. Persist run metadata + per-row diagnostics -------------------------
    meta = {
        "seed_style_guide": args.seed_style_guide,
        "auto": args.auto,
        "max_metric_calls": args.max_metric_calls,
        "train_n": len(train),
        "dev_n": len(dev),
        "task_lm": task_lm.model,
        "reflection_lm": reflection_lm.model,
        "elapsed_sec": t_elapsed,
        "pre": {
            "mean_score": pre["mean_score"],
            "exact_pct": pre["exact_match_pct"],
            "chrf": pre["mean_chrf"],
        },
        "post": {
            "mean_score": post["mean_score"],
            "exact_pct": post["exact_match_pct"],
            "chrf": post["mean_chrf"],
        },
    }
    out_meta = Path("data/evals/korean") / f"gepa_run_{args.tag}.json"
    out_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"Run metadata → {out_meta}")


if __name__ == "__main__":
    main()
