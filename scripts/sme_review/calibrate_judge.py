#!/usr/bin/env python3
"""Calibrate the SME-acceptability judge against the batch-1 SME labels.

The judge (configs/judge/sme_acceptability_judge_v1.md) emits a continuous
`score` per translation. This fits the decision threshold that best reproduces
the SME accept/reject verdict, and reports how good the judge is as a metric:

  - AUC: P[score(ACCEPTABLE) > score(PARTIAL/WRONG)] — threshold-free ranking.
  - Calibrated threshold (accuracy-maximising and Youden-J) on accept-vs-rest.
  - At the chosen threshold: accuracy, precision, recall, Cohen's kappa.
  - 3-way label agreement, for context.

Persists the calibration (threshold + metrics + prompt version) to a JSON
artifact so downstream evals score with a fixed, reproducible cutoff.

Inputs:
  --judge   one or more CSVs with columns idx,label,score (judge outputs).
  --labels  the SME label dataset (sme_labels_v1.csv), joined on a 1-based idx
            assigned by row order (matching how the judge input was built).
  --prompt-version  string recorded in the artifact (default judge_v1).
  --out     calibration JSON path.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    u = ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2
    return float(u / (len(pos) * len(neg)))


def cohen_kappa(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, int), np.asarray(b, int)
    n = len(a)
    po = (a == b).mean()
    pe = sum((a == c).mean() * (b == c).mean() for c in (0, 1))
    return float((po - pe) / (1 - pe)) if pe != 1 else 1.0


def load_judge(paths: list[Path]) -> pd.DataFrame:
    d = pd.concat([pd.read_csv(p) for p in paths]).drop_duplicates("idx")
    d["label"] = d["label"].astype(str).str.upper().str.strip()
    d["score"] = pd.to_numeric(d["score"], errors="coerce")
    return d[["idx", "label", "score"]].sort_values("idx")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--judge", type=Path, nargs="+", required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.add_argument("--prompt-version", default="sme_acceptability_judge_v1")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    lab = pd.read_csv(args.labels, dtype={"sctid": str}).reset_index(drop=True)
    lab["idx"] = range(1, len(lab) + 1)
    d = lab.merge(load_judge(args.judge), on="idx", how="inner")
    if d["score"].isna().any():
        raise ValueError(f"{int(d['score'].isna().sum())} judge scores failed to parse")

    ord3 = {"WRONG": 0, "PARTIAL": 1, "ACCEPTABLE": 2}
    accept = (d["sme_rating"] == "ACCEPTABLE").to_numpy()
    pos, neg = d.loc[accept, "score"].to_numpy(), d.loc[~accept, "score"].to_numpy()
    a_uc = auc(pos, neg)

    # Fit thresholds on accept-vs-rest.
    ts = np.round(np.arange(0.30, 1.00, 0.01), 2)
    acc_t = max(ts, key=lambda t: ((d["score"].to_numpy() >= t) == accept).mean())
    youden_t = max(ts, key=lambda t: (
        ((d["score"].to_numpy() >= t) & accept).sum() / max(accept.sum(), 1)         # TPR
        - ((d["score"].to_numpy() >= t) & ~accept).sum() / max((~accept).sum(), 1))) # FPR

    def at(t: float) -> dict:
        pred = d["score"].to_numpy() >= t
        tp = int((pred & accept).sum()); fp = int((pred & ~accept).sum())
        fn = int((~pred & accept).sum())
        return {
            "threshold": float(t),
            "accuracy": round(float((pred == accept).mean()), 4),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "kappa": round(cohen_kappa(pred.astype(int), accept.astype(int)), 4),
        }

    judge_ord = d["label"].map(ord3)
    sme_ord = d["sme_rating"].map(ord3)
    cal = {
        "prompt_version": args.prompt_version,
        "n": len(d),
        "class_counts": d["sme_rating"].value_counts().to_dict(),
        "auc_accept_vs_rest": round(a_uc, 4),
        "score_by_rating": {r: round(float(g["score"].mean()), 4)
                            for r, g in d.groupby("sme_rating")},
        "threshold_accuracy_max": at(acc_t),
        "threshold_youden_j": at(youden_t),
        "naive_label_binary_accuracy": round(
            float(((judge_ord >= 2) == (sme_ord >= 2)).mean()), 4),
        "exact_3way_agreement": round(float((judge_ord == sme_ord).mean()), 4),
        "spearman_ord": round(float(judge_ord.corr(sme_ord, method="spearman")), 4),
        "confusion_sme_rows_judge_cols": pd.crosstab(
            d["sme_rating"], d["label"]).to_dict(),
    }
    args.out.write_text(json.dumps(cal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"AUC (accept vs rest)          {cal['auc_accept_vs_rest']}")
    print(f"score by rating               {cal['score_by_rating']}")
    print(f"accuracy-max threshold        {at(acc_t)}")
    print(f"Youden-J threshold            {at(youden_t)}")
    print(f"naive label binary accuracy   {cal['naive_label_binary_accuracy']}")
    print(f"3-way agreement / Spearman    {cal['exact_3way_agreement']} / {cal['spearman_ord']}")
    print(f"\nwrote calibration -> {args.out}")


if __name__ == "__main__":
    main()
