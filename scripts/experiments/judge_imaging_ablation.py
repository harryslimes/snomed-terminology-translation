#!/usr/bin/env python3
"""Pairwise LLM-as-judge for the imaging-resources ablation.

For each concept, joins arm-A and arm-B translations on sctid, randomises
their presentation order, and asks a judge LLM which candidate is the better
translation given the KR reference. Runs each pair twice with order swapped
to control for position bias; only consistent verdicts count.

Outputs a per-concept CSV plus an aggregate summary (win / tie counts,
stratified by imaging sub-scope if a method tag is available).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
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
log = logging.getLogger("judge_ablation")

OUT_DIR = ROOT_DIR / "data" / "evals" / "korean" / "imaging_ablation"


JUDGE_SYSTEM = """\
You are a senior Korean medical terminology reviewer evaluating two candidate \
Korean translations of a SNOMED CT imaging procedure concept. Your job is to decide \
which candidate is closer to the official KR reference translation in terms of \
terminology choice, word order, modality naming, contrast / view / timing \
phrasing, body-site rendering, and overall adequacy for clinical use.

Rules:
- Base the decision primarily on fidelity to the reference translation style.
- Prefer the candidate that would be accepted by a Korean radiologist using the \
  KR SNOMED extension.
- If both candidates are equivalent (stylistic variants of each other, or both \
  equally close/far from the reference), return "tie".
- Do not invent additional context. Judge only what is written.

Return ONLY a single JSON object, no extra text:
{"verdict": "LEFT" | "RIGHT" | "tie", "reasoning": "<one short sentence>"}"""


JUDGE_USER = """\
English source term: {english}
Reference Korean (KR extension): {reference}

Candidate LEFT:  {left}
Candidate RIGHT: {right}

