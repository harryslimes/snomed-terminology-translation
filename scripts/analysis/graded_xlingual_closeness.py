"""Graded cross-lingual closeness for NON-exact-match translations.

Prior work (note-direct-xlingual-verify) tested embedding similarity only as a
BINARY error detector. This asks the user's question instead: as a GRADED
partial-credit score, how close are translations when they are NOT an exact
string match — and how badly do exact-match / chrF understate quality there?

Signals per candidate translation:
  sim_ko   cos(candidate_KO, gold_KO)         -- KO<->KO graded score (needs a ref)
  sim_en   cos(candidate_KO, source_EN)       -- EN<->KO direct (reference-free)
  rr_en    rank-normalised sim_en             -- controls BGE cross-lingual compression
  chrf     chrF(candidate_KO, gold_KO)         -- surface metric, for contrast

Anchors: exact-match items (candidate == gold) pin the "known-correct" end of
each signal. We then read where non-exact items fall relative to that anchor.

Env: semi-automated-research/.venv (torch+CUDA, FlagEmbedding, BGE-M3).
Run from snomed-terminology-translation/:
    python scripts/analysis/graded_xlingual_closeness.py
"""
from __future__ import annotations
import csv, sys
import numpy as np

LABELS = "../wizard-data/eval_inputs/kr_candidates_labels.csv"      # sctid,candidate,ko_reference
SOURCE = "data/evals/korean/procedure_eval_set.csv"                  # sctid,preferred_term,hierarchy,ko_reference
OUTDIR = "../wizard-data/eval_inputs"


def norm(s: str) -> str:
    return (s or "").replace(" ", "").strip().lower()


def chrf_score(hyp: str, ref: str) -> float:
    import sacrebleu
    return sacrebleu.sentence_chrf(hyp, [ref]).score / 100.0


def auc(score, y) -> float:
    score = np.asarray(score, float); y = np.asarray(y, int)
    p, n = score[y == 1], score[y == 0]
    if not len(p) or not len(n):
        return float("nan")
    return float((p[:, None] > n[None, :]).mean() + 0.5 * (p[:, None] == n[None, :]).mean())


