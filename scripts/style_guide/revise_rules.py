#!/usr/bin/env python3
"""Revise proposed style-guide rules after a regression analysis.

Feeds the rule-proposing LLM:
  1. The current proposed rules (which caused regressions).
  2. Target errors the rules should fix (the original consensus-WRONG set).
  3. Regressions: rows where v1 was exact-match but v2 broke them.

Asks the LLM to revise the rules to keep the gains while preventing the
regressions. Explicitly instructs it to make rules more precise/conditional
rather than deleting them — the original failures still need addressing.

Writes revised rules to style_guide/proposed_rules_<tag>.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("revise_rules")


SYSTEM_PROMPT = """\
You are a Korean medical terminology style-guide author for SNOMED CT translation. \
You previously proposed a set of rule additions, and those rules were deployed. \
They fixed SOME errors but ALSO caused new failures — cases that were previously \
correct but are now wrong because your rules over-generalised.

Your job now is to REVISE the rules so they still fix the target errors but do NOT \
cause the observed regressions.

You will be shown:
1. The existing style guide (for context).
2. Your current proposed rules (which caused the regressions).
3. A set of TARGET errors the rules should still fix.
4. A set of REGRESSIONS the rules caused. Each regression shows a row that was \
   previously correct (v1 output matched the reference), but your rules caused v2 \
   to produce a different and wrong output.

CRITICAL GUIDANCE:
- Analyse the regressions for PATTERNS. If multiple regressions stem from the same \
  rule over-firing, that rule needs to be made more conditional or removed.
- Prefer MAKING RULES MORE PRECISE over deleting them. A good revision adds \
  qualifying conditions: "prefer X, EXCEPT when the reference or lookup examples \
  use Y".
- The reference translations in the KR extension are INCONSISTENT. Some concepts \
  prefer native Korean, some prefer Sino-Korean. A blanket "always prefer X" rule \
  will cause regressions. Instead, defer to the lookup examples the model is shown \
  at translation time — those are the best signal for the correct register.
- Do NOT introduce rules that name specific SCTIDs or reference individual examples.
- Do NOT duplicate existing style-guide content.
- Preserve rules that had no regressions — if a rule cleanly fixed errors without \
  collateral damage, keep it unchanged.

Output format: complete markdown, replacing your previous proposed rules. Start \
with a single top-level heading "## Proposed additions (from error analysis, revised)". \
Use sub-headings for each rule. Each rule: (a) the rule itself in one or two \
sentences, (b) a rationale based on the PATTERN observed, (c) if a previous rule \
was narrowed or removed, briefly note why in the rationale. Use vocabulary tables \
where useful.

Return ONLY the markdown — no preamble."""


USER_TEMPLATE = """\
# Existing style guide

```markdown
{style_guide}
```

# Your current proposed rules (caused regressions)

```markdown
{current_rules}
```

# Target errors (the rules should STILL fix these)

{target_errors}

# Regressions (your rules caused these to break — previously correct)

{regressions}

