"""Assemble a PRUNED corpus for EN->KO instruction-prompt *induction*.

The goal is maximum *phenomenon coverage per token*, not raw volume — even at
1M context, a few thousand well-chosen examples beat 100k raw pairs, and pruning
is a quality lever, not just a cost one. Four strata:

  A. Model critiques (rule-bearing corrections) — the highest-signal stratum:
     each row is naive_output -> suggested_fix -> a reasoned convention, grounded
     with KR body-site/modality dictionary lookups. (Human SME columns in this
     release are still blank, so these are Sonnet critiques, labelled as such.)
  B. Gold minimal pairs — terms differing by ONE feature (laterality / contrast /
     with-without / acuity / approach); maximal signal per token for how a single
     feature maps.
  C. Gold reference pairs — diversity-sampled by Korean procedure-suffix token to
     spread across construction patterns rather than the head distribution.
  D. Clean SNOMED bilingual pairs (SNOMED + SNOMED_synonyms only; the messy EDI /
     KCD7 / LOINC billing rows are dropped) — breadth beyond procedures.

Emits one markdown corpus + a stats header. Feed it to the ``generate_text``
flow node (Opus, thinking) to induce a translation instruction guide.

    # defaults reproduce the original 248-example corpus
    python scripts/data_prep/build_induction_corpus.py [OUT.md]

    # a larger corpus: more examples per stratum
    python scripts/data_prep/build_induction_corpus.py \
        --reference-n 300 --minimal-cap 120 --bilingual-n 200 \
        --critiques-per-stratum 12 --out data/evals/korean/induction_corpus_big.md

    # or scale every stratum by a factor (rounds each default up)
    python scripts/data_prep/build_induction_corpus.py --scale 3

Stratum sizes are knobs: A (critiques) is capped by the SME-review rows that
actually carry a written critique (~one hundred), so it saturates quickly; B/C
draw from the ~3.7k-row eval set and D from ~475k bilingual pairs, so those scale
far. Raising a knob past what a stratum can supply just yields all of it (the
printed stats header reports the ACTUAL counts). Override the data root with
DATA_DIR (defaults to this repo's data/) or --data-dir.
"""
from __future__ import annotations

import argparse
import collections
import csv
import math
import os
import re
from pathlib import Path

# Original per-stratum defaults (reproduce the historical 248-example corpus).
DEFAULTS = {"critiques_per_stratum": 6, "reference_n": 110,
            "minimal_cap": 60, "bilingual_n": 60}

