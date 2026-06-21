#!/usr/bin/env python3
"""LLM-as-judge for Korean SNOMED translations.

Sends each non-matching (translation != ko_reference) row to Gemma 4 asking
it to classify the error type. Then correlates labels with char_sim.

Labels:
  ACCEPTABLE  - synonym or stylistic variant; both translations valid
  PARTIAL     - missing/wrong modifier or component; close but not quite
  WRONG       - semantic error; different concept, hallucinated, or nonsense

Reads: data/evals/korean/translations_<tag>_lookup.csv
Writes: data/evals/korean/judge_<tag>.csv with columns:
        sctid, english, reference, translation, char_sim, label, reasoning
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("judge")


JUDGE_SYSTEM = """\
You are a Korean medical terminology reviewer. Your job is to classify differences \
between a candidate Korean translation and the reference Korean translation from the \
official KHIS Korean SNOMED CT extension (KR1000267).

Classify each pair into EXACTLY ONE of these three labels:

1. ACCEPTABLE — The candidate is a valid alternative translation. It uses a synonym, \
   a different but equivalent word (e.g. 절제 vs 절제술, 검사 vs 시행), different word \
   order, different particles, or different spacing — but the meaning is correct and a \
   Korean medical professional would accept it. Also use this label if the candidate \
   follows a different but valid translation convention (e.g. native Korean vs \
   Sino-Korean for the same anatomical concept).

2. PARTIAL — The candidate captures the core concept but has a meaningful defect: \
   missing a modifier (e.g. "left/right", "total/partial", "open/laparoscopic"), wrong \
   suffix (e.g. 절제 when 절제술 was required, or vice versa changing meaning), wrong \
   approach verb, or extra/missing clinical detail. A medical professional would notice \
   the difference and mark it as incomplete or slightly off.

3. WRONG — The candidate is semantically wrong. It refers to a different concept, \
   contains hallucinated English/Latin, has ungrammatical Korean, or is nonsense. A \
   medical professional would reject it.

Return ONLY a single JSON object with this exact format, no extra text:
{"label": "ACCEPTABLE" | "PARTIAL" | "WRONG", "reasoning": "<one short sentence>"}"""


JUDGE_USER = """\
English source term: {english}
Reference Korean (KR extension): {reference}
Candidate Korean: {candidate}

