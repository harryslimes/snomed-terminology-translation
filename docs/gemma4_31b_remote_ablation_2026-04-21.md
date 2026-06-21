# Gemma 4 31B (remote, NVFP4-turbo) — model ablation (2026-04-21)

## Question

Does the remote `gemma-4-31B-it-NVFP4-turbo` (LilaRest quantisation) served
from the user's LAN vLLM instance beat the local `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit`
on the 774 KR-covered imaging concepts?

## Setup

Remote endpoint `http://192.168.1.76:18000`, vLLM serving
`LilaRest/gemma-4-31B-it-NVFP4-turbo` exposed as model id `gemma-4-31b`,
`--max-model-len 8192`, `--gpu-memory-utilization 0.92` on the user's
host.

| Parameter | gemma4-26b (local) | gemma4-31b (remote) |
|---|---|---|
| Total params | 26B | 31B |
| Active params (MoE) | 4B | dense (not MoE) |
| Quantisation | AWQ-4bit | NVFP4-turbo |
| `max_model_len` | 16,384 | 8,192 |
| Style guide | v3 (full, 7,706 tokens) | **v3 abbreviated (4,730 tokens)** |
| Effective throughput (c=32) | ~15 req/s | **~38 req/s** |
| Full 774 run wall-time | ~56s | **~20s** |

The 8,192 context window forced a style-guide trim for the remote arm.
The abbreviation strips: inter-hierarchy stubs (finding / observable /
organism / pharmaceutical / qualifier / situation / substance),
provenance and methodology note, open-questions block, recommended-sources
list. All normative rules, tables, and worked examples are preserved.
Net: 4,730 tokens (−39% from full v3).

To separate the style-guide-trim effect from the model-change effect we
ran a three-way comparison:

- **Arm 26b-full**: gemma4-26b + full v3 (existing baseline).
- **Arm 26b-abbr**: gemma4-26b + v3-abbreviated (control for style trim).
- **Arm 31b-abbr**: gemma4-31b + v3-abbreviated (the remote arm).

## Results

### Exact-match against KR reference

| Arm | Exact | Rate |
|---|---|---|
| 26b-full | 599 / 774 | **77.4%** |
| 26b-abbr | 583 / 774 | 75.3% |
| 31b-abbr | 574 / 774 | 74.2% |

Decomposition:

- **Style-guide trim costs ~2 pp** (26b-full → 26b-abbr).
- **Bigger 31b model costs another ~1 pp** at the same prompt
  (26b-abbr → 31b-abbr).

### Pairwise LLM judge (gemma4-26b judge, two-pass order-swapped)

**Same-prompt comparison (isolates model effect):**

| | identical | judged | 26b-abbr wins | 31b wins | tie | inconsistent |
|---|---|---|---|---|---|---|
| 26b-abbr vs 31b-abbr | 639 | 135 | **68 (53.5%)** | 57 (44.9%) | 2 | 8 |

**End-to-end comparison (matches the user's question):**

| | identical | judged | 26b-full wins | 31b wins | tie | inconsistent |
|---|---|---|---|---|---|---|
| 26b-full vs 31b-abbr | 621 | 153 | **87 (59.2%)** | 59 (40.1%) | 1 | 6 |

Both comparisons favour the local gemma4-26b setup. Same-prompt margin is
narrow (53% / 45%) — the 26b model is only slightly preferred over the
31b model when both get the same trimmed prompt. The end-to-end margin
(59% / 40%) compounds that with the ~2 pp advantage of the full style
guide.

## Model landscape after five ablations

| Model | Params (active) | Exact | Throughput (c=16–32) |
|---|---|---|---|
| gemma4-26b (local, full v3) | 26B MoE (4B) | **77.4%** | ~15 req/s |
| gemma4-26b (local, v3-abbr) | 26B MoE (4B) | 75.3% | ~15 req/s |
| gemma4-31b (remote, v3-abbr) | 31B dense | 74.2% | **~38 req/s** |
| qwen36b (local) | 35B MoE (3B) | 71.8% | ~2.7 req/s |
| qwen122b (local) | 122B MoE (10B) | 71.8% | ~0.5 req/s |

## Interpretation

The remote gemma4-31b is **the fastest model tested** — ~38 req/s
(concurrency 32), nearly 3× the local 26b's throughput. The NVFP4-turbo
quantisation on the user's GPU is plainly more efficient than anything we
have on the DGX Spark.

Quality is **very close to the local 26b** when both use the same prompt,
with a narrow 53/45 preference for the 26b. The style-guide trim (forced
by 8k context) accounts for the bulk of the exact-match gap — bumping
`--max-model-len` to 16,384 on the remote server would let us run the
full v3 style guide and likely close most of the 3 pp exact-match gap,
while keeping the 3× throughput advantage.

The Gemma family continues to outperform Qwen in Korean SNOMED procedure
translation. Bigger Qwen (35B → 122B) gave zero improvement; 31b vs 26b
within the Gemma family gave ~1 pp regression on exact match but within
noise on judge — consistent with the broader pattern that this task's
quality ceiling is set by exemplar fidelity, not model size.

## Practical implications

- **If you can bump `--max-model-len` on the remote server to 16384**,
  gemma4-31b becomes strictly more useful: same-prompt parity with the
  local 26b but 3× the throughput. Single-line docker compose edit on
  your host.
- **Right now** gemma4-31b is a credible production option for
  batch-scale translation — its 38 req/s throughput means the eventual
  long-tail run over ~55k untranslated SNOMED procedures takes
  **~24 minutes** instead of ~60 minutes on the local 26b. The 3 pp
  exact-match regression is a reasonable tradeoff for 2.5× faster.
- **For quality-critical spot work**, stick with local 26b + full v3.
- **For scale work** (the actual translation project goal), pick
  gemma4-31b-remote once context is bumped.
- **Network latency from this environment to the remote server is fine**
  — single-request latencies are dominated by prefill time on the GPU,
  not network RTT. LAN connectivity has not been a bottleneck.

## Files

- Translations: `data/evals/korean/imaging_ablation/translations_baseline_gemma4-31b.csv`,
  `data/evals/korean/imaging_ablation/translations_baseline_gemma4-26b_abbr.csv`.
- Judgements: `data/evals/korean/imaging_ablation/judgements_gemma26b_abbr_vs_gemma31b.csv`,
  `data/evals/korean/imaging_ablation/judgements_gemma26b_full_vs_gemma31b.csv`.
- Style guide: `style_guide/style_guide_ko_v3_abbr.md` (new — trimmed
  v3, retains all normative content).
- Config entry: `gemma4-31b-remote` in [configs/models.json](../configs/models.json).
- Permission rule: `.claude/settings.json` allows curl to the LAN IPs.