# Default data paths (repo data/ or $DATA_DIR); main() reassigns these globals
# when --data-dir / $DATA_DIR points elsewhere.
_DATA_DIR = Path(os.environ.get(
    "DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
EVAL = _DATA_DIR / "evals/korean/procedure_eval_set.csv"
INTERNAL = _DATA_DIR / "sme_review/2026-04-24/sme_review_internal.csv"
BILINGUAL = _DATA_DIR / "EN-KO/all_bilingual_pairs.csv"


def spread(items: list, k: int) -> list:
    """Deterministic even sample of k items (no RNG, stable across runs)."""
    n = len(items)
    if n <= k:
        return list(items)
    step = max(1, n // k)
    return [items[(i * step) % n] for i in range(k)]


# ---- A. Model critiques --------------------------------------------------
def load_critiques(limit_per_stratum: int = 6) -> list[dict]:
    rows = list(csv.DictReader(INTERNAL.open(encoding="utf-8")))
    keep = [r for r in rows if len((r.get("sonnet_what_is_wrong") or "").strip()) > 40]
    by_stratum: dict[str, list[dict]] = collections.defaultdict(list)
    for r in keep:
        by_stratum[r.get("stratum") or "?"].append(r)
    out: list[dict] = []
    for _stratum, rs in sorted(by_stratum.items()):
        rs.sort(key=lambda r: (r.get("sonnet_label") == "CORRECT",
                               -len(r.get("sonnet_what_is_wrong") or "")))
        out.extend(rs[:limit_per_stratum])
    return out


# ---- B/C. Gold pairs -----------------------------------------------------
KO_SUFFIX = re.compile(r"(절제술|성형술|복원술|고정술|봉합술|조영술|내시경|초음파|"
                       r"촬영|검사|요법|치료|주입|생검|절개|절단|이식|재건|조영|"
                       r"술|증|염|종|병)$")

def ko_bucket(ko: str) -> str:
    m = KO_SUFFIX.search(ko.strip())
    return m.group(1) if m else "_other"

MINIMAL_FEATURES = [
    ("laterality", re.compile(r"\b(left|right|bilateral)\b", re.I)),
    ("contrast", re.compile(r"\b(with|without)\s+contrast\b", re.I)),
    ("with_without", re.compile(r"\bwith(out)?\b", re.I)),
    ("acuity", re.compile(r"\b(acute|chronic)\b", re.I)),
    ("approach", re.compile(r"\b(open|closed|percutaneous|laparoscopic|endoscopic)\b", re.I)),
]

def load_reference(target_n: int = 110, minimal_cap: int = 60
                   ) -> tuple[list[dict], list[dict]]:
    rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8"))
            if r.get("ko_reference", "").strip()]
    minimal: list[dict] = []
    for feat, rx in MINIMAL_FEATURES:
        groups: dict[str, list[dict]] = collections.defaultdict(list)
        for r in rows:
            if rx.search(r["preferred_term"]):
                groups[rx.sub("█", r["preferred_term"]).lower()].append(r)
        for rs in groups.values():
            variants = {rx.search(r["preferred_term"]).group(0).lower(): r for r in rs}
            if len(variants) >= 2:
                for r in list(variants.values())[:2]:
                    minimal.append(dict(r, _minimal=feat))
        if len(minimal) >= minimal_cap:
            break
    minimal = spread(minimal, minimal_cap)

    by_bucket: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_bucket[ko_bucket(r["ko_reference"])].append(r)
    for b in by_bucket.values():
        b.sort(key=lambda r: (r["preferred_term"].split() or ["_"])[0].lower())
    diverse: list[dict] = []
    buckets = sorted(by_bucket.items(), key=lambda kv: -len(kv[1]))
    per = max(1, target_n // max(1, len(buckets)))
    for _, rs in buckets:
        diverse.extend(spread(rs, per))
    return minimal, spread(diverse, target_n)


# ---- D. Clean SNOMED bilingual pairs ------------------------------------
def load_bilingual(target_n: int = 60) -> list[dict]:
    rows = []
    for r in csv.DictReader(BILINGUAL.open(encoding="utf-8")):
        if r.get("source") in ("SNOMED", "SNOMED_synonyms"):
            en, ko = (r.get("EN") or "").strip(), (r.get("KO") or "").strip()
            if 0 < len(en) <= 80 and ko:
                rows.append({"EN": en, "KO": ko})
    rows.sort(key=lambda r: (len(r["EN"]), r["EN"]))
    return spread(rows, target_n)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a pruned EN->KO induction corpus (parameterised sizes).")
    p.add_argument("out", nargs="?", default=None,
                   help="Output .md path (positional, back-compat). Overridden by "
                        "--out. Default: <data>/evals/korean/induction_corpus.md")
    p.add_argument("--out", dest="out_flag", default=None,
                   help="Output .md path (wins over the positional arg).")
    p.add_argument("--data-dir", default=None,
                   help="Data root (else $DATA_DIR, else this repo's data/).")
    p.add_argument("--critiques-per-stratum", type=int,
                   default=DEFAULTS["critiques_per_stratum"],
                   help=f"Stratum A cap per stratum (default {DEFAULTS['critiques_per_stratum']}; "
                        "saturates ~100 total).")
    p.add_argument("--reference-n", type=int, default=DEFAULTS["reference_n"],
                   help=f"Stratum C diverse reference pairs (default {DEFAULTS['reference_n']}).")
    p.add_argument("--minimal-cap", type=int, default=DEFAULTS["minimal_cap"],
                   help=f"Stratum B minimal-pair cap (default {DEFAULTS['minimal_cap']}).")
    p.add_argument("--bilingual-n", type=int, default=DEFAULTS["bilingual_n"],
                   help=f"Stratum D bilingual breadth pairs (default {DEFAULTS['bilingual_n']}).")
    p.add_argument("--scale", type=float, default=None,
                   help="Multiply every default stratum size by this factor "
                        "(a convenience; per-stratum flags still override it).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    global EVAL, INTERNAL, BILINGUAL
    args = _parse_args(argv)

    data_dir = Path(args.data_dir or os.environ.get("DATA_DIR")
                    or Path(__file__).resolve().parents[2] / "data")
    EVAL = data_dir / "evals/korean/procedure_eval_set.csv"
    INTERNAL = data_dir / "sme_review/2026-04-24/sme_review_internal.csv"
    BILINGUAL = data_dir / "EN-KO/all_bilingual_pairs.csv"

    # --scale sets any knob left at its default; explicit flags always win.
    crit_n, ref_n = args.critiques_per_stratum, args.reference_n
    min_n, bil_n = args.minimal_cap, args.bilingual_n
    if args.scale is not None:
        s = args.scale
        d = DEFAULTS
        if crit_n == d["critiques_per_stratum"]:
            crit_n = math.ceil(d["critiques_per_stratum"] * s)
        if ref_n == d["reference_n"]:
            ref_n = math.ceil(d["reference_n"] * s)
        if min_n == d["minimal_cap"]:
            min_n = math.ceil(d["minimal_cap"] * s)
        if bil_n == d["bilingual_n"]:
            bil_n = math.ceil(d["bilingual_n"] * s)

    out = Path(args.out_flag or args.out
               or data_dir / "evals/korean/induction_corpus.md")

    crit = load_critiques(crit_n)
    minimal, diverse = load_reference(ref_n, min_n)
    biling = load_bilingual(bil_n)
    total = len(crit) + len(minimal) + len(diverse) + len(biling)

    L: list[str] = []
    w = L.append
    w("# EN->KO SNOMED translation - pruned induction corpus\n")
    w(f"- Model critiques (rule-bearing): {len(crit)}")
    w(f"- Gold minimal pairs (feature-isolating): {len(minimal)}")
    w(f"- Gold reference pairs (diversity-sampled): {len(diverse)}")
    w(f"- Clean SNOMED bilingual pairs (breadth): {len(biling)}")
    w(f"- TOTAL examples: {total}\n")

    w("\n## A. Model critiques of naive translations (with reasoning)\n")
    w("_Provenance: Sonnet critiques, dictionary-grounded; human SME review not "
      "yet filled in. Each = naive pipeline output -> suggested fix -> why._\n")
    for i, r in enumerate(crit, 1):
        w(f"\n**A{i}. {r['english_term']}**  (stratum: {r.get('stratum','?')}, "
          f"label: {r.get('sonnet_label','?')}, conf: {r.get('sonnet_confidence','?')})")
        if r.get("snomed_body_site_ko_kr_dict") or r.get("snomed_modality_en"):
            w(f"- grounding: body_site_ko=`{r.get('snomed_body_site_ko_kr_dict','')}` "
              f"modality_en=`{r.get('snomed_modality_en','')}`")
        w(f"- naive: `{r.get('pipeline_translation_ko','')}`  "
          f"(back-translates to: {r.get('pipeline_back_translation_en','')})")
        w(f"- suggested: `{r.get('sonnet_suggested_translation','')}`")
        if r.get("sonnet_what_is_right"):
            w(f"- right: {r['sonnet_what_is_right']}")
        w(f"- WRONG / rule: {r.get('sonnet_what_is_wrong','')}")

    w("\n\n## B. Gold minimal pairs (one feature varied)\n")
    for r in minimal:
        w(f"- [{r['_minimal']}] {r['preferred_term']}  ->  {r['ko_reference']}")

    w("\n\n## C. Gold reference pairs (diverse)\n")
    for r in diverse:
        w(f"- {r['preferred_term']}  ->  {r['ko_reference']}  ({r['hierarchy']})")

    w("\n\n## D. SNOMED bilingual pairs (breadth, EN->KO)\n")
    for r in biling:
        w(f"- {r['EN']}  ->  {r['KO']}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size} bytes, {total} examples: "
          f"{len(crit)} critiques / {len(minimal)} minimal / "
          f"{len(diverse)} reference / {len(biling)} bilingual)")


if __name__ == "__main__":
    main()