Which candidate is closer to the reference?"""


def parse_judge(content: str) -> tuple[str, str]:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL)
    try:
        obj = json.loads(content)
        verdict = str(obj.get("verdict", "")).upper().strip()
        reasoning = str(obj.get("reasoning", "")).strip()
        if verdict in {"LEFT", "RIGHT", "TIE"}:
            return verdict, reasoning
    except json.JSONDecodeError:
        pass
    m = re.search(r'"verdict"\s*:\s*"(LEFT|RIGHT|TIE|tie)"', content, re.IGNORECASE)
    if m:
        return m.group(1).upper(), content[:200]
    up = content.upper()
    for v in ("LEFT", "RIGHT", "TIE"):
        if v in up:
            return v, content[:200]
    return "UNKNOWN", content[:200]


def judge_one(
    base_url: str,
    model_id: str,
    english: str,
    reference: str,
    left: str,
    right: str,
) -> tuple[str, str]:
    user = JUDGE_USER.format(english=english, reference=reference, left=left, right=right)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user},
        ],
        "max_tokens": 256,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=180)
    r.raise_for_status()
    msg = r.json()["choices"][0]["message"]
    content = msg.get("content") or msg.get("reasoning") or ""
    return parse_judge(content)


def load_arm(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["translation"].startswith("ERROR"):
                continue
            rows[row["sctid"]] = row
    return rows


def wait_for_server(base_url: str, timeout: int = 900) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise SystemExit(f"vLLM judge backend not ready within {timeout}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm-a", type=Path, required=True,
                        help="CSV from translate_imaging_ablation.py --arm A")
    parser.add_argument("--arm-b", type=Path, required=True,
                        help="CSV from translate_imaging_ablation.py --arm B")
    parser.add_argument("--output", type=Path, default=OUT_DIR / "judgements.csv")
    parser.add_argument("--model", type=str, default=None,
                        help="Judge model key from configs/models.json (default: gemma4-26b)")
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--single-pass", action="store_true",
                        help="Run each pair once (no order-swap consistency check)")
    args = parser.parse_args()

    cfg_path = ROOT_DIR / "configs" / "models.json"
    cfg = json.loads(cfg_path.read_text())
    model_key = args.model or "gemma4-26b"
    model_cfg = cfg["models"][model_key]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]

    arm_a = load_arm(args.arm_a)
    arm_b = load_arm(args.arm_b)
    common = sorted(set(arm_a) & set(arm_b))
    log.info("Arm A: %d | Arm B: %d | common: %d", len(arm_a), len(arm_b), len(common))

    if args.limit:
        common = common[: args.limit]

    rng = random.Random(args.seed)

    # Build judging tasks. Each sctid becomes one or two judgements.
    tasks: list[dict] = []
    for sctid in common:
        a = arm_a[sctid]
        b = arm_b[sctid]
        if a["translation"].strip() == b["translation"].strip():
            # Identical translations — skip, record as tie directly
            tasks.append({
                "sctid": sctid,
                "english": a["preferred_term"],
                "reference": a["ko_reference"],
                "a_translation": a["translation"],
                "b_translation": b["translation"],
                "mode": "identical",
            })
            continue
        # Order-randomised first pass
        left_is_a = rng.random() < 0.5
        tasks.append({
            "sctid": sctid,
            "english": a["preferred_term"],
            "reference": a["ko_reference"],
            "a_translation": a["translation"],
            "b_translation": b["translation"],
            "mode": "primary",
            "left_is_a": left_is_a,
        })
        if not args.single_pass:
            # Swap-order second pass for consistency check
            tasks.append({
                "sctid": sctid,
                "english": a["preferred_term"],
                "reference": a["ko_reference"],
                "a_translation": a["translation"],
                "b_translation": b["translation"],
                "mode": "swap",
                "left_is_a": not left_is_a,
            })

    wait_for_server(base_url)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    outf = args.output.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf,
        fieldnames=["sctid", "english", "reference", "a_translation", "b_translation",
                    "mode", "left_is_a", "verdict", "winner", "reasoning"],
    )
    writer.writeheader()

    lock = Lock()
    done = [0]
    t0 = time.monotonic()

    def run_one(task: dict) -> dict:
        base = {
            "sctid": task["sctid"],
            "english": task["english"],
            "reference": task["reference"],
            "a_translation": task["a_translation"],
            "b_translation": task["b_translation"],
            "mode": task["mode"],
            "left_is_a": task.get("left_is_a", ""),
        }
        if task["mode"] == "identical":
            base.update({"verdict": "TIE", "winner": "tie",
                         "reasoning": "Identical translations"})
            return base
        left_is_a = task["left_is_a"]
        left = task["a_translation"] if left_is_a else task["b_translation"]
        right = task["b_translation"] if left_is_a else task["a_translation"]
        try:
            verdict, reasoning = judge_one(base_url, model_id,
                                           task["english"], task["reference"],
                                           left, right)
        except Exception as exc:
            verdict, reasoning = "ERROR", str(exc)[:200]

        if verdict == "LEFT":
            winner = "A" if left_is_a else "B"
        elif verdict == "RIGHT":
            winner = "B" if left_is_a else "A"
        elif verdict == "TIE":
            winner = "tie"
        else:
            winner = verdict
        base.update({"verdict": verdict, "winner": winner, "reasoning": reasoning})
        return base

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(run_one, t) for t in tasks]
        for fut in as_completed(futures):
            result = fut.result()
            with lock:
                writer.writerow(result)
                outf.flush()
                done[0] += 1
                if done[0] % 50 == 0:
                    elapsed = time.monotonic() - t0
                    rate = done[0] / elapsed if elapsed > 0 else 0
                    eta = (len(tasks) - done[0]) / rate if rate > 0 else 0
                    log.info("Progress: %d/%d | %.1f req/s | ETA %.0fs",
                             done[0], len(tasks), rate, eta)

    outf.close()
    log.info("Wrote %s", args.output)

    # --- Summary ---
    print_summary(args.output, single_pass=args.single_pass)


def print_summary(output: Path, *, single_pass: bool) -> None:
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    # Group by sctid
    by_sctid: dict[str, list[dict]] = {}
    for r in rows:
        by_sctid.setdefault(r["sctid"], []).append(r)

    identical = 0
    consistent_a = 0
    consistent_b = 0
    consistent_tie = 0
    inconsistent = 0
    errors = 0
    total_judged = 0

    for sctid, group in by_sctid.items():
        modes = {g["mode"] for g in group}
        if modes == {"identical"}:
            identical += 1
            continue
        if any(g["winner"] == "ERROR" for g in group):
            errors += 1
            continue
        winners = [g["winner"] for g in group if g["mode"] in {"primary", "swap"}]
        total_judged += 1
        if single_pass or len(winners) < 2:
            # Single-pass: take the one verdict as-is
            w = winners[0]
            if w == "A":
                consistent_a += 1
            elif w == "B":
                consistent_b += 1
            elif w == "tie":
                consistent_tie += 1
            else:
                inconsistent += 1
        else:
            # Two-pass: only count consistent verdicts
            if winners[0] == winners[1]:
                w = winners[0]
                if w == "A":
                    consistent_a += 1
                elif w == "B":
                    consistent_b += 1
                elif w == "tie":
                    consistent_tie += 1
                else:
                    inconsistent += 1
            else:
                inconsistent += 1

    print("\n=== Pairwise ablation summary ===")
    print(f"Total sctids      : {len(by_sctid)}")
    print(f"  identical       : {identical}")
    print(f"  judged          : {total_judged}")
    print(f"  errors          : {errors}")
    print()
    if single_pass:
        print("Single-pass verdicts (primary only):")
    else:
        print("Consistent two-pass verdicts (primary and swap agree):")
    print(f"  A wins          : {consistent_a}")
    print(f"  B wins          : {consistent_b}")
    print(f"  tie             : {consistent_tie}")
    print(f"  inconsistent    : {inconsistent}")
    denom = consistent_a + consistent_b + consistent_tie + inconsistent
    if denom:
        print()
        print(f"A win rate (of consistent non-inconsistent): "
              f"{consistent_a / (consistent_a + consistent_b + consistent_tie) * 100:.1f}%"
              if (consistent_a + consistent_b + consistent_tie) else "n/a")
        print(f"B win rate (of consistent non-inconsistent): "
              f"{consistent_b / (consistent_a + consistent_b + consistent_tie) * 100:.1f}%"
              if (consistent_a + consistent_b + consistent_tie) else "n/a")


if __name__ == "__main__":
    main()
