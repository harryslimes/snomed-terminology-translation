#!/usr/bin/env python3
"""Reference-free Sonnet judge for SME-review preparation.

For each (English source, candidate Korean) pair, asks Sonnet to:
  - rate the candidate on a label (looks_correct / partial / wrong)
  - identify what aspect is right/wrong (site / modality / word_order / suffix / particle / other)
  - propose an improved Korean translation
  - state confidence

There's no KR reference here — these are long-tail concepts with no
KHIS-authored Korean. Sonnet judges purely on whether the Korean
plausibly conveys the English SNOMED concept's meaning following the
conventions documented in the abbreviated Korean style guide.
"""
from __future__ import annotations
import argparse, asyncio, csv, json, logging, re, sys, time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from claude_agent_sdk import query, ClaudeAgentOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sonnet_review")


SYSTEM = """\
You are a senior Korean medical terminology reviewer with deep knowledge of SNOMED CT \
and the KHIS Korean SNOMED extension conventions. Your task is to evaluate machine-generated \
Korean translations of SNOMED CT clinical procedure concepts, where there is NO KHIS \
reference translation available (these are long-tail concepts).

Korean SNOMED conventions you should apply:
- Korean is head-final SOV: action / modality at the end, body site / modifiers before.
- Default to no genitive 의 between site and action ('간 배액', not '간의 배액').
- Default to bare nominal forms ('절제', not '절제술'); '-술' only for fixed compounds (내시경술, 우회술, 창냄술, 형성술 etc.).
- Imaging modalities are spaced word-by-word: '컴퓨터 단층 촬영' (CT), '자기 공명 영상' (MRI), '초음파 검사' (US).
- Contrast goes BEFORE the body site: '조영제 사용 [site] [modality]'.
- Anatomy: prefer Sino-Korean for viscera (신장, 결장, 충수); pure Korean for surface anatomy and bones (위팔, 어깨뼈).
- Laterality: '왼쪽/오른쪽' over '좌측/우측'.

Evaluate the candidate translation and return ONLY a single JSON object with:
{
  "label": "ACCEPTABLE" | "PARTIAL" | "WRONG",
  "what_is_right": "<short note on what the candidate gets right, or empty if nothing>",
  "what_is_wrong": "<short note on what's wrong; empty if ACCEPTABLE>",
  "wrong_aspect": "<one of: site | modality | word_order | suffix | particle | additional_word | missing_word | other | none>",
  "suggested_translation": "<your better Korean translation, or the candidate verbatim if ACCEPTABLE>",
  "confidence": "high" | "medium" | "low"
}

Definitions:
- ACCEPTABLE: a Korean medical professional would accept the translation as a valid rendering of the English concept, using sound terminology and grammatical Korean.
- PARTIAL: captures the core concept but has a meaningful defect (wrong suffix, missing modifier, wrong word order, wrong anatomy variant, etc.).
- WRONG: the Korean does not convey the English meaning correctly; refers to a different concept, hallucinated text, or ungrammatical Korean.

Reasoning may use English or Korean, but the suggested_translation must be in Hangul only.
"""


USER = """\
English source (SNOMED preferred term): {english}
Body site (English FSN): {site_fsn}
Modality (English FSN): {method_fsn}
Candidate Korean translation: {korean}

Evaluate the candidate."""


