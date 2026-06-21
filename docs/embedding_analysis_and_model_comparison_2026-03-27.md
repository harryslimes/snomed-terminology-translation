# Embedding Analysis & Model Comparison Report — 2026-03-27

## Overview

This report documents a series of investigations into SNOMED CT English-to-Estonian translation quality using BGE-M3 multilingual embeddings, confidence calibration, and a head-to-head comparison of Qwen 3.5 35B vs 122B models across the full Estonian SNOMED extension (17,877 concepts).

All work was performed on an NVIDIA DGX Spark (GB10, 128GB unified memory).

---

## 1. Confidence Calibration (4 prompt variants)

**Goal:** Determine whether Qwen 35B can self-assess translation confidence, and which prompt style gives the most useful signal for routing low-confidence translations to RAG enrichment.

**Method:** Translated 500 stratified eval concepts with each of 4 prompt variants, each asking for a 1-5 confidence score alongside the translation. Scored translations against official Estonian SNOMED extension using composite metric (0.5 * chrF/100 + 0.3 * BGE-M3 cosine + 0.2 * exact match).

### Results

| Prompt | Pearson r | Conf 5 composite | Conf 5 count | Best routing cutoff |
|--------|-----------|------------------|--------------|---------------------|
| **original** | **0.372** | 0.657 | 227 | <=4 routes 55% to RAG |
| checklist | 0.301 | 0.620 | 252 | Collapsed to bimodal (1,2,5 only) |
| **premortem** | 0.314 | **0.863** | **36** | <=4 routes 93% to RAG |
| decompose | 0.182 | 0.589 | 291 | Poor discrimination |

### Key findings

- **Premortem** produces the tightest high-confidence group: when it says 5, it means it (0.863 composite, 80.6% exact match). But it's very harsh — only 36/500 get a 5.
- **Original** has the best overall correlation and cleanest confidence gradient.
- **Checklist** collapsed into a bimodal distribution — the YES/NO questions didn't create a useful gradient.
- **Decompose** (per-word certainty) had the worst correlation (0.182).

### Recommendation

Use **original prompt with cutoff <=4** for balanced routing (55% to RAG, kept translations average 0.657), or **premortem with cutoff <=2** for high-precision filtering (21% to RAG, those genuinely need help).

**Output files:**
- `data/evals/sample/500_confidence_original.csv`
- `data/evals/sample/500_confidence_checklist.csv`
- `data/evals/sample/500_confidence_premortem.csv`
- `data/evals/sample/500_confidence_decompose.csv`

---

## 2. Cross-lingual Embedding Analysis (EN-ET BGE-M3)

**Goal:** Understand how similar English SNOMED terms are to their official Estonian translations in BGE-M3 embedding space, and whether this can be used as a translation quality signal.

**Method:** Computed BGE-M3 dense embeddings for all 17,877 EN-ET concept pairs in the Estonian SNOMED extension. Measured cosine similarity and compared across hierarchies and Latin/native Estonian terms.

### Overall statistics

| Metric | Value |
|--------|-------|
| Concepts | 17,877 |
| Mean cosine | 0.746 |
| Median | 0.744 |
| Std | 0.192 |

### Latin vs Native Estonian

| Category | Count | Mean cosine | Median |
|----------|-------|-------------|--------|
| Latin/Greek | 6,504 (36.4%) | 0.937 | 1.000 |
| Native Estonian | 11,373 | 0.637 | 0.651 |

The Latin/Greek terms (mostly organism binomials) inflate the overall mean significantly. The native Estonian distribution is centred at ~0.65.

### Per-hierarchy baselines (native Estonian terms only)

| Hierarchy | Count | Mean | Median | Latin % |
|-----------|-------|------|--------|---------|
| body structure | 1,376 | 0.516 | 0.513 | 1.0% |
| specimen | 149 | 0.543 | 0.555 | 0.0% |
| substance | 401 | 0.532 | 0.522 | 10.5% |
| physical object | 216 | 0.560 | 0.577 | 7.7% |
| person | 147 | 0.576 | 0.574 | 0.0% |
| observable entity | 154 | 0.636 | 0.671 | 1.3% |
| finding | 442 | 0.644 | 0.667 | 4.3% |
| disorder | 3,380 | 0.650 | 0.677 | 11.3% |
| morphologic abnormality | 1,493 | 0.662 | 0.712 | 23.7% |
| procedure | 2,806 | 0.684 | 0.700 | 5.2% |
| organism | 505 | 0.697 | — | 91.4% |

