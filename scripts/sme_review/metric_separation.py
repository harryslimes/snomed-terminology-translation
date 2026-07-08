#!/usr/bin/env python3
"""Which automatic metric best predicts SME acceptability?

The guide-eval showed distance-to-a-single-reference (chrF, semantic-vs-gold)
does not track SME quality: many valid translations differ from the reference.
A useful metric should score the translations the SME *accepted* higher than
the ones they marked PARTIAL/WRONG.

This ranks candidate metrics by how well they separate ACCEPTABLE from the
rest, measured as ROC AUC (P[metric(ACCEPTABLE) > metric(PARTIAL/WRONG)]).
0.5 = no separation; 1.0 = perfect; <0.5 = inverted.

Metrics tested (all computed on the ORIGINAL pipeline translation the SME
actually rated):
  xling_bge      source-anchored, reference-free: BGE-M3 cosine(EN source, KO output)
  backtrans_bge  reference-free: BGE-M3 cosine(EN source, EN back-translation)
  backtrans_chrf reference-free surface: chrF(EN source, EN back-translation)
  sem_to_corr    reference-based: BGE-M3 cosine(KO output, SME correction)   [corrected rows only]
  chrf_to_corr   reference-based surface: chrF(KO output, SME correction)     [corrected rows only]
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sacrebleu.metrics import CHRF

CHRF_METRIC = CHRF()
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


def enc(t: str) -> np.ndarray:
    if t not in _VEC:
        o = _bge().encode([t or " "], batch_size=1, max_length=256,
                          return_dense=True, return_sparse=False, return_colbert_vecs=False)
        v = np.asarray(o["dense_vecs"][0], np.float32)
        _VEC[t] = v / (float(np.linalg.norm(v)) + 1e-9)
    return _VEC[t]


def bge_cos(a: str, b: str) -> float:
    return float(enc(a) @ enc(b))


def chrf(a: str, b: str) -> float:
    return CHRF_METRIC.sentence_score(a or "", [b or ""]).score


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P[random positive scores above random negative] via Mann-Whitney U."""
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    allv = np.concatenate([pos, neg])
    ranks = pd.Series(allv).rank().to_numpy()
    r_pos = ranks[: len(pos)].sum()
    u = r_pos - len(pos) * (len(pos) + 1) / 2
    return u / (len(pos) * len(neg))


def main() -> None:
    df = pd.read_csv(Path("data/sme_review/2026-04-24/sme_labels_v1.csv"), dtype={"sctid": str})
    en = df["english_term"].fillna("")
    ko = df["pipeline_translation_ko"].fillna("")
    bt = df["pipeline_back_translation_en"].fillna("")
    corr = df["sme_corrected_ko"]

    df["xling_bge"] = [bge_cos(e, k) for e, k in zip(en, ko)]
    df["backtrans_bge"] = [bge_cos(e, b) for e, b in zip(en, bt)]
    df["backtrans_chrf"] = [chrf(b, e) for e, b in zip(en, bt)]
    df["sem_to_corr"] = [bge_cos(k, c) if isinstance(c, str) else np.nan
                         for k, c in zip(ko, corr)]
    df["chrf_to_corr"] = [chrf(k, c) if isinstance(c, str) else np.nan
                          for k, c in zip(ko, corr)]

    accept = df["sme_rating"] == "ACCEPTABLE"
    metrics = ["xling_bge", "backtrans_bge", "backtrans_chrf", "sem_to_corr", "chrf_to_corr"]

    print(f"n = {len(df)}  (ACCEPTABLE {accept.sum()}, PARTIAL/WRONG {(~accept).sum()})")
    print("Separation of ACCEPTABLE vs PARTIAL+WRONG, ranked by AUC:\n")
    print(f"{'metric':16} {'AUC':>6} {'mean_ACC':>9} {'mean_rest':>9} {'n':>4}  interpretation")
    rows = []
    for mname in metrics:
        v = df[[mname, "sme_rating"]].dropna()
        a = v[v["sme_rating"] == "ACCEPTABLE"][mname].to_numpy()
        r = v[v["sme_rating"] != "ACCEPTABLE"][mname].to_numpy()
        rows.append((mname, auc(a, r), a.mean() if len(a) else np.nan,
                     r.mean() if len(r) else np.nan, len(v)))
    for mname, a_uc, ma, mr, n in sorted(rows, key=lambda x: -x[1]):
        sep = "higher=better" if a_uc >= 0.5 else "INVERTED"
        print(f"{mname:16} {a_uc:>6.3f} {ma:>9.3f} {mr:>9.3f} {n:>4}  {sep}")

    df.to_csv("data/sme_review/2026-04-24/metric_separation.csv", index=False)
    print("\nwrote per-term metric values -> data/sme_review/2026-04-24/metric_separation.csv")


if __name__ == "__main__":
    main()
