"""Blind LLM-judge: is the concept-context gain masked by the reference metric?

chrF/semantic-to-gold penalise a valid-but-divergent translation. This judges
bare vs +parents translations PAIRWISE on which better fits the English concept
(judge sees the concept + its context, NOT the gold Korean), blind to which is
which (A/B order randomised). Only the cases where context CHANGED the output
are informative. If the judge favours +parents more than the metric did, the
metric was masking a real jump.

    python scripts/analysis/concept_context_judge.py --scores <dir>/concept_context_scores.csv
"""
from __future__ import annotations
import argparse, csv, hashlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from snomed_translation.snomed_rf2 import read_concept_terms

INT = Path.home() / "SNOMED-Terminologies/SnomedCT_InternationalRF2_PRODUCTION_20260101T120000Z"
BASE, MODEL = "http://localhost:8086", "cyankiwi/gemma-4-26B-A4B-it-qat-AWQ-INT4"
SYS = ("You are a bilingual medical terminologist. You are shown an English SNOMED CT concept and "
       "two candidate Korean translations, A and B. Decide which is the more accurate Korean "
       "translation of the concept. Answer with EXACTLY one token: A, B, or EQUAL.")


def order(sid):  # deterministic blind A/B assignment per concept
    return int(hashlib.md5(sid.encode()).hexdigest(), 16) % 2 == 0


def judge(fsn, a, b):
    u = f"English concept: {fsn}\nA: {a}\nB: {b}\nWhich Korean translation is more accurate (A, B, or EQUAL)?"
    r = requests.post(f"{BASE}/v1/chat/completions", json={
        "model": MODEL, "temperature": 0, "max_tokens": 4,
        "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": u}]}, timeout=120)
    t = (r.json()["choices"][0]["message"].get("content") or "").strip().upper()
    return "A" if t.startswith("A") else "B" if t.startswith("B") else "EQUAL"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--scores", required=True)
    ap.add_argument("--conc", type=int, default=32); a = ap.parse_args()
    fsn = {ct.sctid: ct.fsn for ct in read_concept_terms(INT)}
    rows = list(csv.DictReader(open(a.scores)))
    by = defaultdict(dict)
    for r in rows:
        by[r["sctid"]][r["variant"]] = r
    items = []  # (sid, hierarchy, A_text, B_text, parents_is_A)
    for sid, v in by.items():
        if not {"bare", "+parents"} <= set(v) or sid not in fsn:
            continue
        bare, par = v["bare"]["translation"], v["+parents"]["translation"]
        if bare == par:
            continue
        par_is_A = order(sid)
        items.append((sid, v["bare"]["hierarchy"],
                      par if par_is_A else bare, bare if par_is_A else par, par_is_A))
    print(f"changed cases judged: {len(items)}", flush=True)
    with ThreadPoolExecutor(max_workers=a.conc) as ex:
        verdicts = list(ex.map(lambda it: judge(fsn[it[0]], it[2], it[3]), items))

    tally = defaultdict(lambda: [0, 0, 0])  # hierarchy -> [parents_win, bare_win, equal]
    for (sid, h, _, _, par_is_A), vd in zip(items, verdicts):
        winner = ("parents" if par_is_A else "bare") if vd == "A" else \
                 ("bare" if par_is_A else "parents") if vd == "B" else "equal"
        idx = {"parents": 0, "bare": 1, "equal": 2}[winner]
        tally[h][idx] += 1; tally["__ALL__"][idx] += 1
    print(f"\n{'hierarchy':24s} {'+parents':>9} {'bare':>6} {'equal':>6}   verdict (on CHANGED cases)")
    for h in ["__ALL__", "qualifier value", "finding", "organism", "procedure",
              "body structure", "morphologic abnormality", "disorder", "substance"]:
        if h not in tally:
            continue
        p, b, e = tally[h]; tot = p + b + e
        if tot:
            print(f"{h:24s} {p:9d} {b:6d} {e:6d}   +parents {100*p/tot:.0f}% vs bare {100*b/tot:.0f}%")


if __name__ == "__main__":
    main()