Now revise the proposed rules. Return the full revised markdown."""


def format_cases(cases: list[dict], label: str = "Error") -> str:
    lines = []
    for i, c in enumerate(cases, 1):
        lines.append(
            f"### {label} {i}\n"
            f"- English: {c['english']}\n"
            f"- Reference (KR extension): {c['reference']}\n"
            f"- Candidate: {c['candidate']}\n"
        )
        if c.get("v1"):
            lines.append(f"- V1 output (was correct): {c['v1']}\n")
        if c.get("v2"):
            lines.append(f"- V2 output (now wrong): {c['v2']}\n")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--style-guide",
        type=Path,
        default=Path("style_guide/style_guide_ko.md"),
    )
    parser.add_argument(
        "--current-rules",
        type=Path,
        default=Path("style_guide/proposed_rules_v2.md"),
    )
    parser.add_argument(
        "--v1-translations",
        type=Path,
        default=Path("data/evals/korean/translations_gemma4-26b_t0_lookup.csv"),
    )
    parser.add_argument(
        "--v2-translations",
        type=Path,
        default=Path("data/evals/korean/translations_gemma4-26b_v2_t0_lookup.csv"),
    )
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
        "--output",
        type=Path,
        default=Path("style_guide/proposed_rules_v3.md"),
    )
    parser.add_argument("--model", type=str, default="gemma4-26b")
    parser.add_argument("--max-regressions", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)

    # Load config
    with (ROOT_DIR / "configs" / "models.json").open() as f:
        cfg = json.load(f)
    model_cfg = cfg["models"][args.model]
    base_url = os.getenv("VLLM_BASE_URL", f"http://localhost:{model_cfg['port']}")
    model_id = model_cfg["hf_id"]

    def norm(s):
        return "".join(s.split())

    # Target errors: consensus-WRONG under both judges (original 30)
    a = {r["sctid"]: r for r in csv.DictReader(args.judge_a.open(encoding="utf-8"))}
    b = {r["sctid"]: r for r in csv.DictReader(args.judge_b.open(encoding="utf-8"))}
    target_ids = [s for s in a if s in b and a[s]["label"] == "WRONG" and b[s]["label"] == "WRONG"]
    target_cases = [
        {
            "english": a[s]["english"],
            "reference": a[s]["reference"],
            "candidate": a[s]["translation"],
        }
        for s in target_ids
    ]
    log.info("Target errors: %d", len(target_cases))

    # Regressions: v1 was exact match, v2 is not
    v1 = {r["sctid"]: r for r in csv.DictReader(args.v1_translations.open(encoding="utf-8"))}
    v2 = {r["sctid"]: r for r in csv.DictReader(args.v2_translations.open(encoding="utf-8"))}
    regression_ids = [
        s for s in v1
        if norm(v1[s]["translation"]) == norm(v1[s]["ko_reference"])
        and s in v2
        and norm(v2[s]["translation"]) != norm(v2[s]["ko_reference"])
    ]
    log.info("Total regressions: %d (sampling %d)", len(regression_ids), args.max_regressions)

    if len(regression_ids) > args.max_regressions:
        regression_ids = random.sample(regression_ids, args.max_regressions)

    regression_cases = [
        {
            "english": v1[s]["preferred_term"],
            "reference": v1[s]["ko_reference"],
            "candidate": v2[s]["translation"],
            "v1": v1[s]["translation"],
            "v2": v2[s]["translation"],
        }
        for s in regression_ids
    ]

    # Load guide + current rules
    style_guide = args.style_guide.read_text(encoding="utf-8")
    current_rules = args.current_rules.read_text(encoding="utf-8")

    user = USER_TEMPLATE.format(
        style_guide=style_guide,
        current_rules=current_rules,
        target_errors=format_cases(target_cases, "Target error"),
        regressions=format_cases(regression_cases, "Regression"),
    )

    log.info(
        "Prompt sizes: system=%d user=%d (style_guide=%d, current_rules=%d, targets=%d, regressions=%d)",
        len(SYSTEM_PROMPT), len(user),
        len(style_guide), len(current_rules),
        len(target_cases), len(regression_cases),
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

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "max_tokens": 3500,
        "temperature": 0.2,
    }
    log.info("Calling %s...", args.model)
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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        f"<!--\n"
        f"Auto-generated style-guide additions, revised after regression analysis.\n"
        f"Inputs: {len(target_cases)} target errors, {len(regression_cases)} regressions\n"
        f"  (sampled from {len(regression_ids)} regressions vs v1)\n"
        f"Proposed by: {args.model} ({model_id})\n"
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"-->\n\n"
    )
    args.output.write_text(frontmatter + content.strip() + "\n", encoding="utf-8")
    log.info("Wrote %s (%d chars)", args.output, len(content))


if __name__ == "__main__":
    main()
