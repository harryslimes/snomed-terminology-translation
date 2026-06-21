# Qwen 3.6 35B-A3B vs Gemma 4 26B-A4B — model ablation (2026-04-20)

## Question

Does swapping the base LLM from gemma4-26b to a newer / larger MoE
(Qwen 3.6 35B-A3B, AWQ-4bit) improve translation quality on the 774
KR-covered imaging concepts?

## Setup

Both arms use the identical pipeline — `style_guide_ko_v3.md` + BGE-M3
exemplar lookup, same decoding params (temperature 0, max_tokens 128,
`enable_thinking: false` for Qwen). The only variable is the LLM.

| Parameter | gemma4-26b | qwen36b |
|---|---|---|
| Total params | 26B | 35B |
| Active params (MoE) | 4B | 3B |
| Quantisation | AWQ-4bit | AWQ-4bit |
| `max_model_len` | 16,384 | 16,384 (bumped from 8,192 — v3 prompt is ~6k tokens) |
| Weights on disk | ~13 GB | ~22 GB |
| Throughput on DGX Spark GB10 | ~14 req/s | ~2.7 req/s |

Qwen needed the `max_model_len` bump — default 8,192 rejected 288/774
prompts with 400 Bad Request once the v3 style guide + exemplar table
exceeded the ceiling.

## Results

### Exact-match against KR reference

| Model | Exact matches | Rate |
|---|---|---|
| gemma4-26b (baseline) | 599 / 774 | **77.4%** |
| qwen36b | 556 / 774 | 71.8% |

### Pairwise LLM judge (gemma4-26b judge, two-pass order-swapped)

| identical | judged | gemma wins | qwen wins | tie | inconsistent |
|---|---|---|---|---|---|
| 583 | 191 | **119 (64.3%)** | 64 (34.6%) | 2 | 6 |

Low inconsistent rate (~3% of judged) indicates high-confidence verdicts.

gemma4 wins ~2:1 on pairwise judge and by 5.6 pp on exact-match.

_Judge caveat: the judge is gemma4-26b itself. Cross-model self-bias is a
known effect, but the margin is large enough that it wouldn't flip with a
different judge — the exact-match gap is independent and in the same
direction._

## Where the two models diverge

### Qwen systematically prefers Sino-Korean over the KR-preferred form

Out of 94 concepts where gemma was exact and qwen wasn't, a large fraction
are body-site rendering differences where qwen chose the more "formal"
Sino-Korean term and the KR reference chose pure Korean:

| Concept | KR reference | gemma (matches) | qwen (misses) |
|---|---|---|---|
| MRI of forearm | 아래팔 (pure) | 아래팔 | 전완 (Sino) |
| MRI of right scapula | 어깨뼈 (pure) | 어깨뼈 | 견갑골 (Sino) |
| MRI of right calf | 장딴지 (pure) | 장딴지 | 종아리 (pure alt) |
| MRI of mandible | 아래턱뼈 (pure) | 아래턱뼈 | 하악 (Sino) |

Qwen also tended to drop `의` particle, contract multi-site phrases
(흉추 및 요추 → 흉요추), and omit `혈관` from angiography compounds
(혈관 조영 → 조영).

### Qwen does win sometimes

51 concepts where qwen was exact and gemma wasn't. Interestingly, many of
these are the **opposite** pattern — gemma over-applied pure Korean,
qwen stuck to Sino-Korean which matched KR:

| Concept | KR reference | qwen (matches) | gemma (misses) |
|---|---|---|---|
| MRI of hip | 고관절 (Sino) | 고관절 | 엉덩관절 (pure) |
| Ultrasound of rib | 갈비뼈 (pure) | 갈비뼈 | 늑골 (Sino) |
| Internal carotid angiography | 내경동맥 조영술 | 내경동맥 조영술 | 내경동맥 혈관 조영술 |

Neither model has a model-internal policy that matches the KR release
consistently, because the KR release is itself inconsistent across
concepts (see [procedure_inconsistencies_2026-04-20.md](procedure_inconsistencies_2026-04-20.md)).

## Interpretation

**Qwen is more opinionated; gemma leverages exemplars more.** The task's
ground truth is "whatever KHIS translator wrote" — which varies per
concept. A model that follows the exemplar table closely (gemma) matches
reference more often than a model that applies a consistent internal
policy regardless of exemplars (qwen).

This is consistent with our earlier findings: on KR-covered content, the
signal is in the exemplars, not in the prompt. Qwen's apparent tendency to
override exemplars with its own terminology preferences costs it the match
rate.

## Practical implications

- **For production translation on KR-covered content: gemma4-26b stays.**
  It wins on exact-match, on pairwise judge, and on throughput (~5× faster
  under identical load).
- **Qwen3.6 might still be worth testing on the long tail** where
  exemplars are weak — a more opinionated model may help where the
  exemplar table offers nothing. Same gating question we noted for
  dictionaries. Not tested yet.
- **Throughput matters**. 2.7 req/s vs 14 req/s means gemma completes the
  774-concept set in 56s, qwen takes 286s. For a full run over the ~55k
  untranslated SNOMED procedures, that's ~1 hour (gemma) vs ~6 hours
  (qwen) per pass. Not a blocker, but a real cost factor.
- **Qwen's narrower context default (8192) costs an additional
  configuration step.** Worth noting if we try other Qwen3+ variants.

## Files

- Translations: `data/evals/korean/imaging_ablation/translations_baseline_qwen36b.csv`.
- Judgements (gemma judge): `data/evals/korean/imaging_ablation/judgements_gemma4_vs_qwen36b.csv`.
- Judgements (qwen judge): `data/evals/korean/imaging_ablation/judgements_gemma4_vs_qwen36b_qwen_judge.csv`.
- Docker / config entries added for `qwen36b` model key.

## Addendum — thinking mode and judge cross-check

Two follow-up checks were run to stress-test the conclusion.

### Is Qwen secretly doing reasoning?

No. Direct probe:

```
enable_thinking=False: 14.41s content='뇌 컴퓨터 단층 촬영' reasoning=''
enable_thinking=True:   0.54s content=None            reasoning="Here's a thinking process:"
```

Thinking is disabled in the actual translation run. The Qwen response has
`reasoning=''` and a populated `content`. The slowness is the model itself
on this hardware — a single 7,906-token prefill (v3 style guide +
exemplars) takes 14s. vLLM logs during startup also warn that the GB10's
CUDA capability 12.1 exceeds PyTorch's supported max of 12.0, which
probably forces unoptimised kernel paths for some operations. This likely
explains the throughput gap (2.7 req/s Qwen vs 14 req/s Gemma).

### Does the judge choice change the verdict?

No. Running the pairwise judge with `--model qwen36b` (Qwen judging itself
vs Gemma):

| Judge | gemma wins | qwen wins | tie | inconsistent |
|---|---|---|---|---|
| gemma4-26b | **119 (64.3%)** | 64 (34.6%) | 2 | 6 |
| qwen36b | **99 (61.5%)** | 58 (36.0%) | 4 | 30 |

The direction holds — Qwen itself judges Gemma's translations as closer to
the KR reference ~5:3. This rules out judge self-bias.

Note that Qwen is a noisier judge (30 inconsistent vs 6 across the
order-swap), consistent with its higher variance as a generator.

### Revised bottom line

Gemma wins on exact-match (77.4% vs 71.8%) and wins on pairwise judge
regardless of which model judges. Not a bias artefact, not a thinking-mode
artefact — Qwen 3.6 35B-A3B just produces translations further from the
KR reference on this corpus, at 5× lower throughput.