### Cross-lingual retrieval accuracy (500-concept eval subset)

| Metric | Dense cosine | ColBERT MaxSim |
|--------|-------------|----------------|
| Recall@1 | 60.8% | 61.4% |
| Recall@5 | 73.6% | 73.2% |
| Recall@10 | 76.6% | 76.6% |

Dense and ColBERT produce nearly identical results (r=0.967). Sparse (lexical) similarity is near zero for cross-lingual pairs — no shared tokens between English and Estonian.

### Embedding similarity as a translation quality signal

Tested whether the cosine gap (EN-Translation cosine minus EN-Reference cosine) can detect bad translations:

| Signal | Correlation with composite score |
|--------|--------------------------------|
| Translation-Reference cosine | 0.856 (requires answer) |
| Model confidence (original) | 0.372 |
| EN-Reference cosine | 0.402 (term difficulty) |
| **Cos gap (EN-Tr minus EN-Ref)** | **-0.294** |

The cos gap catches a different failure mode from confidence — specifically Latin borrowings and transliterations where the model is confident but wrong:

- "Vas deferens struktuur" instead of "Seemnejuha" (conf 5, gap 0.65)
- "Hemoptüüs" instead of "Veriköha" (conf 5, gap 0.52)
- "Atriaalflutter" instead of "Kodade laperdus" (conf 5, gap 0.45)

**Combined signal** (confidence <=4 OR cos_gap > 0.05): keeps 131 translations averaging **0.775** composite vs confidence alone keeping 227 at 0.657.

**Output files:**
- `data/evals/ee_extension_embeddings.csv` — per-concept cosine scores, string similarity, Latin flag
- `data/evals/hierarchy_cosine_baselines.json` — per-hierarchy baseline statistics
- `data/evals/embeddings/en_vecs.npy` — 17,877 x 1024 English embeddings
- `data/evals/embeddings/et_vecs.npy` — 17,877 x 1024 Estonian embeddings
- `data/evals/embeddings/sctids.npy` — SCTID index

**Visualisations:**
- `data/evals/cosine_histograms_by_hierarchy.png`
- `data/evals/cosine_distribution_latin_vs_native.png`
- `data/evals/cosine_boxplots_by_hierarchy.png`
- `data/evals/strsim_vs_cosine_scatter.png`

---

## 3. Full Extension Translation: Qwen 35B

**Goal:** Translate all 17,877 Estonian SNOMED extension terms with Qwen 3.5 35B (GPTQ-Int4) and compare against official translations.

**Model:** `Qwen/Qwen3.5-35B-A3B-GPTQ-Int4` served via vLLM (dgx-vllm:latest)
**Rules applied:** body structure (8 rules), morphologic abnormality (4 rules)

### Results by hierarchy

| Hierarchy | Count | EN-Official | EN-Qwen | Qwen-Official |
|-----------|-------|-------------|---------|----------------|
| body structure | 1,390 | 0.518 | 0.631 | 0.678 |
| disorder | 3,810 | 0.669 | 0.706 | 0.789 |
| morphologic abnormality | 1,957 | 0.700 | 0.723 | 0.814 |
| procedure | 2,960 | 0.692 | 0.719 | 0.772 |
| finding | 462 | 0.654 | 0.688 | 0.742 |
| substance | 448 | 0.565 | 0.636 | 0.750 |
| organism | 5,847 | 0.939 | 0.960 | 0.944 |
| person | 147 | 0.576 | 0.586 | 0.733 |
| physical object | 234 | 0.583 | 0.642 | 0.687 |
| specimen | 149 | 0.543 | 0.632 | 0.621 |

Qwen translations consistently have higher EN-Translation cosine than official translations — the Latin/transliteration bias. The model produces translations closer to English than the official Estonian terms.

**Translation time:** ~12 minutes (32 concurrent requests)
**Throughput:** Not measured for 35B in this run

**Output:** `data/evals/ee_extension_translations/`

---

## 4. Full Extension Translation: Qwen 122B

**Goal:** Compare the larger Qwen 3.5 122B-A10B model against the 35B.

**Model:** `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` served via vLLM (dgx-vllm:latest)
**Throughput:** ~1,100 tok/s prefill, ~35-50 tok/s generation (32 concurrent)
**Translation time:** ~45 minutes
**Note:** Prefix cache hit rate was 0% despite shared system prompts per hierarchy — needs investigation.

