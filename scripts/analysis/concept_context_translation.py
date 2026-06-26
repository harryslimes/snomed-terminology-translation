"""Does SNOMED concept context in the EN->KO prompt improve translation quality?

Translates a stratified sample of SNOMED concepts EN->KO under three prompt
variants — bare term / +semantic tag / +parent hierarchy — and scores each
against the KR national-edition gold (multi-reference chrF + BGE-M3 semantic
cosine). Reports the quality delta overall and per hierarchy, weighted toward
the hard tail where context should matter most.

Feeds the prompt-optimisation thread: which extra context is worth referencing.

    python scripts/analysis/concept_context_translation.py --n-per 120 --out <dir>
"""
from __future__ import annotations
import argparse, csv, sys, random, json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np, requests, sacrebleu

INT = Path.home() / "SNOMED-Terminologies/SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z"
KR = Path("data/korean/SnomedCT_ManagedServiceKR_PRODUCTION_KR1000267_20251215T120000Z")
BASE = "http://localhost:8086"
MODEL = "cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4"
SYS = ("You are a medical terminologist. Translate the given English SNOMED CT clinical term "
       "into Korean, using standard Korean medical terminology. Output ONLY the Korean term for "
       "the main concept — no English, no explanation, no parentheses, no notes.")
HARD = ["organism", "morphologic abnormality", "body structure", "qualifier value"]
EASY = ["disorder", "procedure", "finding", "substance"]


def strip(f): return f.rsplit(" (", 1)[0] if f.endswith(")") else f
def tag(f): return f.rsplit("(", 1)[-1].rstrip(")").strip() if f.endswith(")") else ""


def load_int():
    from snomed_translation.snomed_rf2 import read_concept_terms
    fsn = {ct.sctid: ct.fsn for ct in read_concept_terms(INT)}
    parents = defaultdict(list)
    rel = next((INT / "Snapshot" / "Terminology").glob("sct2_Relationship_Snapshot*.txt"))
    with rel.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.split("\t")
            if p[2] == "1" and p[7] == "116680003":
                parents[p[4]].append(p[5])
    return fsn, parents


def load_kr_gold():
    g = defaultdict(set)
    d = next((KR / "Snapshot" / "Terminology").glob("sct2_Description_Snapshot-ko*.txt"))
    with d.open(encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.split("\t")          # id,eff,active,module,conceptId,lang,typeId,term,caseSig
            if p[2] == "1" and p[7].strip():
                g[p[4]].add(p[7].strip())
    return g


def chat(user):
    r = requests.post(f"{BASE}/v1/chat/completions", json={
        "model": MODEL, "temperature": 0, "max_tokens": 64,
        "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": user}]}, timeout=120)
    c = (r.json()["choices"][0]["message"].get("content") or "").strip()
    return c.splitlines()[0].strip().strip('".() ') if c else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per", type=int, default=120)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conc", type=int, default=128)
    a = ap.parse_args()
    rng = random.Random(13)
    fsn, parents = load_int()
    gold = load_kr_gold()
    by_h = defaultdict(list)
    for sid, terms in gold.items():
        if sid in fsn:
            by_h[tag(fsn[sid])].append(sid)
    sample = []
    for h in HARD + EASY:
        ids = sorted(by_h.get(h, [])); rng.shuffle(ids)
        sample += [(s, h) for s in ids[:a.n_per]]
    print(f"sample={len(sample)} across {len(set(h for _,h in sample))} hierarchies", flush=True)

    def variants(sid):
        pref, t = strip(fsn[sid]), tag(fsn[sid])
        pnames = [strip(fsn[p]) for p in parents.get(sid, [])[:3] if p in fsn]
        # context is clearly fenced off (labelled, "context only") so it informs
        # disambiguation without leaking into the output.
        bare = f"English term: {pref}\nKorean translation:"
        tagv = (f"English term: {pref}\nSemantic type (context only, do NOT translate or include): "
                f"{t}\nKorean translation:") if t else bare
        par = (f"English term: {pref}\nSemantic type (context only): {t}\nBroader SNOMED concepts "
               f"(context only, do NOT include): {'; '.join(pnames)}\nKorean translation:"
               ) if pnames else tagv
        return {"bare": bare, "+tag": tagv, "+parents": par}

    prompts = [(sid, h, v, txt) for sid, h in sample for v, txt in variants(sid).items()]
    with ThreadPoolExecutor(max_workers=a.conc) as ex:
        outs = list(ex.map(lambda p: chat(p[3]), prompts))
    print("translations done", flush=True)

    # score: chrF (multi-ref) + BGE semantic cosine (max over refs)
    from agent.qdrant_store import BGEM3Embedder
    emb = BGEM3Embedder()
    def enc(t):
        v, _ = emb.encode_documents(t); v = np.array(v, np.float32)
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)
    hyp_vec = enc([o or " " for o in outs])
    rows = []
    for (sid, h, v, _), out, hv in zip(prompts, outs, hyp_vec):
        refs = sorted(gold[sid])
        chrf = sacrebleu.sentence_chrf(out, refs).score
        rv = enc(refs); sem = float((rv @ hv).max())
        rows.append({"sctid": sid, "hierarchy": h, "variant": v, "chrf": chrf, "sem": sem,
                     "translation": out, "gold": " | ".join(refs[:3])})
    empty = sum(1 for r in rows if not r["translation"])
    if empty:
        print(f"WARNING: {empty}/{len(rows)} translations were EMPTY", flush=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    with open(f"{a.out}/concept_context_scores.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    def agg(rs): return (np.mean([r["chrf"] for r in rs]), np.mean([r["sem"] for r in rs]))
    print(f"\n{'variant':10s} {'chrF':>6} {'sem':>6}   (overall, n={len(sample)})")
    for v in ("bare", "+tag", "+parents"):
        c, s = agg([r for r in rows if r["variant"] == v]); print(f"{v:10s} {c:6.1f} {s:6.3f}")
    print("\nby hierarchy (chrF / sem), bare -> +tag -> +parents:")
    for h in HARD + EASY:
        line = f"  {h:24s}"
        for v in ("bare", "+tag", "+parents"):
            c, s = agg([r for r in rows if r["variant"] == v and r["hierarchy"] == h])
            line += f"  {c:4.1f}/{s:.2f}"
        print(line)


if __name__ == "__main__":
    main()
