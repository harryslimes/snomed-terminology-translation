#!/usr/bin/env python3
"""Score guide-iteration translations against the batch-1 SME gold.

Given per-guide translation CSVs (idx, ko) produced under identical model /
retrieval conditions, report:
  - mean chrF vs the SME gold (overall + on the rows the SME corrected), and
  - rule-adherence counters that measure whether the v5.2 rules were followed,
    computed only on the rows where each rule is *applicable* (so they are not
    diluted by irrelevant rows).

This is a lightweight guide-isolation A/B, not a tracked production run: the
model and no-RAG condition are held constant so the style guide is the only
variable. In-sample caveat: the v5.2 rules were derived from this same batch,
so this measures "were the rules encoded and followed", not held-out
generalisation (that needs batch 2).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import os

import numpy as np
import pandas as pd
from sacrebleu.metrics import CHRF

CHRF_METRIC = CHRF()


def chrf(hyp: str, ref: str) -> float:
    return CHRF_METRIC.sentence_score(hyp or "", [ref or ""]).score


# BGE-M3 dense cosine similarity — the same embedding the project's
# `cosine_similarity` scorer / GEPA metric uses (snomed_translation/gepa_metric.py).
# Runs on CPU; every vector is cached by text.
_BGE = None
_VEC: dict[str, np.ndarray] = {}


def _bge():
    global _BGE
    if _BGE is None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from FlagEmbedding import BGEM3FlagModel
        try:
            _BGE = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, devices="cpu")
        except TypeError:
            _BGE = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, device="cpu")
    return _BGE


def _enc(text: str) -> np.ndarray:
    if text not in _VEC:
        out = _bge().encode([text or " "], batch_size=1, max_length=256,
                            return_dense=True, return_sparse=False,
                            return_colbert_vecs=False)
        v = np.asarray(out["dense_vecs"][0], np.float32)
        _VEC[text] = v / (float(np.linalg.norm(v)) + 1e-9)
    return _VEC[text]


def semantic(hyp: str, ref: str) -> float:
    """Cosine similarity in [0,1]-ish (BGE dense vectors are ~non-negative)."""
    return float(_enc(hyp) @ _enc(ref))


def load_cands(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for p in paths:
        d = pd.read_csv(p, dtype={"idx": int})
        frames.append(d[["idx", "ko"]])
    out = pd.concat(frames).drop_duplicates("idx").sort_values("idx")
    out["ko"] = out["ko"].fillna("").str.strip()
    return out


# Rule-adherence probes: (name, applies(en) -> bool, ok(ko) -> bool).
RULES = {
    "solid_MRI": (
        lambda en: "magnetic resonance" in en.lower(),
        lambda ko: "자기공명" in ko and "자기 공명" not in ko,
    ),
    "solid_CT": (
        lambda en: "computed tomography" in en.lower(),
        lambda ko: "컴퓨터단층촬영" in ko and "컴퓨터 단층 촬영" not in ko,
    ),
    "solid_US": (
        lambda en: any(w in en.lower() for w in ("ultrasoun", "ultrasonograph", "echography")),
        lambda ko: "초음파검사" in ko or ("초음파" in ko and "초음파 검사" not in ko),
    ),
    "xray_as_Xseon": (
        lambda en: "x-ray" in en.lower(),
        lambda ko: ("X선" in ko or "x선" in ko) and "방사선 영상 촬영" not in ko,
    ),
    "whole_limb_native": (
        lambda en: any(w in en.lower() for w in ("upper limb", "lower limb",
                                                 "upper extremity", "lower extremity")),
        lambda ko: ("팔" in ko or "다리" in ko) and "위팔" not in ko and "아래팔" not in ko,
    ),
    "contrast_fronted": (
        lambda en: "contrast" in en.lower(),
        lambda ko: ko.strip().startswith("조영제"),
    ),
    "symptomatic_is_diagnostic": (
        lambda en: "symptomatic" in en.lower(),
        lambda ko: "진단" in ko and "증상치료" not in ko and "증상성" not in ko,
    ),
    "no_phonetic_gram": (
        # -graphy/-gram roots must not be rendered as *그램/*그래피/*니오 etc.
        lambda en: en.lower().rstrip().endswith(("gram", "graphy")),
        lambda ko: not any(s in ko for s in ("그램", "그래피", "니오그")),
    ),
}


def score(label: str, cands: pd.DataFrame, gold: pd.DataFrame) -> dict:
    m = gold.merge(cands, on="idx", how="left")
    m["ko"] = m["ko"].fillna("")
    m["chrf"] = [chrf(h, r) for h, r in zip(m["ko"], m["gold_ko"])]
    m["sem"] = [semantic(h, r) for h, r in zip(m["ko"], m["gold_ko"])]
    corrected = m[m["sme_corrected_ko"].notna()]
    rules = {}
    for name, (applies, ok) in RULES.items():
        app = m[m["english_term"].map(applies)]
        n = len(app)
        passed = int(app["ko"].map(ok).sum()) if n else 0
        rules[name] = (passed, n)
    by_rating = {r: (round(g["sem"].mean(), 4), round(g["chrf"].mean(), 2), len(g))
                 for r, g in m.groupby("sme_rating")}
    return {
        "label": label,
        "n": len(m),
        "sem_all": round(m["sem"].mean(), 4),
        "sem_corrected": round(corrected["sem"].mean(), 4),
        "chrf_all": round(m["chrf"].mean(), 2),
        "chrf_corrected": round(corrected["chrf"].mean(), 2),
        "n_corrected": len(corrected),
        "empty_outputs": int((m["ko"] == "").sum()),
        "by_rating": by_rating,
        "rules": rules,
        "_merged": m,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gold", type=Path, required=True)
    p.add_argument("--v51", type=Path, nargs="+", required=True)
    p.add_argument("--v52", type=Path, nargs="+", required=True)
    p.add_argument("--dump", type=Path, default=None,
                   help="optional: write a side-by-side per-term CSV")
    args = p.parse_args()

    gold = pd.read_csv(args.gold, dtype={"idx": int})
    res = [score("v5.1", load_cands(args.v51), gold),
           score("v5.2", load_cands(args.v52), gold)]

    print("PRIMARY — BGE-M3 semantic cosine (generated vs SME canonical):")
    print(f"{'guide':6} {'sem(all)':>9} {'sem(corr)':>10} {'chrF(all)':>10} {'chrF(corr)':>11} {'empty':>6}")
    for r in res:
        print(f"{r['label']:6} {r['sem_all']:>9} {r['sem_corrected']:>10} "
              f"{r['chrf_all']:>10} {r['chrf_corrected']:>11} {r['empty_outputs']:>6}")
    print("\nsemantic cosine by SME rating (v5.1 -> v5.2, n):")
    for rating in ("ACCEPTABLE", "PARTIAL", "WRONG"):
        a = res[0]["by_rating"].get(rating); b = res[1]["by_rating"].get(rating)
        if a and b:
            print(f"  {rating:11} n={a[2]:<3}  {a[0]:.4f} -> {b[0]:.4f}")
    print(f"\nrule adherence (passed / applicable rows):")
    print(f"{'rule':28} {'v5.1':>10} {'v5.2':>10}")
    for name in RULES:
        a = res[0]["rules"][name]; b = res[1]["rules"][name]
        print(f"{name:28} {f'{a[0]}/{a[1]}':>10} {f'{b[0]}/{b[1]}':>10}")

    if args.dump:
        m1, m2 = res[0]["_merged"], res[1]["_merged"]
        out = m1[["idx", "english_term", "sme_rating", "gold_ko"]].copy()
        out["v51_ko"] = m1["ko"].values
        out["v52_ko"] = m2["ko"].values
        out["v51_sem"] = m1["sem"].round(3).values
        out["v52_sem"] = m2["sem"].round(3).values
        out["v51_chrf"] = m1["chrf"].round(1).values
        out["v52_chrf"] = m2["chrf"].round(1).values
        out["sem_delta"] = (m2["sem"].values - m1["sem"].values).round(3)
        out.to_csv(args.dump, index=False)
        print(f"\nwrote per-term dump -> {args.dump}")


if __name__ == "__main__":
    main()
