#!/usr/bin/env python3
"""Translate SNOMED procedure concepts EN -> Korean using bilingual pair lookup.

Replicates the Estonian translation pipeline's RAG approach:
  1. For each English term, search Qdrant (BGE-M3 hybrid) for similar EN-KO pairs
  2. Inject top-N pairs + style guide into prompt
  3. Call LLM via OpenAI-compatible API with concurrent requests

Two-step process to avoid OOM:
  Step 1 (--prepare-lookups): run BGE-M3 lookups, save to JSON, then exit
  Step 2 (default):           load JSON, translate concurrently (no embedder needed)

Config-driven: reads model/job settings from configs/models.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
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
log = logging.getLogger("translate_ko_lookup")

# Suppress noisy HTTP request logging from qdrant/httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def load_config(model_key: str | None = None) -> dict:
    cfg_path = ROOT_DIR / "configs" / "models.json"
    with cfg_path.open() as f:
        cfg = json.load(f)
    job = cfg["jobs"]["translate_korean_lookup"]
    model_key = model_key or job["default_model"]
    model = cfg["models"][model_key]
    return {"model": model, "model_key": model_key, "job": job}


SYSTEM_TEMPLATE = """\
You are a medical terminology translator specialising in English to Korean translation \
of SNOMED CT clinical terms in the **Procedure** hierarchy. You must follow the style \
guide below, which was derived from the official KHIS Korean SNOMED CT national \
extension (KR1000267). Return ONLY the Korean translation in Hangul (한글) — no \
explanation, no quotes, no romanisation, no English, no extra text.

# Korean SNOMED CT translation style guide

{style_guide}"""


USER_TEMPLATE = """\
Here are similar Korean SNOMED translations for reference:

{paired_translations}

