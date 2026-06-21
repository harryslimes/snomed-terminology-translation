#!/usr/bin/env python3
"""Sweep sampling parameters on the dev set.

Two modes:
  - single-sample sweep: vary temperature / top_p / top_k, record dev scores.
  - self-consistency: sample N candidates at temp > 0 and take the most
    frequent normalized form (whitespace-stripped majority vote). Strong
    baseline for stabilising stochastic output.

Outputs a markdown summary + per-row CSVs to data/evals/korean/.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import dspy  # noqa: E402
import sacrebleu  # noqa: E402

from scripts.optimization.dspy_translate import (  # noqa: E402
    build_lm, build_translator, load_split,
    _best_ref_by_chrf, _norm,
)


# Sampling configurations to evaluate. Each tuple: (label, kwargs to build_lm).
DEFAULT_CONFIGS = [
    ("temp=0 (current default)",      {"temperature": 0.0}),
    ("temp=0.3",                      {"temperature": 0.3}),
    ("temp=0.7",                      {"temperature": 0.7}),
    ("temp=1.0",                      {"temperature": 1.0}),
    ("Gemma-recommended (1.0/0.95/64)", {"temperature": 1.0, "top_p": 0.95, "top_k": 64}),
    ("temp=0.7, top_p=0.95",          {"temperature": 0.7, "top_p": 0.95}),
]


def score_one(translator, ex):
    try:
        pred = translator(sctid=ex.sctid, preferred_term=ex.preferred_term)
        cand = pred.korean
    except Exception as exc:
        return {"sctid": ex.sctid, "candidate": f"ERROR: {exc}",
                "exact": 0, "chrf": 0.0, "source": ex.source}
    refs = [r for r in (ex.ko_all or "").split("|") if r.strip()] or [ex.ko_reference]
    exact = 1 if _norm(cand) in {_norm(r) for r in refs} else 0
    _, chrf = _best_ref_by_chrf(cand, refs)
    return {"sctid": ex.sctid, "candidate": cand,
            "exact": exact, "chrf": chrf, "source": ex.source}


def run_eval(translator, examples, concurrency=8):
    rows = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(score_one, translator, ex) for ex in examples]
        for fut in as_completed(futs):
            rows.append(fut.result())
    return rows


def summarise(rows):
    n = len(rows)
    exact = sum(r["exact"] for r in rows) / n * 100
    chrf = sum(r["chrf"] for r in rows) / n
    kr = [r for r in rows if r["source"] == "KR"]
    sme = [r for r in rows if r["source"] == "SME"]
    return {
        "n": n,
        "exact": exact,
        "chrf": chrf,
        "kr_exact": sum(r["exact"] for r in kr) / len(kr) * 100 if kr else 0.0,
        "kr_chrf":  sum(r["chrf"]  for r in kr) / len(kr)        if kr else 0.0,
        "sme_exact":sum(r["exact"] for r in sme) / len(sme) * 100 if sme else 0.0,
        "sme_chrf": sum(r["chrf"]  for r in sme) / len(sme)        if sme else 0.0,
    }


def run_self_consistency(seed_kwargs, n_samples, examples,
                          style_guide_path, lookup_cache_path,
                          base_url, model_id, api_key, extra_body,
                          concurrency=8):
    """For each example, sample N candidates and majority-vote on whitespace-
    normalized form. Tie-break: longest distinct candidate (preserves
    information). Return per-row rows in the same shape as run_eval()."""
    # Per-sample, build a fresh translator (each with its own LM at the
    # chosen temperature; sampling is non-deterministic, so each call gives
    # a different output without us having to set a seed).
    sample_rows = [[] for _ in examples]  # sample_rows[i] = [cand_1, cand_2, ...]

    for s in range(n_samples):
        lm = build_lm(
            model_id=model_id, base_url=base_url, api_key=api_key,
            extra_body=extra_body, max_tokens=256,
            **seed_kwargs,
        )
        dspy.settings.configure(lm=lm)
        translator = build_translator(style_guide_path, lookup_cache_path)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(score_one, translator, ex): i
                    for i, ex in enumerate(examples)}
            for fut in as_completed(futs):
                i = futs[fut]
                sample_rows[i].append(fut.result())
        print(f"  sample {s+1}/{n_samples} done")

    final_rows = []
    for i, samples in enumerate(sample_rows):
        cands = [s["candidate"] for s in samples
                 if not s["candidate"].startswith("ERROR")]
        if not cands:
            final_rows.append(samples[0])
            continue
        norms = [_norm(c) for c in cands]
        # Pick the most frequent normalized form; among raws sharing that
        # form, take the most common literal string (preserves spacing).
        top_norm = Counter(norms).most_common(1)[0][0]
        raws_for_top = [c for c, nc in zip(cands, norms) if nc == top_norm]
        winner = Counter(raws_for_top).most_common(1)[0][0]
        ex = examples[i]
        refs = [r for r in (ex.ko_all or "").split("|") if r.strip()] or [ex.ko_reference]
        exact = 1 if _norm(winner) in {_norm(r) for r in refs} else 0
        _, chrf = _best_ref_by_chrf(winner, refs)
        final_rows.append({
            "sctid": ex.sctid, "candidate": winner,
            "exact": exact, "chrf": chrf, "source": ex.source,
            "n_distinct": len(set(norms)),
            "vote_majority": Counter(norms)[top_norm],
        })
    return final_rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--style-guide",
                   default="style_guide/style_guide_ko_v5_1.md")
    p.add_argument("--split",
                   default="data/evals/korean/dspy_splits/dev.csv")
    p.add_argument("--lookup-cache",
                   default="data/sme_review/2026-04-24/lookup_cache.json")
    p.add_argument("--base-url",
                   default="http://localhost:8083/v1")
    p.add_argument("--model-id",
                   default="cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit")
    p.add_argument("--api-key-env", default=None)
    p.add_argument("--disable-thinking", action="store_true")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out-prefix",
                   default="data/evals/korean/sweep_gemma_v51")
    p.add_argument("--self-consistency", type=int, default=0,
                   help="If > 0, run N-sample majority vote (uses temp from "
                        "the configuration label '__sc__').")
    p.add_argument("--sc-temp", type=float, default=0.7)
    p.add_argument("--sc-top-p", type=float, default=0.95)
    p.add_argument("--sc-top-k", type=int, default=64)
    args = p.parse_args()

    examples = load_split(args.split)
    if args.limit:
        examples = examples[: args.limit]

    api_key = os.environ[args.api_key_env] if args.api_key_env else "EMPTY"
    extra_body = None
    if args.disable_thinking:
        extra_body = {"enable_thinking": False,
                      "chat_template_kwargs": {"enable_thinking": False}}

    results: list[tuple[str, dict, str]] = []  # (label, summary, csv path)

    # ----- single-sample sweep ------------------------------------------------
    for label, lm_kwargs in DEFAULT_CONFIGS:
        print(f"\n=== {label} ===")
        lm = build_lm(
            model_id=args.model_id, base_url=args.base_url, api_key=api_key,
            max_tokens=256, extra_body=extra_body, **lm_kwargs,
        )
        dspy.settings.configure(lm=lm)
        translator = build_translator(args.style_guide, args.lookup_cache)
        t0 = time.monotonic()
        rows = run_eval(translator, examples, args.concurrency)
        s = summarise(rows)
        elapsed = time.monotonic() - t0
        print(f"  n={s['n']} exact={s['exact']:.1f}% chrF={s['chrf']:.1f}  "
              f"KR exact={s['kr_exact']:.1f}% chrF={s['kr_chrf']:.1f}  "
              f"SME exact={s['sme_exact']:.1f}% chrF={s['sme_chrf']:.1f}  "
              f"({elapsed:.0f}s)")
        out_csv = f"{args.out_prefix}_{label.replace(' ','_').replace('=','').replace('(','').replace(')','').replace('/','_').replace(',','')}.csv"
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sctid", "candidate", "exact", "chrf", "source"])
            w.writeheader(); w.writerows(rows)
        results.append((label, s, out_csv))

    # ----- self-consistency ---------------------------------------------------
    if args.self_consistency:
        label = f"self-consistency N={args.self_consistency} (temp={args.sc_temp})"
        print(f"\n=== {label} ===")
        t0 = time.monotonic()
        rows = run_self_consistency(
            seed_kwargs={"temperature": args.sc_temp,
                          "top_p": args.sc_top_p,
                          "top_k": args.sc_top_k},
            n_samples=args.self_consistency,
            examples=examples,
            style_guide_path=args.style_guide,
            lookup_cache_path=args.lookup_cache,
            base_url=args.base_url, model_id=args.model_id,
            api_key=api_key, extra_body=extra_body,
            concurrency=args.concurrency,
        )
        s = summarise(rows)
        elapsed = time.monotonic() - t0
        print(f"  n={s['n']} exact={s['exact']:.1f}% chrF={s['chrf']:.1f}  "
              f"KR exact={s['kr_exact']:.1f}% chrF={s['kr_chrf']:.1f}  "
              f"SME exact={s['sme_exact']:.1f}% chrF={s['sme_chrf']:.1f}  "
              f"({elapsed:.0f}s)")
        out_csv = f"{args.out_prefix}_sc_n{args.self_consistency}.csv"
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sctid", "candidate", "exact", "chrf",
                                              "source", "n_distinct", "vote_majority"])
            w.writeheader(); w.writerows(rows)
        results.append((label, s, out_csv))

    # ----- summary table ------------------------------------------------------
    print("\n" + "="*100)
    print(f"{'config':<40s} {'exact%':>7s} {'chrF':>6s}  {'KR exact':>9s} {'KR chrF':>8s}  {'SME exact':>10s} {'SME chrF':>9s}")
    print("-"*100)
    for label, s, _ in results:
        print(f"{label:<40s} {s['exact']:>6.1f}% {s['chrf']:>6.1f}  "
              f"{s['kr_exact']:>8.1f}% {s['kr_chrf']:>8.1f}  "
              f"{s['sme_exact']:>9.1f}% {s['sme_chrf']:>9.1f}")


if __name__ == "__main__":
    main()