def parse_response(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        obj = json.loads(text)
        return {
            "label": str(obj.get("label", "UNKNOWN")).upper(),
            "what_is_right": str(obj.get("what_is_right", "")),
            "what_is_wrong": str(obj.get("what_is_wrong", "")),
            "wrong_aspect": str(obj.get("wrong_aspect", "")),
            "suggested_translation": str(obj.get("suggested_translation", "")),
            "confidence": str(obj.get("confidence", "")),
        }
    except json.JSONDecodeError:
        return {
            "label": "UNKNOWN", "what_is_right": "", "what_is_wrong": text[:200],
            "wrong_aspect": "", "suggested_translation": "", "confidence": "",
        }


def extract_text(message) -> str:
    parts = []
    if hasattr(message, "content"):
        for block in message.content:
            if hasattr(block, "text"):
                parts.append(block.text)
    return "".join(parts)


async def judge_one(sem, options, english, site_fsn, method_fsn, korean,
                     max_retries=3) -> tuple[dict, float]:
    user = USER.format(english=english, site_fsn=site_fsn or "(none)",
                        method_fsn=method_fsn or "(none)", korean=korean)
    last_text = ""
    last_cost = 0.0
    for attempt in range(max_retries):
        text = ""
        cost = 0.0
        async with sem:
            try:
                async for m in query(prompt=user, options=options):
                    name = type(m).__name__
                    if name == "AssistantMessage":
                        text += extract_text(m)
                    elif name == "ResultMessage":
                        cost = getattr(m, "total_cost_usd", 0.0) or 0.0
            except Exception as exc:
                last_text = f"ERROR: {str(exc)[:200]}"
                await asyncio.sleep(1 + 3 ** attempt)
                continue
        last_text = text
        last_cost = cost
        parsed = parse_response(text)
        if parsed["label"] != "UNKNOWN":
            return parsed, cost
        await asyncio.sleep(1)
    return parse_response(last_text), last_cost


async def main_async() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True,
                   help="CSV with sctid, preferred_term, translation, site_fsn, method_fsn columns.")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", type=str, default="claude-sonnet-4-6")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    rows = list(csv.DictReader(args.input.open(encoding="utf-8")))
    rows = [r for r in rows if not r.get("translation", "").startswith("ERROR")]
    if args.limit:
        rows = rows[: args.limit]

    log.info("Sonnet review (no ref): %d rows at concurrency %d", len(rows), args.concurrency)

    # Block the 21 MCP tools that get auto-loaded from the user's claude.ai
    # account (Gmail / Drive / Calendar / snowstorm). When Sonnet sees these
    # without runtime access it generates "I don't have live tool access"
    # multi-turn prose, which crashes the CLI subprocess at concurrency >1.
    # Listing them in disallowed_tools strips them from the prompt entirely.
    MCP_TOOLS = [
        "mcp__claude_ai_Gmail__authenticate",
        "mcp__claude_ai_Gmail__complete_authentication",
        "mcp__claude_ai_Google_Calendar__authenticate",
        "mcp__claude_ai_Google_Calendar__complete_authentication",
        "mcp__claude_ai_Google_Drive__authenticate",
        "mcp__claude_ai_Google_Drive__complete_authentication",
        "mcp__claude_ai_snowstorm_mcp__fhir_metadata",
        "mcp__claude_ai_snowstorm_mcp__list_terminologies",
        "mcp__claude_ai_snowstorm_mcp__server_capabilities",
        "mcp__claude_ai_snowstorm_mcp__server_health",
        "mcp__claude_ai_snowstorm_mcp__snomed_expand",
        "mcp__claude_ai_snowstorm_mcp__snomed_get_ancestors",
        "mcp__claude_ai_snowstorm_mcp__snomed_get_children",
        "mcp__claude_ai_snowstorm_mcp__snomed_get_descendants",
        "mcp__claude_ai_snowstorm_mcp__snomed_lookup",
        "mcp__claude_ai_snowstorm_mcp__snomed_subsumes",
        "mcp__claude_ai_snowstorm_mcp__snomed_validate_code",
        "mcp__claude_ai_snowstorm_mcp__snowstorm_get_concept_native",
        "mcp__claude_ai_snowstorm_mcp__snowstorm_list_codesystems",
        "mcp__claude_ai_snowstorm_mcp__snowstorm_list_versions",
        "mcp__claude_ai_snowstorm_mcp__snowstorm_search_concepts",
    ]

    options = ClaudeAgentOptions(
        model=args.model, system_prompt=SYSTEM,
        tools=[], allowed_tools=[], disallowed_tools=MCP_TOOLS,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    outf = args.output.open("w", encoding="utf-8", newline="")
    fieldnames = list(rows[0].keys()) + [
        "sonnet_label", "sonnet_what_is_right", "sonnet_what_is_wrong",
        "sonnet_wrong_aspect", "sonnet_suggested", "sonnet_confidence", "sonnet_cost_usd",
    ]
    writer = csv.DictWriter(outf, fieldnames=fieldnames)
    writer.writeheader()

    # Warm cache sequentially
    log.info("Warming prompt cache...")
    r0 = rows[0]
    parsed0, cost0 = await judge_one(
        asyncio.Semaphore(1), options,
        r0["preferred_term"], r0.get("site_fsn", ""), r0.get("method_fsn", ""),
        r0["translation"],
    )
    log.info("  warm-up cost: $%.4f", cost0)
    writer.writerow({
        **r0,
        "sonnet_label": parsed0["label"],
        "sonnet_what_is_right": parsed0["what_is_right"],
        "sonnet_what_is_wrong": parsed0["what_is_wrong"],
        "sonnet_wrong_aspect": parsed0["wrong_aspect"],
        "sonnet_suggested": parsed0["suggested_translation"],
        "sonnet_confidence": parsed0["confidence"],
        "sonnet_cost_usd": f"{cost0:.6f}",
    })
    outf.flush()
    total_cost = cost0
    counts = {parsed0["label"]: 1}
    t0 = time.monotonic()

    sem = asyncio.Semaphore(args.concurrency)

    async def go(row):
        parsed, cost = await judge_one(
            sem, options,
            row["preferred_term"], row.get("site_fsn", ""), row.get("method_fsn", ""),
            row["translation"],
        )
        return row, parsed, cost

    tasks = [asyncio.create_task(go(r)) for r in rows[1:]]
    done = 1
    for coro in asyncio.as_completed(tasks):
        row, parsed, cost = await coro
        total_cost += cost
        counts[parsed["label"]] = counts.get(parsed["label"], 0) + 1
        writer.writerow({
            **row,
            "sonnet_label": parsed["label"],
            "sonnet_what_is_right": parsed["what_is_right"],
            "sonnet_what_is_wrong": parsed["what_is_wrong"],
            "sonnet_wrong_aspect": parsed["wrong_aspect"],
            "sonnet_suggested": parsed["suggested_translation"],
            "sonnet_confidence": parsed["confidence"],
            "sonnet_cost_usd": f"{cost:.6f}",
        })
        outf.flush()
        done += 1
        if done % 20 == 0:
            elapsed = time.monotonic() - t0
            rate = done / elapsed if elapsed else 0
            eta = (len(rows) - done) / rate if rate else 0
            log.info("Progress: %d/%d | %.1f req/s | ETA %.0fs | cost=$%.2f | labels=%s",
                     done, len(rows), rate, eta, total_cost, counts)

    outf.close()
    log.info("Done. Wrote %s | cost=$%.2f | labels=%s",
             args.output, total_cost, counts)


if __name__ == "__main__":
    asyncio.run(main_async())
