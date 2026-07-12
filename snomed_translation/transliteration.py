"""Transliteration-slip detector — a deterministic MT error gate.

Flags Korean SNOMED translations that are *pure phonetic transliterations* of
the English source (e.g. ``Herniogram -> 허니오그램``) rather than genuine
translations (``Herniogram -> 탈장 조영술``). This is the failure mode that
cross-lingual embedding / back-translation confidence is BLIND to: a phonetic
echo embeds *close* to its English source, so similarity scores it as a good
match (see the ``snomed_direct_xlingual_verify_v1`` AUC~0.5 result).

Method (reference-free, no LLM):
  1. Romanize the hangul natively (Unicode syllable decomposition).
  2. Reduce romanized-KO and the English to their CONSONANT SKELETON —
     transliteration preserves consonants; vowels are noise.
  3. ``echo`` = skeleton similarity. High echo ⇒ the hangul mimics the sound.
  4. ``dict_cov`` = fraction of the hangul covered by a known native/Sino
     morpheme (from the register oracle). A real/hybrid translation contains
     one; a bare transliteration does not.
  5. Flag when echo is high AND dictionary coverage is ~zero.

Wire a ``translations`` dataset (needs an English column + a candidate-Korean
column) and, for the coverage gate, a ``dictionary`` dataset (the register
oracle CSV). Emits a per-row ``flags`` dataset + metrics; when the input also
carries an SME-rating column, the metrics include a false-positive proxy
(flagged rows the SME actually accepted).
"""
from __future__ import annotations

import csv
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pipelines.context import RunContext
from pipelines.functions import FunctionResult

# ── native hangul romanizer (Revised-Romanization approximation) ──────────
_CHO = ['g', 'kk', 'n', 'd', 'tt', 'r', 'm', 'b', 'pp', 's', 'ss', '',
        'j', 'jj', 'ch', 'k', 't', 'p', 'h']
_JUNG = ['a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', 'wae',
         'oe', 'yo', 'u', 'wo', 'we', 'wi', 'yu', 'eu', 'ui', 'i']
_JONG = ['', 'g', 'kk', 'ks', 'n', 'nj', 'nh', 'd', 'l', 'lg', 'lm', 'lb',
         'ls', 'lt', 'lp', 'lh', 'm', 'b', 'bs', 's', 'ss', 'ng', 'j', 'ch',
         'k', 't', 'p', 'h']
_VOWELS = set('aeiou')


def romanize(text: str) -> str:
    """Romanize hangul syllables to latin; keep any latin already present."""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            s = code - 0xAC00
            cho, rem = divmod(s, 588)
            jung, jong = divmod(rem, 28)
            out.append(_CHO[cho] + _JUNG[jung] + _JONG[jong])
        elif ch.isalpha():
            out.append(ch.lower())
    return ''.join(out)


def _skeleton(s: str) -> str:
    """Consonant skeleton with runs collapsed: 'herniogram' -> 'hrngrm'."""
    s = re.sub(r'[^a-z]', '', s.lower())
    cons = ''.join(c for c in s if c not in _VOWELS)
    return re.sub(r'(.)\1+', r'\1', cons)


def _hangul_only(s: str) -> str:
    return ''.join(c for c in s if 0xAC00 <= ord(c) <= 0xD7A3)


def phonetic_echo(english: str, korean: str) -> float:
    """0..1 consonant-skeleton similarity of romanized KO vs the English."""
    eng = re.sub(r'[^a-z]', '', english.lower())
    return SequenceMatcher(None, _skeleton(romanize(korean)),
                           _skeleton(eng)).ratio()


def dict_coverage(korean: str, vocab: set[str]) -> float:
    """Fraction of hangul chars covered by any known dictionary token."""
    h = _hangul_only(korean)
    if not h:
        return 1.0
    covered = [False] * len(h)
    for v in vocab:
        start = 0
        while (i := h.find(v, start)) != -1:
            for k in range(i, i + len(v)):
                covered[k] = True
            start = i + 1
    return sum(covered) / len(h)


def load_vocab(path: str, col: str = "ko_term", min_len: int = 2) -> set[str]:
    """Known native/Sino KO tokens from a dictionary CSV (e.g. register oracle)."""
    vocab: set[str] = set()
    p = Path(path)
    if not p.exists():
        return vocab
    with p.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for tok in re.split(r'[\s,;()/]+', row.get(col, "") or ""):
                tok = _hangul_only(tok)
                if len(tok) >= min_len:
                    vocab.add(tok)
    return vocab


