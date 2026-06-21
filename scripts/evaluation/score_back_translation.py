#!/usr/bin/env python3
"""Score translations by back-translating KO→EN and comparing to source EN.

Pipeline:
  1. For each (english_source, korean_translation) pair, ask an LLM to
     translate the Korean back into English (medical terminology).
  2. Embed original EN and back-translated EN with BGE-M3.
  3. Compute cosine similarity. Low similarity = translation likely lost meaning.

This is a reference-free quality signal. Unlike
score_cross_lingual_similarity.py, back-translation works on the long tail
where no KR reference exists — only requires the source English and our
Korean output.

Uses a local vLLM endpoint (default: gemma4-26b at localhost:8083) for the
KO→EN pass. Output rows include the back-translated English for manual
inspection.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import numpy as np
import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.qdrant_store import BGEM3Config, BGEM3Embedder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("back_trans")


SYSTEM = """\
You are a medical terminology translator. Given a Korean SNOMED CT term, produce \
the most likely English SNOMED-style equivalent. Return ONLY the English — no \
explanation, no romanisation, no Korean, no extra text.\
"""

USER = "Korean: {korean}\nEnglish:"


def back_translate(base_url: str, model_id: str, korean: str, timeout: int = 60) -> str:
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(korean=korean)},
        ],
        "max_tokens": 64,
        "temperature": 0.0,
        "stop": ["\n\n", "Korean:"],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    if "<think>" in (content or ""):
        content = content.split("</think>")[-1]
    return (content or "").strip().strip('"').strip("'").strip()


def wait_ready(base_url: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(3)
    raise SystemExit("LLM backend not ready")


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    an = np.linalg.norm(a, axis=1, keepdims=True) + 1e-12
    bn = np.linalg.norm(b, axis=1, keepdims=True) + 1e-12
    return np.sum((a / an) * (b / bn), axis=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=str, default="gemma4-26b")
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    import json
    cfg = json.loads((ROOT_DIR / "configs" / "models.json").read_text())
    model_cfg = cfg["models"][args.model]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]

    rows = list(csv.DictReader(args.translations.open(encoding="utf-8")))
    rows = [r for r in rows if not r.get("translation", "").startswith("ERROR")]
    if args.limit:
        rows = rows[: args.limit]
    log.info("Back-translating %d rows via %s", len(rows), args.model)

    wait_ready(base_url)

    back_trans: list[str] = [""] * len(rows)
    lock = Lock()
    errors = [0]

    def one(i: int, ko: str) -> None:
        try:
            back_trans[i] = back_translate(base_url, model_id, ko)
        except Exception as exc:
            back_trans[i] = f"ERROR: {exc}"
            with lock:
                errors[0] += 1

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(one, i, r["translation"]) for i, r in enumerate(rows)]
        done = 0
        for _ in as_completed(futures):
            done += 1
            if done % 100 == 0:
                rate = done / (time.monotonic() - t0)
                eta = (len(rows) - done) / rate if rate > 0 else 0
                log.info("Back-translate: %d/%d | %.1f req/s | ETA %.0fs | errors=%d",
                         done, len(rows), rate, eta, errors[0])
    log.info("Back-translate done in %.0fs, %d errors", time.monotonic() - t0, errors[0])

    # Embed source EN and back-translated EN
    log.info("Embedding...")
    embedder = BGEM3Embedder(BGEM3Config())
    en_src = [r["preferred_term"] for r in rows]
    en_back = back_trans

    def embed(texts):
        dense, _ = embedder.encode_documents(texts)
        return np.asarray(dense, dtype=np.float32)

    en_src_emb = embed(en_src)
    en_back_emb = embed(en_back)
    sim_back = cosine(en_src_emb, en_back_emb)

    # Write
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) + ["back_translated", "sim_en_back"]
    with args.output.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for i, r in enumerate(rows):
            out = dict(r)
            out["back_translated"] = en_back[i]
            out["sim_en_back"] = f"{float(sim_back[i]):.4f}"
            w.writerow(out)

    log.info("Wrote %s", args.output)

    def pct(a, q): return float(np.percentile(a, q))
    log.info("sim(source EN, back-translated EN)  mean=%.3f  p10=%.3f  p50=%.3f  p90=%.3f",
             float(sim_back.mean()), pct(sim_back, 10), pct(sim_back, 50), pct(sim_back, 90))


if __name__ == "__main__":
    main()
