#!/usr/bin/env python3
"""LLM-as-judge for Korean SNOMED translations using Claude Sonnet 4.6.

A cross-check alternative to `judge_korean_translations.py` (which uses the
local gemma4-26b). Uses the Claude Agent SDK with the user's locally-stored
Claude Code credentials — no ANTHROPIC_API_KEY required, just a logged-in
Claude Code installation.

Efficiency notes:
  - Passes `tools=[]` and `allowed_tools=[]` to strip tool descriptions
    from the system prompt (cuts cache-creation tokens ~6×).
  - After the first call warms the prompt cache, subsequent rows cost
    ~$0.002 each. A 774-row run costs ~$1-2.
  - Classifications match the existing ACCEPTABLE / PARTIAL / WRONG labels
    so the output is directly comparable with judge_korean_translations.py.

Input: a translations CSV with columns sctid, preferred_term (English PT),
ko_reference, translation.
Output: same columns plus `label` and `reasoning` from the Sonnet judge.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import re
import sys
import time
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("judge_sonnet")


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


LABEL_RE = re.compile(r'"label"\s*:\s*"(ACCEPTABLE|PARTIAL|WRONG)"', re.IGNORECASE)


def parse_judge_response(content: str) -> tuple[str, str]:
    content = (content or "").strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL)
    try:
        obj = json.loads(content)
        label = str(obj.get("label", "")).upper().strip()
        reasoning = str(obj.get("reasoning", "")).strip()
        if label in {"ACCEPTABLE", "PARTIAL", "WRONG"}:
            return label, reasoning
    except json.JSONDecodeError:
        pass
    m = LABEL_RE.search(content)
    if m:
        return m.group(1).upper(), content[:200]
    up = content.upper()
    for lbl in ("ACCEPTABLE", "PARTIAL", "WRONG"):
        if lbl in up:
            return lbl, content[:200]
    return "UNKNOWN", content[:200]


def extract_text(message) -> str:
    """Accumulate text from AssistantMessage.content blocks."""
    parts: list[str] = []
    if hasattr(message, "content"):
        for block in message.content:
            if hasattr(block, "text"):
                parts.append(block.text)
    return "".join(parts)


async def judge_one(sem: asyncio.Semaphore, options: ClaudeAgentOptions,
                    english: str, reference: str, candidate: str,
                    max_retries: int = 3) -> tuple[str, str, float]:
    user = JUDGE_USER.format(english=english, reference=reference, candidate=candidate)
    last_exc = ""
    for attempt in range(max_retries):
        text = ""
        cost_usd = 0.0
        async with sem:
            try:
                async for m in query(prompt=user, options=options):
                    name = type(m).__name__
                    if name == "AssistantMessage":
                        text += extract_text(m)
                    elif name == "ResultMessage":
                        cost_usd = getattr(m, "total_cost_usd", 0.0) or 0.0
            except Exception as exc:
                last_exc = str(exc)[:200]
                # exponential backoff: 1s, 3s, 9s
                await asyncio.sleep(1 + (3 ** attempt))
                continue
        label, reasoning = parse_judge_response(text)
        if label != "UNKNOWN":
            return label, reasoning, cost_usd
        # fall through to retry on UNKNOWN parse
        last_exc = f"parse failed: {text[:120]!r}"
        await asyncio.sleep(1)
    return "ERROR", last_exc, 0.0


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=str, default="claude-sonnet-4-6")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true",
                        help="Skip sctids already in the output file.")
    args = parser.parse_args()

    rows = list(csv.DictReader(args.translations.open(encoding="utf-8")))
    rows = [r for r in rows if not r["translation"].startswith("ERROR")]
    if args.limit:
        rows = rows[: args.limit]

    done: set[str] = set()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w"
    if args.resume and args.output.exists():
        with args.output.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add(row["sctid"])
        mode = "a"
        log.info("Resuming: %d already judged", len(done))

    remaining = [r for r in rows if r["sctid"] not in done]
    log.info("Judging %d rows with %s at concurrency %d",
             len(remaining), args.model, args.concurrency)

    options = ClaudeAgentOptions(
        model=args.model,
        system_prompt=JUDGE_SYSTEM,
        tools=[],            # strip tool definitions from prompt
        allowed_tools=[],    # forbid any tool use at runtime
        # max_turns intentionally unset — Sonnet sometimes reports error_max_turns
        # on max_turns=1 for borderline classifications; our prompt is single-shot
        # anyway so a higher cap doesn't cost us anything.
    )

    # Warm the prompt cache with a single sequential call before fanning out
    # (keeps the first N concurrent calls from each re-creating the cache)
    if remaining:
        log.info("Warming prompt cache...")
        r0 = remaining[0]
        label0, reasoning0, cost0 = await judge_one(
            asyncio.Semaphore(1), options,
            r0["preferred_term"], r0["ko_reference"], r0["translation"],
        )
        log.info("  warm-up cost: $%.4f, label=%s", cost0, label0)
        first_result = (r0, label0, reasoning0, cost0)
        batch = remaining[1:]
    else:
        first_result = None
        batch = []

    outf = args.output.open(mode, encoding="utf-8", newline="")
    writer = csv.DictWriter(
        outf,
        fieldnames=["sctid", "english", "reference", "translation",
                    "label", "reasoning", "cost_usd"],
    )
    if mode == "w":
        writer.writeheader()

    def write_row(row, label, reasoning, cost):
        writer.writerow({
            "sctid": row["sctid"],
            "english": row["preferred_term"],
            "reference": row["ko_reference"],
            "translation": row["translation"],
            "label": label,
            "reasoning": reasoning,
            "cost_usd": f"{cost:.6f}",
        })
        outf.flush()

    if first_result:
        write_row(*first_result)

    sem = asyncio.Semaphore(args.concurrency)
    total_cost = first_result[3] if first_result else 0.0
    done_count = 1 if first_result else 0
    t0 = time.monotonic()
    label_counts: dict[str, int] = {}
    if first_result:
        label_counts[first_result[1]] = label_counts.get(first_result[1], 0) + 1

    async def run(row):
        label, reasoning, cost = await judge_one(
            sem, options, row["preferred_term"], row["ko_reference"], row["translation"]
        )
        return row, label, reasoning, cost

    tasks = [asyncio.create_task(run(r)) for r in batch]
    for coro in asyncio.as_completed(tasks):
        row, label, reasoning, cost = await coro
        total_cost += cost
        done_count += 1
        label_counts[label] = label_counts.get(label, 0) + 1
        write_row(row, label, reasoning, cost)
        if done_count % 25 == 0:
            elapsed = time.monotonic() - t0
            rate = done_count / elapsed if elapsed > 0 else 0
            eta = (len(remaining) - done_count) / rate if rate > 0 else 0
            log.info(
                "Progress: %d/%d | %.1f req/s | ETA %.0fs | cost=$%.2f | labels=%s",
                done_count, len(remaining), rate, eta, total_cost, dict(label_counts),
            )

    outf.close()
    log.info("Done. Wrote %s", args.output)
    log.info("Total cost: $%.2f | labels: %s", total_cost, dict(label_counts))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
