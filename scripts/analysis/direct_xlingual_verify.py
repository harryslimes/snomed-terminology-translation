"""Non-generative translation check: score the candidate Korean DIRECTLY in the
multilingual BGE-M3 space, instead of round-tripping through an LLM.

Back-translation fails as an error detector (AUC ~0.5) because the LLM normalises
errors. This skips the LLM: embed the candidate Korean and compare it to (a) the
source concept's English term [reference-free, deployable] and (b) the gold
Korean [reference-based]. Reports AUC for predicting an incorrect translation
vs both a string label (char-Jaccard to gold, embedder-independent) and a
semantic label, alongside the back-translation baselines.

Needs GPU/BGE-M3. Result: direct cross-lingual (vs EN) beats back-translation
(0.58-0.62 vs 0.51-0.53) but is weak absolutely; vs the Korean reference it is
near-perfect (0.98+) but only available where a reference exists.

    python scripts/analysis/direct_xlingual_verify.py \
        --labels data/eval_inputs/kr_candidates_labels.csv \
        --bt-run data/wizard_runs/<job>/snomed_retrieve.csv --int <RF2_root>
"""
from __future__ import annotations
import argparse, csv
import numpy as np
from snomed_translation.snomed_rf2 import read_concept_terms


def auc(s, y):
    s = np.asarray(s, float); p = s[y == 1]; ng = s[y == 0]
    if not len(p) or not len(ng):
        return float("nan")
    return float((p[:, None] > ng[None, :]).mean() + 0.5 * (p[:, None] == ng[None, :]).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--bt-run", required=True)
    ap.add_argument("--int", required=True)
    a = ap.parse_args()
    from agent.qdrant_store import BGEM3Embedder
    strip = lambda f: f.rsplit(" (", 1)[0] if f.endswith(")") else f
    fsn = {ct.sctid: strip(ct.fsn) for ct in read_concept_terms(a.int)}
    lab = list(csv.DictReader(open(a.labels)))
    res = list(csv.DictReader(open(a.bt_run)))
    keep = [i for i in range(min(len(lab), len(res))) if lab[i]["sctid"] in fsn]
    lab = [lab[i] for i in keep]; res = [res[i] for i in keep]
    emb = BGEM3Embedder()

    def enc(t):
        v, _ = emb.encode_documents(t); v = np.array(v, np.float32)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    cand = enc([l["candidate"] for l in lab])
    gold = enc([l["ko_reference"] for l in lab])
    cen = enc([fsn[l["sctid"]] for l in lab])
    xling_en = (cand * cen).sum(1)
    sem_gold = (cand * gold).sum(1)
    bt_rec = np.array([int(r.get("recovered") or 0) for r in res])
    bt_mar = np.array([float(r.get("margin") or 0) for r in res])
    norm = lambda s: (s or "").replace(" ", "").lower()
    cj = lambda a, b: (len(set(norm(a)) & set(norm(b))) / len(set(norm(a)) | set(norm(b)))
                       if (set(norm(a)) | set(norm(b))) else 0)
    inc_str = np.array([cj(l["candidate"], l["ko_reference"]) < 0.5 for l in lab], int)
    inc_sem = (sem_gold < 0.75).astype(int)
    print(f"n={len(lab)}  incorrect(string)={int(inc_str.sum())}  incorrect(sem)={int(inc_sem.sum())}")
    print(f"{'signal':30s} {'vs string':>10s} {'vs sem':>8s}")
    for name, sig in [("xling_en (NON-gen, vs EN)", -xling_en),
                      ("back-trans recovered (gen)", 1 - bt_rec),
                      ("back-trans margin (gen)", -bt_mar),
                      ("sem_gold (vs gold KO; circular)", -sem_gold)]:
        print(f"{name:30s} {auc(sig, inc_str):10.3f} {auc(sig, inc_sem):8.3f}")


if __name__ == "__main__":
    main()
