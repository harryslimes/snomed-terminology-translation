# Qwen 3.5 122B-A10B vs Gemma 4 26B-A4B — model ablation (2026-04-21)

## Question

Does going even bigger — Qwen 3.5 122B-A10B (GPTQ-Int4, 10B active) — beat
Gemma 4 26B-A4B (AWQ-4bit, 4B active) on the 774 KR-covered imaging
concepts?

## Setup

Identical pipeline on both arms: `style_guide_ko_v3.md` + BGE-M3 exemplar
lookup, same decoding params (temperature 0, max_tokens 128,
`enable_thinking: false`).

| Parameter | gemma4-26b | qwen36b | **qwen122b** |
|---|---|---|---|
| Total params | 26B | 35B | **122B** |
| Active params (MoE) | 4B | 3B | **10B** |
| Quantisation | AWQ-4bit | AWQ-4bit | **GPTQ-Int4** |
| `max_model_len` | 16,384 | 16,384 | 16,384 (bumped from 8,192) |
| Weights on disk | ~13 GB | ~22 GB | ~60 GB |
| Effective throughput (c=16) | ~14 req/s | ~2.7 req/s | **~0.5 req/s** |
| Full 774 run wall-time | ~56s | ~286s | ~1,220s |

Qwen122b needed the same `max_model_len` bump as qwen36b (8,192 rejects v3
style-guide + exemplar prompts at ~7,900 tokens).

## Results

### Exact-match against KR reference

| Model | Exact matches | Rate |
|---|---|---|
| gemma4-26b (baseline) | 599 / 774 | **77.4%** |
| qwen36b | 556 / 774 | 71.8% |
| **qwen122b** | **556 / 774** | **71.8%** |

qwen122b matched **exactly the same count** as qwen36b. 584/774 (75%) of
qwen122b's translations are textually identical to qwen36b's — doubling
the active params (3B → 10B) and nearly quadrupling total params
(35B → 122B) changed ~190 outputs but netted zero improvement on
exact-match.

### Pairwise LLM judge (gemma4-26b judge, two-pass order-swapped)

| identical | judged | gemma wins | qwen122b wins | tie | inconsistent |
|---|---|---|---|---|---|
| 573 | 201 | **125 (64.1%)** | 67 (34.4%) | 3 | 6 |

Practically identical to the gemma-vs-qwen36b result (64.3% / 34.6%). The
two Qwen models are interchangeable from the reference's perspective.

## The five-model picture (combining all ablations)

| Model | Active | Exact | Gemma-judge A-win vs gemma |
|---|---|---|---|
| gemma4-26b | 4B | **77.4%** | — (reference) |
| qwen36b | 3B | 71.8% | loses 64% / 35% |
| qwen122b | 10B | 71.8% | loses 64% / 34% |

On this corpus, **raw parameter count doesn't move the metric**. Qwen36b
and qwen122b produce translations of essentially equivalent quality
despite the 3.5× capacity gap.

## Why more Qwen capacity doesn't help

Same diagnosis as qwen36b vs gemma4: Qwen models apply a more consistent
**Sino-Korean** policy (전완 / 견갑골 / 하악) while the KR reference mixes
pure and Sino. A bigger Qwen reinforces its own priors more confidently,
not less. The quality ceiling is set by the mismatch between any given
model's internal policy and the KR release's per-concept inconsistency,
and the exemplar table is the only mechanism that pushes the model toward
the reference's actual choices. Both Qwen sizes are insufficiently
willing to override their policy in favour of the exemplar pattern.

This is the **fourth consecutive ablation** in this session showing the
same pattern: on KR-covered content the quality ceiling is determined by
exemplar fidelity, not by prompt rules, dictionaries, or model size.

## Throughput

For future production use, the numbers matter:

- gemma4-26b: **~56 seconds** for 774 concepts.
- qwen36b: ~4.8 minutes (5× slower).
- qwen122b: **~20 minutes** (22× slower).

Extrapolating to the full ~55k untranslated SNOMED procedures:
- gemma4-26b: ~1 hour.
- qwen122b: ~24 hours.

GB10 CUDA capability 12.1 > PyTorch's supported 12.0 still likely the
root cause of the Qwen slowness, but gemma's compressed-tensors AWQ
kernel evidently survives the fallback while qwen's GPTQ-Int4 path does
not. Independently: qwen122b's 10B active is 2.5× gemma4's 4B, so some
slowdown was expected — but not 22×.

## Practical implications

- **Production pipeline stays on gemma4-26b**. Qwen122b offers no quality
  gain and costs 22× more wall-clock per translation.
- **Larger model is not the missing ingredient.** That closes one of the
  three remaining avenues I flagged after the v4 style-guide ablation
  ("a different / larger model might extract more from the same prompt").
  It doesn't. The other two avenues are still viable: (a) long-tail
  evaluation and (b) better exemplar retrieval.
- **Qwen remains interesting for the long tail** where the exemplar table
  is weakest — its stronger internal priors may do better than Gemma's
  exemplar-dependent behaviour on concepts with no close neighbours in
  the KR corpus. Worth gating on exemplar score when we get there.

## Files

- Translations: `data/evals/korean/imaging_ablation/translations_baseline_qwen122b.csv`.
- Judgements: `data/evals/korean/imaging_ablation/judgements_gemma4_vs_qwen122b.csv`.
- Config entry `qwen122b` already existed in [configs/models.json](../configs/models.json);
  `max_model_len` bumped to 16,384 for this run.
