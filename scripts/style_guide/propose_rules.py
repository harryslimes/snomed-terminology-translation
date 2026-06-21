#!/usr/bin/env python3
"""Propose style-guide additions from consensus translation errors.

Reads two judge CSVs (e.g. from Gemma and Qwen), finds rows where BOTH judges
labelled the translation as WRONG, and asks an LLM to propose general rules
that would prevent those errors — without being over-fitted to the specific
examples shown.

Reads:
  data/evals/korean/judge_gemma4-26b.csv
  data/evals/korean/judge_qwen35b.csv
  style_guide/style_guide_ko.md

Writes:
  style_guide/proposed_rules_<tag>.md
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("propose_rules")


SYSTEM_PROMPT = """\
You are a Korean medical terminology style-guide author for SNOMED CT translation. \
Your task is to propose ADDITIONS to an existing Korean translation style guide, \
based on a set of translation errors where the candidate translation was judged \
semantically wrong by two independent medical-language reviewers.

You will be shown:
1. The current style guide (for context — do NOT duplicate or contradict existing rules).
2. A list of translation errors, each with:
   - the English SNOMED term
   - the reference Korean translation (from the official KHIS KR1000267 extension)
   - the incorrect candidate translation
   - the reasoning from each judge explaining why it is wrong.

Your job is to look across ALL the errors and identify GENERAL PATTERNS — \
recurring confusions, wrong vocabulary choices, verb/suffix conventions, or \
anatomical term preferences — that if formalised as rules would help prevent \
similar errors in the future.

CRITICAL CONSTRAINTS:
- Rules must be GENERAL. Do NOT refer to specific SCTIDs or name individual terms \
  as the primary motivation for a rule. A reader should not need the example list \
  to understand or apply the rule.
- Rules must be ACTIONABLE. Each rule should tell a translator what to do or avoid, \
  not just describe a phenomenon.
- Rules must NOT duplicate existing style-guide content. If a relevant rule already \
  exists, do not repeat it — only propose genuine additions or clarifications.
- Rules must be CONSISTENT with the existing style guide's tone, structure, and \
  conventions (markdown with bold keywords, short tables where useful).
- If the errors seem to stem from reference inconsistencies rather than a learnable \
  rule, SAY SO honestly — do not invent a rule for an unlearnable pattern.
- Aim for 3–8 high-quality rules, not a long list. Quality over quantity.

Output format: markdown. Start with a single top-level heading "## Proposed additions \
(from error analysis)" followed by your rules. Use sub-headings for each rule. For \
each rule include: (a) the rule itself in one or two sentences, (b) a brief rationale \
referring to the PATTERN observed across errors (not individual cases), (c) optional: \
a small vocabulary table if it helps.

Return ONLY the markdown — no preamble, no explanation before the heading."""


USER_TEMPLATE = """\
# Current style guide

```markdown
{style_guide}
```

# Translation errors (consensus WRONG by two independent judges)

{errors}

Now propose general style-guide additions following the constraints in the system message."""


def find_consensus_errors(
    judge_a_path: Path, judge_b_path: Path, label: str = "WRONG"
) -> list[dict]:
    """Return rows where both judges assigned the same label."""
    a = {r["sctid"]: r for r in csv.DictReader(judge_a_path.open(encoding="utf-8"))}
    b = {r["sctid"]: r for r in csv.DictReader(judge_b_path.open(encoding="utf-8"))}
    common = set(a) & set(b)
    consensus = []
    for sctid in common:
        if a[sctid]["label"] == label and b[sctid]["label"] == label:
            consensus.append({
                "sctid": sctid,
                "english": a[sctid]["english"],
                "reference": a[sctid]["reference"],
                "translation": a[sctid]["translation"],
                "char_sim": a[sctid]["char_sim"],
                "reasoning_a": a[sctid]["reasoning"],
                "reasoning_b": b[sctid]["reasoning"],
            })
    return consensus


def format_errors(errors: list[dict]) -> str:
    lines = []
    for i, e in enumerate(errors, 1):
        lines.append(
            f"### Error {i}\n"
            f"- English: {e['english']}\n"
            f"- Reference (KR extension): {e['reference']}\n"
            f"- Candidate (wrong): {e['translation']}\n"
            f"- Judge A reasoning: {e['reasoning_a']}\n"
            f"- Judge B reasoning: {e['reasoning_b']}\n"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--judge-a",
        type=Path,
        default=Path("data/evals/korean/judge_gemma4-26b.csv"),
    )
    parser.add_argument(
        "--judge-b",
        type=Path,
        default=Path("data/evals/korean/judge_qwen35b.csv"),
    )
    parser.add_argument(
        "--style-guide",
        type=Path,
        default=Path("style_guide/style_guide_ko.md"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("style_guide/proposed_rules_v2.md"),
    )
    parser.add_argument("--model", type=str, default="gemma4-26b")
    parser.add_argument("--label", type=str, default="WRONG")
    args = parser.parse_args()

    # Load config
    with (ROOT_DIR / "configs" / "models.json").open() as f:
        cfg = json.load(f)
    model_cfg = cfg["models"][args.model]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]

    # Find consensus errors
    errors = find_consensus_errors(args.judge_a, args.judge_b, args.label)
    log.info("Found %d consensus-%s rows", len(errors), args.label)
    if not errors:
        raise SystemExit("No consensus errors found.")

    # Load style guide
    style_guide = args.style_guide.read_text(encoding="utf-8")

    # Build prompt
    user = USER_TEMPLATE.format(
        style_guide=style_guide,
        errors=format_errors(errors),
    )

    log.info(
        "Prompting %s: system=%d chars, user=%d chars (includes %d errors + %d-char style guide)",
        args.model, len(SYSTEM_PROMPT), len(user), len(errors), len(style_guide),
    )

    # Wait for server
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{base_url}/v1/models", timeout=5)
            if r.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(5)

    # Call LLM
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "max_tokens": 4096,
        "temperature": 0.2,
    }
    log.info("Calling LLM...")
    t0 = time.monotonic()
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=300)
    r.raise_for_status()
    elapsed = time.monotonic() - t0
    msg = r.json()["choices"][0]["message"]
    content = msg.get("content") or msg.get("reasoning") or ""
    usage = r.json().get("usage", {})
    log.info(
        "LLM responded in %.1fs: prompt=%d completion=%d tokens",
        elapsed, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
    )

    # Save with frontmatter
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        f"<!--\n"
        f"Auto-generated style-guide additions.\n"
        f"Source: {len(errors)} consensus-{args.label} errors from\n"
        f"  {args.judge_a.name} and {args.judge_b.name}\n"
        f"Proposed by: {args.model} ({model_id})\n"
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"-->\n\n"
    )
    args.output.write_text(frontmatter + content.strip() + "\n", encoding="utf-8")
    log.info("Wrote %s (%d chars)", args.output, len(content))


if __name__ == "__main__":
    main()