# ── flow runner ────────────────────────────────────────────────────────────
def _dataset_path(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in ("_primary", "dataset", "rows", "path"):
            if isinstance(value.get(k), str):
                return value[k]
    return None


def _roles(value: Any) -> dict[str, str]:
    return value.get("roles", {}) if isinstance(value, dict) else {}


def _col(params: dict, roles: dict, param_name: str, role: str,
         fallback: str) -> str:
    """Resolve a column name: explicit param > datasource role map > fallback."""
    return str(params.get(param_name) or roles.get(role) or fallback)


def transliteration_detect(ctx: RunContext, inputs: dict[str, Any],
                           params: dict[str, Any]) -> FunctionResult:
    tpath = _dataset_path(inputs.get("translations"))
    if not tpath or not Path(tpath).exists():
        return FunctionResult(ok=False,
                              message="transliteration_detect: no `translations` dataset wired")
    roles = _roles(inputs.get("translations"))
    id_col = _col(params, roles, "id_col", "sctid", "sctid")
    en_col = _col(params, roles, "en_col", "en", "en")
    ko_col = _col(params, roles, "ko_col", "target", "translation")
    label_col = str(params.get("label_col") or "sme_rating")
    echo_thr = float(params.get("echo_threshold") or 0.70)
    # Coverage gate is an OPTIONAL refinement: only applied when a dictionary is
    # wired AND cov_threshold > 0. Echo alone separates cleanly on the full pool
    # (pure transliterations sit ≥0.73; the next non-transliteration is ~0.61),
    # and raw substring coverage is polluted by loan fragments that leak into the
    # oracle (e.g. 그램 from 밀리그램), so the gate is off by default.
    cov_thr = float(params.get("cov_threshold") or 0.0)

    vocab: set[str] = set()
    dpath = _dataset_path(inputs.get("dictionary"))
    if dpath and Path(dpath).exists():
        dict_col = _col(params, _roles(inputs.get("dictionary")),
                        "dict_col", "target", "ko_term")
        vocab = load_vocab(dpath, col=dict_col)
    have_dict = bool(vocab)
    use_gate = have_dict and cov_thr > 0.0

    out_rows: list[dict] = []
    with Path(tpath).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        has_label = label_col in (reader.fieldnames or [])
        for r in reader:
            en, ko = (r.get(en_col) or "").strip(), (r.get(ko_col) or "").strip()
            if not en or not ko:
                continue
            echo = phonetic_echo(en, ko)
            cov = dict_coverage(ko, vocab) if have_dict else None
            flag = echo >= echo_thr and (not use_gate or (cov is not None and cov <= cov_thr))
            row = {id_col: (r.get(id_col) or "").strip(), "english": en,
                   "korean": ko, "romanized": romanize(ko),
                   "echo": round(echo, 3),
                   "dict_cov": ("" if cov is None else round(cov, 3)),
                   "flag": int(flag)}
            if has_label:
                row["sme_rating"] = (r.get(label_col) or "").strip().upper()
            out_rows.append(row)

    if not out_rows:
        return FunctionResult(ok=False,
                              message=f"transliteration_detect: no usable rows in {tpath} "
                                      f"(en_col={en_col!r}, ko_col={ko_col!r})")

    out = Path(ctx.log_dir) / "transliteration_flags.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    n = len(out_rows)
    flagged = [r for r in out_rows if r["flag"]]
    metrics = {"n_rows": float(n), "n_flagged": float(len(flagged)),
               "flag_rate_pct": round(100.0 * len(flagged) / n, 3),
               "dictionary_tokens": float(len(vocab))}
    if out_rows and "sme_rating" in out_rows[0]:
        # false-positive proxy: rows we flagged that the SME actually accepted
        fp = sum(1 for r in flagged if r["sme_rating"] == "ACCEPTABLE")
        tp_nonacc = sum(1 for r in flagged if r["sme_rating"] in ("PARTIAL", "WRONG"))
        metrics["flagged_sme_acceptable"] = float(fp)
        metrics["flagged_sme_nonacceptable"] = float(tp_nonacc)
        metrics["flag_precision_pct"] = (
            round(100.0 * tp_nonacc / len(flagged), 3) if flagged else 0.0)

    msg = (f"flagged {len(flagged)}/{n} as transliteration (echo≥{echo_thr}"
           + (f", cov≤{cov_thr}" if use_gate else "")
           + f"; coverage gate {'ON' if use_gate else 'off'})")
    return FunctionResult(ok=True, outputs={"flags": str(out)},
                          metrics=metrics, message=msg)