Translate this SNOMED CT procedure term from English to Korean.
English: {english}
Korean:"""


LOOKUP_CACHE = Path("data/evals/korean/lookup_cache.json")


def wait_for_server(base_url: str, timeout: int = 900) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base_url}/v1/models",
                              headers=_auth_headers(), timeout=5)
            if r.status_code == 200:
                models = [m["id"] for m in r.json().get("data", [])]
                log.info("vLLM ready: %s", models)
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    raise SystemExit(f"vLLM not ready within {timeout}s")


def lookup_pairs(embedder, store, collection: str, text: str, topn: int,
                 query_filter=None, exclude_sctid: str | None = None
                 ) -> tuple[list[list[str]], list[list]]:
    """Top-N exemplars for one term, with optional per-concept self-exclusion.

    YAKE keyword expansion + BGE-M3 hybrid queries against the collection,
    merged keeping each hit's best score. A pure function of the live index —
    callers may cache the result, but the index is the source of truth.

    Each kept exemplar is ``[english, translation, source, sctid]`` — ``source``
    is the per-row provenance (SNOMED/EDI/…) shown to the translating model,
    ``sctid`` the concept id. When ``exclude_sctid`` is given, any hit whose
    ``sctid`` equals it is DROPPED (the query concept's own canonical entries —
    its FSN + synonyms — which are the gold we score against and must not be
    handed to the model). Returns ``(kept, excluded)`` where ``excluded`` rows
    are ``[english, translation, source, sctid, rank]`` for run-time reporting.
    """
    import yake

    kw_extractor = yake.KeywordExtractor(lan="en", n=1, dedupLim=0.7, top=10)
    keywords = [kw for kw, _ in kw_extractor.extract_keywords(text)]
    if text not in keywords:
        keywords = [text, *keywords]

    # A concept can have several descriptions (FSN + synonyms) clustered at the
    # top; widen the buffer when excluding so topn survivors still remain.
    limit = max(topn * 6, topn + 20) if exclude_sctid else max(topn * 3, topn)
    hits_by_id: dict[str, tuple[float, dict]] = {}
    for keyword in keywords:
        try:
            dense, sparse = embedder.encode_query(keyword)
            result = store.hybrid_query(
                collection_name=collection,
                dense_vector=dense,
                sparse_vector=sparse,
                limit=limit,
                query_filter=query_filter,
            )
            for point in result.points:
                payload = getattr(point, "payload", {}) or {}
                pid = str(getattr(point, "id", ""))
                score = float(getattr(point, "score", 0.0))
                if pid:
                    prev = hits_by_id.get(pid)
                    if prev is None or score > prev[0]:
                        hits_by_id[pid] = (score, payload)
        except Exception as exc:
            log.warning("Lookup failed for %r: %s", keyword, exc)

    ranked = sorted(hits_by_id.values(), key=lambda x: x[0], reverse=True)
    kept: list[list[str]] = []
    excluded: list[list] = []
    want = str(exclude_sctid) if exclude_sctid not in (None, "") else None
    # The pool deliberately keeps the SAME (en, ko) pair from several sources
    # (EDI and SNOMED both translating one term), so an undeduplicated top-N
    # spends its scarce slots on copies: measured on the 200-row SME set, ~50%
    # of prompts showed a duplicate and some showed the same Korean 3 times,
    # making top-5 an effective top-3. Deduplicate on the Korean string —
    # highest-scoring row wins and keeps its provenance.
    seen_ko: set[str] = set()
    for rank, (_, p) in enumerate(ranked, 1):
        row = [p.get("text", ""), p.get("translation", ""),
               p.get("row_source", ""), str(p.get("sctid") or "")]
        if want is not None and row[3] == want:
            # A self-hit competing for a shown slot — the leak we remove.
            if len(kept) < topn:
                excluded.append([*row, rank])
            continue
        key = (row[1] or "").replace(" ", "").strip()
        if not key or key in seen_ko:
            continue
        if len(kept) < topn:
            seen_ko.add(key)
            kept.append(row)
        if len(kept) >= topn:
            break
    return kept, excluded


def prepare_lookups(input_path: Path, collection: str, topn: int) -> None:
    """Phase 1: run all Qdrant lookups via BGE-M3, save results to JSON, then exit."""
    from agent.qdrant_store import BGEM3Config, BGEM3Embedder, QdrantHybridStore, direction_filter

    rows = list(csv.DictReader(input_path.open(encoding="utf-8")))
    log.info("Preparing lookups for %d terms (topn=%d)...", len(rows), topn)

    embedder = BGEM3Embedder(BGEM3Config())
    store = QdrantHybridStore()
    store.client.get_collections()

    filt = direction_filter("EN->KO")
    cache: dict[str, list[list[str]]] = {}

    for i, row in enumerate(rows, 1):
        kept, _excluded = lookup_pairs(
            embedder, store, collection, row["preferred_term"], topn, filt,
            exclude_sctid=row.get("sctid"))
        cache[row["sctid"]] = kept

        if i % 100 == 0:
            log.info("  lookups: %d/%d", i, len(rows))

    LOOKUP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    LOOKUP_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    log.info("Saved %d lookups to %s", len(cache), LOOKUP_CACHE)


def format_pairs_table(pairs: list[list[str]]) -> str:
    """Render exemplar rows as a markdown table for the prompt.

    Rows may be ``[en, ko]`` (legacy) or ``[en, ko, source, sctid]``. When
    provenance is present, a ``Source`` column is shown so the model knows an
    exemplar's origin (e.g. an Athena EDI/KCD7 match is a real translation but
    NOT a canonical SNOMED reference for this concept), and weighs it
    accordingly. The sctid is internal (exclusion key) and not rendered.
    """
    if not pairs:
        return "(no similar translations found)"
    has_source = any(len(p) >= 3 and (p[2] or "").strip() for p in pairs)
    if has_source:
        lines = ["|English|Korean|Source|", "|---|---|---|"]
        for p in pairs:
            en, ko = p[0], p[1]
            source = p[2] if len(p) >= 3 else ""
            lines.append(f"|{en}|{ko}|{source}|")
    else:
        lines = ["|English|Korean|", "|---|---|"]
        for p in pairs:
            lines.append(f"|{p[0]}|{p[1]}|")
    return "\n".join(lines)


def _auth_headers() -> dict:
    """Pick up an OpenAI-compatible API key from env (for remote endpoints
    such as Dashscope / OpenAI / Anthropic-compatible mirrors). vLLM running
    locally with no auth is fine — the header simply isn't sent."""
    key = (os.getenv("VLLM_API_KEY")
           or os.getenv("OPENAI_API_KEY")
           or os.getenv("DASHSCOPE_API_KEY"))
    return {"Authorization": f"Bearer {key}"} if key else {}