def main() -> None:
    src = {r["sctid"]: r for r in csv.DictReader(open(SOURCE))}
    rows = []
    for r in csv.DictReader(open(LABELS)):
        s = src.get(r["sctid"])
        if not s or not r["candidate"] or not r["ko_reference"]:
            continue
        rows.append({
            "sctid": r["sctid"], "en": s["preferred_term"], "hier": s.get("hierarchy", ""),
            "cand": r["candidate"], "gold": r["ko_reference"],
            "exact": norm(r["candidate"]) == norm(r["ko_reference"]),
        })
    n = len(rows)
    print(f"n={n}  exact={sum(r['exact'] for r in rows)}  non-exact={sum(not r['exact'] for r in rows)}")

    from agent.qdrant_store import BGEM3Embedder
    emb = BGEM3Embedder()

    def enc(texts):
        v, _ = emb.encode_documents(list(texts))
        v = np.asarray(v, np.float32)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)

    cand = enc([r["cand"] for r in rows])
    gold = enc([r["gold"] for r in rows])
    en = enc([r["en"] for r in rows])

    sim_ko = (cand * gold).sum(1)
    sim_en = (cand * en).sum(1)
    sim_en_goldko = (gold * en).sum(1)          # known-good KO vs its EN: the EN<->KO ceiling

    # rank-normalised EN<->KO: for each candidate, percentile-rank of its OWN source
    # EN among all sources by similarity to the candidate KO. Robust to the global
    # compression that flattens absolute cross-lingual cosine.
    S = cand @ en.T                              # [n_cand, n_en]
    own = np.diag(S).copy()
    rr_en = (S < own[:, None]).mean(1)           # fraction of other EN this cand beats -> [0,1]

    exact = np.array([r["exact"] for r in rows])
    ne = ~exact

    def stats(name, x):
        print(f"  {name:26s} exact μ={x[exact].mean():.3f}  non-exact μ={x[ne].mean():.3f}  "
              f"non-exact p10={np.percentile(x[ne],10):.3f} p50={np.percentile(x[ne],50):.3f}")

    print("\n== signal means (exact anchors vs non-exact) ==")
    stats("sim_ko  (cand vs gold KO)", sim_ko)
    stats("sim_en  (cand vs EN)", sim_en)
    stats("rr_en   (rank-norm EN)", rr_en)
    stats("sim_en_goldko (gold vs EN)", sim_en_goldko)

    # --- metric-penalty quantification -------------------------------------
    # Calibrate a "semantically equivalent" threshold from the exact anchors: the
    # 5th-percentile sim_ko among items whose candidate is a *near* variant of gold
    # (chrf>=0.9 but not exact) approximates the valid-synonym floor. Fall back to
    # a conservative fixed 0.90 if too few near-variants.
    chrf = np.array([chrf_score(r["cand"], r["gold"]) for r in rows])
    near = ne & (chrf >= 0.9)
    tau = float(np.percentile(sim_ko[near], 5)) if near.sum() >= 30 else 0.90
    valid = ne & (sim_ko >= tau)
    print(f"\n== metric penalty on the {ne.sum()} NON-exact items (valid-synonym τ={tau:.3f}) ==")
    print(f"  semantically-equivalent (sim_ko>=τ): {valid.sum()}  "
          f"= {100*valid.sum()/ne.sum():.1f}% of non-exact, {100*valid.sum()/n:.1f}% of all")
    print(f"  chrF on those valid synonyms: μ={chrf[valid].mean():.3f}  "
          f"(exact-match would score 1.0; chrF wrongly penalises these)")
    print(f"  fraction of ALL items exact-match calls 'wrong' that are actually valid: "
          f"{100*valid.sum()/(ne.sum()):.1f}%")

    # --- can EN<->KO stand in where there's no Korean reference? ------------
    # Ground "semantically correct" by the KO<->KO score (the strong reference
    # signal), then ask how well the reference-FREE EN signals recover it.
    y_ok = (sim_ko >= tau).astype(int)
    print("\n== reference-free recovery of the KO<->KO 'correct' label (non-exact only) ==")
    for nm, sig in [("sim_en (raw EN<->KO)", sim_en), ("rr_en (rank-norm EN<->KO)", rr_en)]:
        print(f"  AUC {nm:26s} = {auc(sig[ne], y_ok[ne]):.3f}")

    # --- by hierarchy -------------------------------------------------------
    print("\n== non-exact valid-synonym rate by hierarchy ==")
    hiers = sorted({r["hier"] for r in rows})
    for h in hiers:
        m = ne & np.array([r["hier"] == h for r in rows])
        if m.sum() < 20:
            continue
        print(f"  {h:22s} n={m.sum():4d}  valid={100*(m&valid).sum()/m.sum():5.1f}%  "
              f"sim_ko μ={sim_ko[m].mean():.3f}")

    # --- dump examples: chrF near 0 but semantically equivalent -------------
    order = np.argsort(chrf + (~valid) * 9)      # valid synonyms, lowest chrF first
    out = f"{OUTDIR}/xlingual_penalty_examples.csv"
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sctid", "en", "candidate", "gold", "chrf", "sim_ko", "sim_en", "rr_en"])
        for i in order[:40]:
            w.writerow([rows[i]["sctid"], rows[i]["en"], rows[i]["cand"], rows[i]["gold"],
                        f"{chrf[i]:.3f}", f"{sim_ko[i]:.3f}", f"{sim_en[i]:.3f}", f"{rr_en[i]:.3f}"])
    print(f"\nwrote {out} (valid synonyms with lowest chrF — the metric-penalty cases)")

    # full per-item table for downstream (task-31 confidence feature)
    full = f"{OUTDIR}/xlingual_closeness_full.csv"
    with open(full, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sctid", "hier", "exact", "chrf", "sim_ko", "sim_en", "rr_en", "sim_en_goldko"])
        for i in range(n):
            w.writerow([rows[i]["sctid"], rows[i]["hier"], int(exact[i]),
                        f"{chrf[i]:.3f}", f"{sim_ko[i]:.3f}", f"{sim_en[i]:.3f}",
                        f"{rr_en[i]:.3f}", f"{sim_en_goldko[i]:.3f}"])
    print(f"wrote {full}")


if __name__ == "__main__":
    sys.exit(main())
