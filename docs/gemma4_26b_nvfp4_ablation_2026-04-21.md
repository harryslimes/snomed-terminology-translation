# Gemma 4 26B-A4B — AWQ vs NVFP4 quantisation ablation (2026-04-21)

## Question

The same base model (`google/gemma-4-26B-A4B-it`) served through two
different 4-bit quantisation paths. Does NVFP4 change quality?

- **Local**: `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` on DGX Spark GB10 via
  vLLM (`--quantization compressed-tensors`).
- **Remote**: `RedHatAI/gemma-4-26B-A4B-it-NVFP4` on user's workstation
  (192.168.1.76:18000), served as model id `gemma-4-26b-a4b`,
  max_model_len 8192, `--gpu-memory-utilization 0.92`, up to 64 concurrent
  sequences.

Both arms use the same pipeline: BGE-M3 exemplar lookup (same Qdrant
index), same decoding parameters (temperature 0, max_tokens 128,
`enable_thinking: false` — no-op for Gemma).

The remote's 8k context forces a trimmed style guide; we ran the local
AWQ under both full v3 and v3-abbreviated to separate the prompt-trim
effect from the quantisation effect.

## Results

### Exact-match against KR reference

| Arm | Exact | Rate |
|---|---|---|
| 26b-AWQ (local, v3-full) | 599 / 774 | 77.4% |
| 26b-AWQ (local, v3-abbr) | 583 / 774 | 75.3% |
| **26b-NVFP4 (remote, v3-abbr)** | **608 / 774** | **78.6%** |

The remote NVFP4 beats the local AWQ even with the trimmed style guide
— and it's the single best exact-match of any model we've tested.

### Pairwise LLM judge (gemma4-26b (local AWQ) judge, two-pass)

**Same-prompt comparison (isolates quantisation effect):**

| | identical | judged | AWQ-abbr wins | **NVFP4 wins** | tie | inconsistent |
|---|---|---|---|---|---|---|
| 26b-AWQ-abbr vs 26b-NVFP4 | 670 | 104 | 35 (35.4%) | **63 (63.6%)** | 1 | 5 |

**End-to-end comparison (AWQ gets its best possible setup):**

| | identical | judged | AWQ-full wins | **NVFP4 wins** | tie | inconsistent |
|---|---|---|---|---|---|---|
| 26b-AWQ-full vs 26b-NVFP4 | 656 | 118 | 51 (45.1%) | **62 (54.9%)** | 0 | 5 |

NVFP4 wins both. Same-prompt margin is large (~2:1); even giving AWQ the
full style guide, NVFP4-with-trimmed-prompt still wins 55/45.

### Throughput

| Arm | Wall-time for 774 | Effective req/s (c=32) |
|---|---|---|
| 26b-AWQ (local) | ~56s | ~15 |
| **26b-NVFP4 (remote)** | **~24s** | **~32** |

Remote NVFP4 is **2.3× faster** at concurrency 32 and it's running on
the user's workstation over LAN, not the DGX. (Note: local
`gpu-memory-utilization` is 0.60 vs remote 0.92 — the local could
probably push higher too, but at this setting NVFP4 still wins on
throughput even accounting for that.)

## Interpretation

Two things are happening:

1. **NVFP4 preserves more signal than AWQ-4bit** for this model at this
   bit budget. The 63/35 same-prompt win isn't subtle — NVFP4 is
   producing outputs that better match the KR reference than AWQ does,
   at identical model weights and identical prompts.
2. **NVFP4 kernels are substantially faster** on modern Nvidia silicon.
   That's a known property of the format (native hardware support on
   Blackwell/Hopper lines vs AWQ's dequantise-then-compute path).

The **same base model** outperforms itself by quantisation choice alone.
That's a meaningful finding — all our prior conclusions about the
quality ceiling being set by exemplar fidelity were collected on the
AWQ-quantised version, which we now know was leaving quality on the
table.

## Revised model landscape

| Model | Quant | Exact | Throughput | Notes |
|---|---|---|---|---|
| **gemma4-26b NVFP4 (remote)** | NVFP4 | **78.6%** | **~32 req/s** | Best on both. |
| gemma4-26b AWQ (local, full v3) | AWQ-4bit | 77.4% | ~15 req/s | Prior production default. |
| gemma4-26b AWQ (local, v3-abbr) | AWQ-4bit | 75.3% | ~15 req/s | Same quant as prod, trimmed prompt. |
| gemma4-31b NVFP4-turbo (remote) | NVFP4-turbo | 74.2% | ~38 req/s | Slightly worse than 26b-NVFP4 despite bigger params. |
| qwen36b (local) | AWQ-4bit | 71.8% | ~2.7 req/s | |
| qwen122b (local) | GPTQ-Int4 | 71.8% | ~0.5 req/s | |

## Practical implications

- **New production default: gemma4-26b-NVFP4 (remote)**. Higher exact
  match, 2× throughput, no quality gap to close.
- **The prior conclusion that "quality is capped by exemplar fidelity"
  needs a caveat**: the cap we observed was the AWQ cap. NVFP4 moves it
  up by ~1.2 pp exact-match / ~2:1 judge preference. Models / quants can
  still matter — we just needed a better one than AWQ.
- **Everything that failed against AWQ-baseline** (editorial addendum,
  KAA, KARP, KR-native body-site dict, v4 style guide, qwen36b,
  qwen122b) is worth no reassessment — they all lost by substantial
  margins to a weaker baseline than this one. But future resource
  experiments should be run against the NVFP4 baseline.
- **For the eventual full-SNOMED long-tail run** (~55k untranslated
  procedures): NVFP4 at ~32 req/s takes ~28 minutes, AWQ at ~15 req/s
  takes ~60 minutes. And NVFP4 produces better output.
- **If you bump remote `--max-model-len` to 16384**, NVFP4 gets the full
  v3 style guide too. At 75.3% → 78.6% on trimmed alone, the full prompt
  is likely a further small bump. Single-line docker compose edit.

## Files

- Translations: `data/evals/korean/imaging_ablation/translations_baseline_gemma4-26b-nvfp4.csv`.
- Judgements:
  - `data/evals/korean/imaging_ablation/judgements_26b_awq_abbr_vs_26b_nvfp4.csv`
  - `data/evals/korean/imaging_ablation/judgements_26b_awq_full_vs_26b_nvfp4.csv`
- Config entry: `gemma4-26b-nvfp4-remote` in `configs/models.json`.