### 35B vs 122B comparison

| Hierarchy | Count | 35B-Ref | 122B-Ref | Delta |
|-----------|-------|---------|----------|-------|
| event | 42 | 0.722 | 0.788 | **+0.066** |
| qualifier value | 114 | 0.719 | 0.758 | **+0.039** |
| person | 147 | 0.733 | 0.764 | **+0.031** |
| substance | 448 | 0.750 | 0.780 | **+0.030** |
| observable entity | 156 | 0.747 | 0.765 | +0.018 |
| disorder | 3,810 | 0.789 | 0.807 | +0.018 |
| body structure | 1,390 | 0.678 | 0.690 | +0.012 |
| procedure | 2,960 | 0.772 | 0.784 | +0.012 |
| morphologic abnormality | 1,957 | 0.814 | 0.826 | +0.011 |
| specimen | 149 | 0.621 | 0.630 | +0.009 |
| organism | 5,847 | 0.944 | 0.939 | -0.005 |
| **OVERALL** | **17,877** | **0.825** | **0.833** | **+0.008** |

**Head to head:** 122B wins 29.5%, 35B wins 25.4%, ties 45.1%

### Selective model routing recommendation

Best value from 122B on: event, qualifier value, person, substance (751 terms, 4.2% of total) — these show the largest quality gains. The remaining hierarchies get diminishing returns for 3x the compute cost.

**Output:** `data/evals/ee_extension_translations_122b/`

---

## 5. vLLM Performance Notes

### Qwen 122B-A10B GPTQ-Int4 on DGX Spark

- **Prefill:** ~1,100 tokens/s
- **Generation:** 35-50 tokens/s (batched, 32 concurrent)
- **GPU memory utilisation:** 0.85
- **KV cache usage:** 15-18%
- **Prefix cache hit rate:** 0% (bug — needs investigation)
- **Model load time:** ~10 minutes (39 safetensor shards at ~10s each)

### Potential optimisations identified

1. **Fix prefix caching** — shared system prompts per hierarchy should cache; would significantly reduce prefill tokens
2. **Multi-token prediction (MTP)** — Qwen 3.5 122B supports `qwen3_next_mtp` speculative decoding with `num_speculative_tokens=2`
3. **Hybrid quantisation** — GPTQ-Int4 for MoE experts, FP8/BF16 for attention + shared expert layers. A custom vLLM fork (github.com/rmstxrx/vllm-hybrid-quant) reports 15 -> 21.5 tok/s single-request on Spark (+43%)
4. **Tensorizer / sharded state** — pre-process checkpoint for faster loading (seconds instead of 10 minutes)

---

## 6. Infrastructure Changes

### docker-compose.yml

- Added `vllm` service: Qwen 35B GPTQ-Int4 on port 8000 using `dgx-vllm:latest` image
- Added `vllm-122b` service: Qwen 122B GPTQ-Int4 on port 8001 using `dgx-vllm:latest` image
- Fixed `max-num-batched-tokens` for 122B (2096 -> 8192) to satisfy Mamba cache block size requirement

### New scripts

| Script | Purpose |
|--------|---------|
| `scripts/confidence_calibration.py` | 4-variant confidence calibration analysis |
| `scripts/translate_ee_extension.py` | Full extension translation with any vLLM model, embedding comparison, histogram generation |
| `scripts/build_eval_sample.py` | Stratified eval sample builder using local SNOMED GML graph |
| `scripts/optimize_rules.py` | Iterative rule optimisation with incremental building, ablation, train/holdout validation |
| `scripts/eval_translations.py` | Hybrid evaluation metric (chrF + BGE-M3 + exact match) |

---

## 7. Next Steps

1. **Agentic RAG loop comparison** — Build a loop that uses confidence assessment to route low-confidence translations to RAG enrichment (paired translations, Sonaveeb dictionary, clinical docs, web search — but NOT the SNOMED EE extension itself). Compare 35B vs 122B as the loop model.
2. **Fix prefix caching** — Investigate why vLLM reports 0% prefix cache hit rate for the 122B model despite shared system prompts.
3. **MTP benchmark** — Test multi-token prediction (`qwen3_next_mtp`) throughput impact on a 500-term subset.
4. **Hybrid quantisation** — Evaluate the rmstxrx/vllm-hybrid-quant fork for throughput gains.
5. **Selective model routing** — Wire hierarchy-to-model mapping into the translation pipeline (122B for event, qualifier value, person, substance; 35B for everything else).
