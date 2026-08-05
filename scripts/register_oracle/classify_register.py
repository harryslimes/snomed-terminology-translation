"""Classify every Korean form in the SNOMED KR extension by register
(sino | native | loan | mixed) using the NIKL 원어 lexicon.

Method:
  1. whole-term lookup in the lexicon (word -> {origins}); most multi-syllable
     medical compounds are unambiguous single entries.
  2. otherwise greedy longest-match segmentation into dictionary morphemes,
     classify each, aggregate.
  3. the rare sino+native homonym ambiguity (~0.7% of words: 하지=下肢, 위=胃) is
     resolved with a MEDICAL-SINO prior and flagged, since SNOMED clinical terms
     skew Sino. Every prior-resolved / low-coverage call is marked so it is
     auditable rather than silently guessed.

Reads : data/register_oracle/register_oracle.csv  (ko_term column)
        data/lexicon_nikl/nikl_origin.tsv
Writes: data/register_oracle/register_oracle_labeled.csv
        data/register_oracle/register_label_stats.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "register_oracle"
LEX = ROOT / "data" / "lexicon_nikl" / "nikl_origin.tsv"
ORACLE = OUT_DIR / "register_oracle.csv"

HANGUL = re.compile(r"[가-힣]+")
LATIN = re.compile(r"[A-Za-z]")


def load_lexicon():
    origins: dict[str, set[str]] = defaultdict(set)
    hanja: dict[str, str] = {}
    with LEX.open(encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 2:
                continue
            w, o = p[0], p[1]
            origins[w].add(o)
            if len(p) >= 3 and p[2] and w not in hanja:
                hanja[w] = p[2]
    maxlen = max(len(w) for w in origins)
    return origins, hanja, maxlen


def resolve_origin(origins: set[str]) -> tuple[str, bool]:
    """Collapse a homonym origin-set to one label. Returns (label, is_prior)."""
    if len(origins) == 1:
        return next(iter(origins)), False
    # medical-Sino prior for the sino/native clash; loan wins if only loan+native
    if "sino" in origins:
        return "sino", True
    if "loan" in origins:
        return "loan", True
    if "hybrid" in origins:
        return "hybrid", True
    return next(iter(origins)), True


def segment(tok: str, origins, maxlen: int):
    """Greedy longest-match. Returns list of (piece, label|None, is_prior)."""
    out = []
    i, n = 0, len(tok)
    cap = min(maxlen, n)
    while i < n:
        matched = False
        for L in range(min(cap, n - i), 0, -1):
            piece = tok[i : i + L]
            if piece in origins:
                lbl, prior = resolve_origin(origins[piece])
                out.append((piece, lbl, prior))
                i += L
                matched = True
                break
        if not matched:
            out.append((tok[i], None, False))  # unknown single syllable
            i += 1
    return out


def classify(term: str, origins, hanja, maxlen: int) -> dict:
    has_latin = bool(LATIN.search(term))
    chunks = HANGUL.findall(term)
    n_syl = sum(len(c) for c in chunks)
    labels = []            # per-morpheme labels (excluding unknown)
    prior_used = False
    covered = 0
    hanja_parts = []
    for chunk in chunks:
        # fast path: whole chunk is a dictionary entry
        if chunk in origins:
            lbl, prior = resolve_origin(origins[chunk])
            labels.append(lbl)
            prior_used |= prior
            covered += len(chunk)
            if chunk in hanja:
                hanja_parts.append(hanja[chunk])
            continue
        for piece, lbl, prior in segment(chunk, origins, maxlen):
            if lbl is not None:
                labels.append(lbl)
                prior_used |= prior
                covered += len(piece)
                if piece in hanja:
                    hanja_parts.append(hanja[piece])

    counts = Counter(labels)
    coverage = covered / n_syl if n_syl else 0.0

    # aggregate to a primary register label
    if has_latin:
        primary = "loan"
    elif not labels:
        primary = "unknown"
    elif counts.get("loan"):
        primary = "loan" if counts["loan"] * 2 >= len(labels) else "mixed"
    else:
        kinds = {k for k in counts if k in ("sino", "native", "hybrid")}
        if kinds == {"sino"}:
            primary = "sino"
        elif kinds == {"native"}:
            primary = "native"
        elif "sino" in kinds and "native" in kinds:
            primary = "mixed"
        elif kinds == {"hybrid"} or "hybrid" in kinds:
            primary = "mixed"
        else:
            primary = next(iter(kinds)) if kinds else "unknown"

    # confidence tier
    if primary == "unknown" or coverage < 0.5:
        conf = "low"
    elif prior_used or coverage < 1.0:
        conf = "medium"
    else:
        conf = "high"

    return {
        "register": primary,
        "breakdown": "+".join(f"{k}:{v}" for k, v in counts.most_common()),
        "coverage": round(coverage, 2),
        "confidence": conf,
        "hanja": "".join(hanja_parts) if primary in ("sino", "mixed") else "",
    }


def main() -> None:
    print("loading lexicon ...")
    origins, hanja, maxlen = load_lexicon()
    print(f"  {len(origins):,} words, maxlen={maxlen}")

    # classify each UNIQUE ko form once
    terms = {}
    with ORACLE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = row["ko_term"]
            if t not in terms:
                terms[t] = classify(t, origins, hanja, maxlen)
    print(f"  classified {len(terms):,} unique forms")

    # write labeled oracle (re-join to every row)
    out_path = OUT_DIR / "register_oracle_labeled.csv"
    with ORACLE.open(encoding="utf-8") as f, out_path.open(
        "w", newline="", encoding="utf-8"
    ) as g:
        r = csv.DictReader(f)
        w = csv.writer(g)
        w.writerow(
            ["sctid", "en_fsn", "ko_term", "acceptability", "nikl_register",
             "breakdown", "coverage", "confidence", "hanja"]
        )
        for row in r:
            c = terms[row["ko_term"]]
            w.writerow([
                row["sctid"], row["en_fsn"], row["ko_term"], row["acceptability"],
                c["register"], c["breakdown"], c["coverage"], c["confidence"], c["hanja"],
            ])

    # stats over unique forms
    reg = Counter(c["register"] for c in terms.values())
    conf = Counter(c["confidence"] for c in terms.values())
    reg_by_conf = defaultdict(Counter)
    for c in terms.values():
        reg_by_conf[c["confidence"]][c["register"]] += 1
    stats = {
        "unique_forms": len(terms),
        "register": dict(reg.most_common()),
        "confidence": dict(conf.most_common()),
        "register_by_confidence": {k: dict(v) for k, v in reg_by_conf.items()},
    }
    (OUT_DIR / "register_label_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False)
    )
    print("\n=== register (unique forms) ===")
    print(json.dumps(stats["register"], ensure_ascii=False, indent=2))
    print("=== confidence ===")
    print(json.dumps(stats["confidence"], ensure_ascii=False, indent=2))
    print(f"\nwrote {out_path.name}")


if __name__ == "__main__":
    main()
