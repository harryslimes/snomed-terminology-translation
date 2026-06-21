# Claude Sonnet 4.6 as a cross-check judge (2026-04-22)

## Motivation

Our primary judge (`gemma4-26b` local) is the same family as the
generator model (`gemma-4-26B-A4B-it-NVFP4` remote). Possible self-family
bias. Worth re-judging with a very different model — Claude Sonnet 4.6 —
as a cross-check.

## Setup

- [scripts/evaluation/judge_korean_sonnet.py](../scripts/evaluation/judge_korean_sonnet.py)
- Uses `claude-agent-sdk` with local Claude Code OAuth credentials
  (no `ANTHROPIC_API_KEY` required).
- Stripped overhead: `tools=[]` + `allowed_tools=[]` strips the Claude Code
  tool catalog from the prompt (cuts cache-creation tokens ~6×). After the
  first call warms the prompt cache, subsequent calls cost ~$0.01 each.
- Same `ACCEPTABLE / PARTIAL / WRONG` labels, same system/user prompt as
  `judge_korean_translations.py`, so labels are directly comparable.
- Concurrency 8 (retries on transient CLI subprocess errors).

Each arm: 774 imaging concepts, ~10 min wall-time, ~$7-8 in API cost.

## Results

### Leaky baseline — self-hits present in retrieval pool

| Judge | ACCEPTABLE | PARTIAL | WRONG |
|---|---|---|---|
| gemma4-26b | **754 (97.4%)** | 18 (2.3%) | 2 (0.3%) |
| **Sonnet 4.6** | **730 (94.3%)** | 42 (5.4%) | 2 (0.3%) |

Agreement: **95.5%** (739/774). The two disagree mostly on the
PARTIAL/ACCEPTABLE boundary — Sonnet calls 29 things PARTIAL that gemma
rated ACCEPTABLE. Hard-failure (WRONG) agreement is near-perfect.

### Self-excluded baseline — realistic long-tail conditions

| Judge | ACCEPTABLE | PARTIAL | WRONG |
|---|---|---|---|
| gemma4-26b | **685 (88.5%)** | 61 (7.9%) | 28 (3.6%) |
| **Sonnet 4.6** | **594 (76.7%)** | 148 (19.1%) | 32 (4.1%) |

Agreement: **84.8%** (656/774). Big disagreement on the ACCEPTABLE/PARTIAL
boundary: of the 685 gemma marked ACCEPTABLE, Sonnet reclassifies 94
(14%) as PARTIAL and 5 as WRONG. Gemma was being generous on close-but-
not-right translations.

Confusion matrix (self arm):

```
gemma \ sonnet    ACCEPTABLE    PARTIAL     WRONG
ACCEPTABLE              586         94         5
PARTIAL                   6         49         6
WRONG                     2          5        21
```

- WRONG diagonal: 21/28 gemma-WRONGs confirmed by Sonnet. Sonnet finds
  another 11 cases of genuine wrongness in what gemma called
  ACCEPTABLE/PARTIAL.
- PARTIAL expansion: gemma 61 PARTIAL → Sonnet 148 PARTIAL. Much of
  that +87 comes from gemma-ACCEPTABLE being reclassified.

## Drop leaky → self, by judge

| Judge | Leaky ACCEPTABLE | Self ACCEPTABLE | Drop |
|---|---|---|---|
| gemma4-26b | 97.4% | 88.5% | **−8.9 pp** |
| Sonnet 4.6 | 94.3% | 76.7% | **−17.6 pp** |

Sonnet sees **twice the drop** that gemma did when the cache leakage is
removed. The "real" long-tail quality degradation is larger than the
gemma judge suggested.

## Revised headline numbers

| Metric | Leaky | Self (realistic long-tail) |
|---|---|---|
| Strict exact | 78.0% | 44.1% |
| Lenient (preferred ∪ acceptable synonym) | 85.9% | 49.7% |
| gemma-judge ACCEPTABLE | 97.4% | 88.5% |
| **Sonnet-judge ACCEPTABLE** | **94.3%** | **76.7%** |

Between the two judges, I trust Sonnet more:

- It's a stronger, different-family model (no self-family bias).
- Higher disagreement on the borderline cases suggests it's *detecting*
  the variance that gemma is smoothing over.
- Its WRONG set on the self arm (32 concepts) has high overlap with
  gemma's (21/28 agreement), so it's not hallucinating strictness —
  both judges agree on the clearly-wrong ones.

### What this means for the project state

- **Real long-tail acceptability is ~77%, not 88%.** That's a ~23% error
  rate on the long tail — meaningful but not catastrophic.
- About **19% of the long-tail output is PARTIAL** — core concept right
  but with a meaningful defect (wrong suffix, missing modifier, etc.).
  This is where most of the improvement headroom lives.
- **4% genuinely WRONG** — needs careful review but is a small enough
  set to spot-check manually.
- The 23% gap from Sonnet-ACCEPTABLE to 100% is the real quality
  deficit, not the 56% gap from strict-exact-match to 100%.

## Cost efficiency

Total cost for both 774-row arms: **$15.57**.

Breakdown:

- First call per arm: cache creation ~$0.01.
- Subsequent cached calls: ~$0.01 each.
- Per-arm total: ~$7.50 for 774 rows.

At this cost, Sonnet judging can be run on every major ablation batch
(~$15–30 per full cycle). Budget-conscious but not prohibitive.

## Practical recommendation

For the project's evaluation scorecard going forward:

| Tier | Tool | Purpose | Cost |
|---|---|---|---|
| 1 — Strict / lenient exact-match | stdlib | Cheap regression check | free |
| 2 — gemma4 local judge | existing script | Free LLM sanity check | free |
| 3 — **Sonnet judge** | this script | Trusted quality signal | ~$15 / 1.5k rows |

Sonnet becomes the "ground truth" tier below an SME review. Gemma
remains useful as a free first-pass signal for experiments that aren't
budget-sensitive enough to justify Sonnet on every run.

## Files

- Judge script: [scripts/evaluation/judge_korean_sonnet.py](../scripts/evaluation/judge_korean_sonnet.py)
- Judgements:
  - `data/evals/korean/synthetic_long_tail/judge_sonnet_imaging_none.csv`
  - `data/evals/korean/synthetic_long_tail/judge_sonnet_imaging_self.csv`
