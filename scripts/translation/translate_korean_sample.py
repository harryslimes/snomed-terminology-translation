#!/usr/bin/env python
"""Translate a sample of SNOMED procedure concepts EN -> Korean using Qwen 3.5 35B.

Two modes:
  --mode baseline   : minimal prompt, no style guide
  --mode styleguide : prepends the Korean SNOMED style guide as context

Reads:  data/evals/korean/procedure_eval_sample_100.csv
        (sctid, preferred_term, hierarchy, ko_reference)
Writes: data/evals/korean/translations_qwen35b_<mode>.csv
        (sctid, preferred_term, ko_reference, translation)
"""
from __future__ import annotations

import argparse
import csv
import logging
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("translate_korean_sample")

import os
BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8002")
MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen3.5-35B-A3B-GPTQ-Int4")
TAG = os.getenv("OUTPUT_TAG", "qwen35b")
INPUT = Path(os.getenv("INPUT_CSV", "data/evals/korean/procedure_eval_sample_100.csv"))
STYLE_GUIDE_PATH = Path("style_guide/style_guide_ko.md")

BASELINE_SYSTEM = """\
You are a medical terminology translator specialising in English to Korean translation \
of SNOMED CT clinical terms. Return ONLY the Korean translation in Hangul (한글) — no \
explanation, no quotes, no romanisation, no English, no extra text. If the term contains \
a well-known Latin chemical name, drug name, eponym, or gene/marker symbol that is \
conventionally kept in Latin script in Korean medical writing, you may keep that part \
in Latin script."""

STYLEGUIDE_SYSTEM_TEMPLATE = """\
You are a medical terminology translator specialising in English to Korean translation \
of SNOMED CT clinical terms in the **Procedure** hierarchy. You must follow the style \
guide below, which was derived from the official KHIS Korean SNOMED CT national \
extension (KR1000267). Return ONLY the Korean translation in Hangul (한글) — no \
explanation, no quotes, no romanisation, no English, no extra text.

# Korean SNOMED CT translation style guide

{style_guide}
"""


def wait_for_server(timeout: int = 900) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/v1/models", timeout=5)
            if r.status_code == 200:
                log.info("vLLM ready: %s", [m["id"] for m in r.json().get("data", [])])
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise SystemExit(f"vLLM not ready within {timeout}s")


def translate(system_prompt: str, english: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Translate this SNOMED CT procedure term from English to Korean.\n"
                    f"English: {english}\n"
                    f"Korean:"
                ),
            },
        ],
        "max_tokens": 128,
        "temperature": 0.1,
        "stop": ["\n\n", "English:"],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload, timeout=180)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    if "<think>" in content:
        content = content.split("</think>")[-1]
    return content.strip().strip('"').strip("'").strip()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["baseline", "styleguide"], required=True)
    args = p.parse_args()

    if args.mode == "styleguide":
        guide = STYLE_GUIDE_PATH.read_text(encoding="utf-8")
        system_prompt = STYLEGUIDE_SYSTEM_TEMPLATE.format(style_guide=guide)
    else:
        system_prompt = BASELINE_SYSTEM

    rows = list(csv.DictReader(INPUT.open(encoding="utf-8")))
    log.info("Mode=%s  rows=%d  system_prompt_chars=%d", args.mode, len(rows), len(system_prompt))

    wait_for_server()

    out_path = Path(f"data/evals/korean/translations_{TAG}_{args.mode}.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["sctid", "preferred_term", "ko_reference", "translation"]
        )
        w.writeheader()
        for i, row in enumerate(rows, 1):
            try:
                t = translate(system_prompt, row["preferred_term"])
            except Exception as exc:
                log.error("[%d/%d] %s -> ERROR %s", i, len(rows), row["preferred_term"], exc)
                t = f"ERROR: {exc}"
            log.info("[%d/%d] %s | ref=%s | got=%s",
                     i, len(rows), row["preferred_term"][:40], row["ko_reference"], t)
            w.writerow({
                "sctid": row["sctid"],
                "preferred_term": row["preferred_term"],
                "ko_reference": row["ko_reference"],
                "translation": t,
            })
            f.flush()

    log.info("Wrote %s", out_path)


if __name__ == "__main__":
    main()