def translate_one(
    base_url: str,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    llm_params: dict,
    timeout: tuple[float, float | None] | float | None = (10, 300),
    return_usage: bool = False,
):
    """Single chat-completion call.

    Returns the cleaned completion text. When ``return_usage`` is True, returns
    ``(text, usage)`` where ``usage`` is the provider's token-usage dict
    (``prompt_tokens`` / ``completion_tokens`` / ``prompt_tokens_details`` with
    ``cached_tokens`` under vLLM prefix caching), or ``{}`` if absent.

    ``timeout`` is passed straight to ``requests``. The default ``(10, None)``
    is a (connect, read) pair: fail fast (10s) if vLLM is unreachable, but
    never time out a generation already in flight — a long run, or a thinking
    model emitting thousands of reasoning tokens under load, can legitimately
    take a very long time, and a flow may run for hours or days.
    """
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **llm_params,
    }
    r = requests.post(f"{base_url}/v1/chat/completions",
                      json=payload, headers=_auth_headers(), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    # Reasoning models (gpt-oss, qwen3-thinking) may emit only into
    # `reasoning_content` and leave `content` empty/None when the response
    # was truncated. Fall back to reasoning_content's last line so we
    # surface *something* instead of crashing the row.
    content = msg.get("content") or ""
    if not content.strip():
        rc = (msg.get("reasoning_content") or "").strip().splitlines()
        content = rc[-1] if rc else ""
    if "<think>" in content:
        content = content.split("</think>")[-1]
    content = content.strip().strip('"').strip("'").strip()
    if return_usage:
        return content, (data.get("usage") or {})
    return content


def smoke_test_throughput(
    base_url: str, model_id: str, system_prompt: str, llm_params: dict, concurrency: int
) -> None:
    test_prompts = [
        "Translate this SNOMED CT procedure term from English to Korean.\nEnglish: Excision of lung\nKorean:",
        "Translate this SNOMED CT procedure term from English to Korean.\nEnglish: Biopsy of liver\nKorean:",
        "Translate this SNOMED CT procedure term from English to Korean.\nEnglish: Total hip replacement\nKorean:",
    ] * min(concurrency, 6)
    test_prompts = test_prompts[:concurrency]
    log.info("Smoke test: %d concurrent requests...", len(test_prompts))
    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=len(test_prompts)) as pool:
        futs = [
            pool.submit(translate_one, base_url, model_id, system_prompt, p, llm_params)
            for p in test_prompts
        ]
        results = []
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as exc:
                log.warning("Smoke test request failed: %s", exc)

    elapsed = time.monotonic() - t0
    log.info(
        "Smoke test: %d/%d succeeded in %.1fs (%.1f req/s). Sample: %s",
        len(results), len(test_prompts), elapsed,
        len(results) / elapsed if elapsed > 0 else 0,
        results[0] if results else "N/A",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=None, help="Model key from configs/models.json")
    parser.add_argument("--topn", type=int, default=None, help="Override lookup pair count")
    parser.add_argument("--concurrency", type=int, default=None, help="Override concurrent requests")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows for testing")
    parser.add_argument("--resume", action="store_true", help="Resume from last written row")
    parser.add_argument("--smoke-test", action="store_true", help="Run throughput smoke test then exit")
    parser.add_argument("--prepare-lookups", action="store_true", help="Run lookups only, save to cache, then exit")
    parser.add_argument("--tag", type=str, default=None, help="Override output tag")
    parser.add_argument("--style-guide", type=Path, default=None, help="Override path to style guide")
    parser.add_argument("--sctid-filter", type=Path, default=None, help="Text file of sctids (one per line) to translate; others skipped")
    args = parser.parse_args()

    # Load config
    cfg = load_config(args.model)
    model_cfg = cfg["model"]
    job_cfg = cfg["job"]
    model_key = cfg["model_key"]

    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]
    concurrency = args.concurrency or job_cfg.get("concurrency", 16)
    topn = args.topn or job_cfg.get("lookup_topn", 5)
    tag = args.tag or os.getenv("OUTPUT_TAG", model_key)
    collection = job_cfg.get("qdrant_collection", "paired_translations_ko")
    llm_params = job_cfg.get("llm_params", {})

    input_path = Path(os.getenv("INPUT_CSV", job_cfg["eval_set"]))
    style_guide_path = args.style_guide or Path(job_cfg.get("style_guide", "style_guide/style_guide_ko.md"))

    # --- Prepare lookups mode (separate process, loads BGE-M3) ---
    if args.prepare_lookups:
        prepare_lookups(input_path, collection, topn)
        return

    # --- Load style guide (becomes cached prefix in vLLM) ---
    guide = style_guide_path.read_text(encoding="utf-8")
    system_prompt = SYSTEM_TEMPLATE.format(style_guide=guide)

    log.info(
        "Config: model=%s base_url=%s concurrency=%d topn=%d system_prompt=%d chars",
        model_key, base_url, concurrency, topn, len(system_prompt),
    )

    # Wait for LLM
    wait_for_server(base_url)

    # Smoke test mode
    if args.smoke_test:
        smoke_test_throughput(base_url, model_id, system_prompt, llm_params, concurrency)
        return

    # --- Load lookup cache ---
    if not LOOKUP_CACHE.exists():
        log.error("Lookup cache not found at %s. Run with --prepare-lookups first.", LOOKUP_CACHE)
        sys.exit(1)
    lookup_cache = json.loads(LOOKUP_CACHE.read_text(encoding="utf-8"))
    log.info("Loaded %d cached lookups from %s", len(lookup_cache), LOOKUP_CACHE)

    # Load eval set
    rows = list(csv.DictReader(input_path.open(encoding="utf-8")))
    if args.sctid_filter:
        keep = {line.strip() for line in args.sctid_filter.read_text().splitlines() if line.strip()}
        rows = [r for r in rows if r["sctid"] in keep]
        log.info("Filtered to %d rows via %s", len(rows), args.sctid_filter)
    if args.limit:
        rows = rows[:args.limit]
    log.info("Eval set: %d rows", len(rows))

    # Output path
    out_path = Path(job_cfg["output_dir"]) / f"translations_{tag}_lookup.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume support
    done_sctids = set()
    if args.resume and out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done_sctids.add(row["sctid"])
        log.info("Resuming: %d already done", len(done_sctids))

    remaining = [r for r in rows if r["sctid"] not in done_sctids]
    log.info("Remaining: %d rows to translate", len(remaining))

    if not remaining:
        log.info("Nothing to do.")
        return

    # --- Concurrent translation ---
    log.info("Translating %d terms with concurrency=%d...", len(remaining), concurrency)

    write_lock = Lock()
    completed = [0]
    errors = [0]
    t0 = time.monotonic()

    mode = "a" if args.resume and done_sctids else "w"
    outf = out_path.open(mode, encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf, fieldnames=["sctid", "preferred_term", "ko_reference", "translation"]
    )
    if mode == "w":
        writer.writeheader()

    def process_row(row: dict) -> dict:
        english = row["preferred_term"]
        pairs = lookup_cache.get(row["sctid"], [])
        pairs_table = format_pairs_table(pairs)
        user_prompt = USER_TEMPLATE.format(
            paired_translations=pairs_table,
            english=english,
        )
        try:
            t = translate_one(base_url, model_id, system_prompt, user_prompt, llm_params)
        except Exception as exc:
            log.error("%s -> ERROR %s", english[:40], exc)
            t = f"ERROR: {exc}"
        return {
            "sctid": row["sctid"],
            "preferred_term": english,
            "ko_reference": row["ko_reference"],
            "translation": t,
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(process_row, row): row for row in remaining}
        for fut in as_completed(futures):
            result = fut.result()
            with write_lock:
                writer.writerow(result)
                outf.flush()
                completed[0] += 1
                if result["translation"].startswith("ERROR"):
                    errors[0] += 1
                if completed[0] % 50 == 0:
                    elapsed = time.monotonic() - t0
                    rate = completed[0] / elapsed if elapsed > 0 else 0
                    eta = (len(remaining) - completed[0]) / rate if rate > 0 else 0
                    log.info(
                        "Progress: %d/%d (%.0f%%) | %.1f req/s | ETA %.0fs | errors: %d",
                        completed[0], len(remaining),
                        100 * completed[0] / len(remaining),
                        rate, eta, errors[0],
                    )

    outf.close()
    elapsed = time.monotonic() - t0
    log.info(
        "Done. Wrote %s (%d translations, %d errors, %.0fs, %.1f req/s)",
        out_path, completed[0], errors[0], elapsed,
        completed[0] / elapsed if elapsed > 0 else 0,
    )


if __name__ == "__main__":
    main()