Classify the candidate."""


def normalise(s: str) -> str:
    return "".join(s.split())


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def char_sim(a: str, b: str) -> float:
    na, nb = normalise(a), normalise(b)
    mx = max(len(na), len(nb), 1)
    return 1.0 - levenshtein(na, nb) / mx


def parse_judge_response(content: str) -> tuple[str, str]:
    """Extract label and reasoning from judge response. Fallback to heuristic parse."""
    content = content.strip()
    # Strip any code fences
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL)
    try:
        obj = json.loads(content)
        label = str(obj.get("label", "")).upper().strip()
        reasoning = str(obj.get("reasoning", "")).strip()
        if label in {"ACCEPTABLE", "PARTIAL", "WRONG"}:
            return label, reasoning
    except json.JSONDecodeError:
        pass
    # Fallback: regex for label
    m = re.search(r'"label"\s*:\s*"(ACCEPTABLE|PARTIAL|WRONG)"', content, re.IGNORECASE)
    if m:
        return m.group(1).upper(), content[:200]
    # Last resort: first of the three keywords found
    for lbl in ("ACCEPTABLE", "PARTIAL", "WRONG"):
        if lbl in content.upper():
            return lbl, content[:200]
    return "UNKNOWN", content[:200]


def judge_one(
    base_url: str,
    model_id: str,
    english: str,
    reference: str,
    candidate: str,
) -> tuple[str, str]:
    user = JUDGE_USER.format(english=english, reference=reference, candidate=candidate)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user},
        ],
        "max_tokens": 256,
        "temperature": 0.0,
        # Disable thinking for reasoning-capable models (Qwen3); Gemma ignores this
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=180)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    content = msg.get("content") or msg.get("reasoning") or ""
    return parse_judge_response(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--translations",
        type=Path,
        default=Path("data/evals/korean/translations_gemma4-26b_lookup.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/evals/korean/judge_gemma4-26b.csv"),
    )
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--include-exact",
        action="store_true",
        help="Also judge rows that exact-match (for calibration)",
    )
    args = parser.parse_args()

    # Load model config
    cfg_path = ROOT_DIR / "configs" / "models.json"
    with cfg_path.open() as f:
        cfg = json.load(f)
    model_key = args.model or "gemma4-26b"
    model_cfg = cfg["models"][model_key]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]

    # Load translations, filter to non-matches
    rows = list(csv.DictReader(args.translations.open(encoding="utf-8")))
    scored = []
    for row in rows:
        t = row["translation"].strip()
        r = row["ko_reference"].strip()
        if t.startswith("ERROR"):
            continue
        sim = char_sim(t, r)
        exact = normalise(t) == normalise(r)
        scored.append({
            "sctid": row["sctid"],
            "english": row["preferred_term"],
            "reference": r,
            "translation": t,
            "char_sim": sim,
            "exact": exact,
        })

    if args.include_exact:
        to_judge = scored
    else:
        to_judge = [r for r in scored if not r["exact"]]

    if args.limit:
        to_judge = to_judge[: args.limit]

    log.info(
        "Loaded %d total, %d non-exact, judging %d (concurrency=%d)",
        len(scored), sum(1 for r in scored if not r["exact"]), len(to_judge), args.concurrency,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    outf = args.output.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf,
        fieldnames=["sctid", "english", "reference", "translation", "char_sim", "exact", "label", "reasoning"],
    )
    writer.writeheader()

    lock = Lock()
    done = [0]
    t0 = time.monotonic()

    def process(row: dict) -> dict:
        try:
            label, reasoning = judge_one(
                base_url, model_id, row["english"], row["reference"], row["translation"]
            )
        except Exception as exc:
            log.error("Judge failed for %s: %s", row["sctid"], exc)
            label, reasoning = "ERROR", str(exc)[:200]
        return {**row, "label": label, "reasoning": reasoning}

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(process, row) for row in to_judge]
        for fut in as_completed(futures):
            result = fut.result()
            with lock:
                writer.writerow(result)
                outf.flush()
                done[0] += 1
                if done[0] % 50 == 0:
                    elapsed = time.monotonic() - t0
                    rate = done[0] / elapsed if elapsed > 0 else 0
                    eta = (len(to_judge) - done[0]) / rate if rate > 0 else 0
                    log.info(
                        "Progress: %d/%d (%.0f%%) | %.1f req/s | ETA %.0fs",
                        done[0], len(to_judge), 100 * done[0] / len(to_judge), rate, eta,
                    )

    outf.close()
    log.info("Wrote %s", args.output)

    # --- Correlation: label × sim bucket ---
    log.info("Building correlation table...")
    judge_rows = list(csv.DictReader(args.output.open(encoding="utf-8")))
    buckets = [
        ("sim ≥ 0.90", lambda s: s >= 0.90),
        ("0.70–0.90", lambda s: 0.70 <= s < 0.90),
        ("0.40–0.70", lambda s: 0.40 <= s < 0.70),
        ("sim < 0.40", lambda s: s < 0.40),
    ]
    labels = ["ACCEPTABLE", "PARTIAL", "WRONG", "UNKNOWN", "ERROR"]

    # Cross-tab
    print("\n=== Label × char_sim cross-tab ===")
    print(f"{'bucket':<14s} | " + " | ".join(f"{l:>10s}" for l in labels) + f" | {'total':>6s}")
    print("-" * 80)
    totals = {l: 0 for l in labels}
    for bname, bfn in buckets:
        counts = {l: 0 for l in labels}
        for r in judge_rows:
            try:
                s = float(r["char_sim"])
            except ValueError:
                continue
            if bfn(s):
                counts[r["label"]] = counts.get(r["label"], 0) + 1
                totals[r["label"]] = totals.get(r["label"], 0) + 1
        total = sum(counts.values())
        print(
            f"{bname:<14s} | "
            + " | ".join(f"{counts.get(l, 0):>10d}" for l in labels)
            + f" | {total:>6d}"
        )
    print("-" * 80)
    print(
        f"{'TOTAL':<14s} | "
        + " | ".join(f"{totals.get(l, 0):>10d}" for l in labels)
        + f" | {sum(totals.values()):>6d}"
    )

    # Per-label sim stats
    print("\n=== Per-label char_sim stats ===")
    print(f"{'label':<12s} {'n':>5s} {'mean':>7s} {'median':>7s} {'min':>6s} {'max':>6s}")
    for lbl in labels:
        sims = []
        for r in judge_rows:
            if r["label"] == lbl:
                try:
                    sims.append(float(r["char_sim"]))
                except ValueError:
                    pass
        if not sims:
            continue
        sims.sort()
        n = len(sims)
        mean = sum(sims) / n
        median = sims[n // 2]
        print(f"{lbl:<12s} {n:>5d} {mean:>7.3f} {median:>7.3f} {sims[0]:>6.3f} {sims[-1]:>6.3f}")


if __name__ == "__main__":
    main()
