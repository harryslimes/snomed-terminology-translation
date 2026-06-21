# Korean SNOMED Translation Evaluation Report

**Date:** 2026-04-10
**Model:** Gemma 4 26B-A4B (AWQ-4bit) via vLLM
**Eval set:** 3,693 SNOMED CT Procedure concepts with Korean reference translations from KHIS KR1000267 (2025-12-15 release)

## Key Result

Adding bilingual pair lookup (RAG) to the translation pipeline produced a **dramatic improvement** over all previous runs:

| Run | N | Exact% | Norm% | CharSim | Jaccard |
|-----|---|--------|-------|---------|---------|
| Qwen 35B baseline | 100 | 10.0% | 15.0% | 0.595 | 0.275 |
| Qwen 35B + style guide | 100 | 19.0% | 21.0% | 0.631 | 0.438 |
| Qwen 122B + style guide v3 | 100 | 33.0% | 38.0% | 0.711 | 0.554 |
| Gemma 4 baseline | 100 | 10.0% | 14.0% | 0.628 | 0.288 |
| Gemma 4 + style guide | 100 | 22.0% | 25.0% | 0.664 | 0.468 |
| Gemma 4 + style guide v3 | 100 | 33.0% | 35.0% | 0.710 | 0.544 |
| Gemma 4 + style guide v3 (full) | 3,693 | 26.4% | 30.1% | 0.671 | 0.487 |
| **Gemma 4 + lookup (full)** | **3,693** | **68.1%** | **70.2%** | **0.877** | **0.792** |

**The lookup-augmented run achieves 68% exact match** (vs 26% for the previous best full-set run), with character similarity jumping from 0.671 to 0.877.

## What Changed

### Previous runs (baseline / style guide only)
- Model receives English term + optional style guide
- No example translations provided
- Model must generate Korean from scratch

### This run (lookup-augmented)
- For each English term, search 475,700 EN-KO bilingual pairs via Qdrant hybrid search (BGE-M3 dense + BM25 sparse, RRF fusion)
- Inject top-5 most similar translations as a markdown table in the prompt
- Style guide also included
- Model can copy/adapt from real Korean medical terminology rather than guessing

### Bilingual pair sources
| Source | Pairs | Domain |
|--------|-------|--------|
| EDI (HIRA) | 385,203 | Procedures, drugs, measurements |
| SNOMED KR ⨝ International | 56,778 | All SNOMED domains (synonyms) |
| SNOMED KR (canonical) | 39,056 | 1:1 FSN pairs |
| KCD7 | 22,413 | Diseases/conditions |
| LOINC-KO | 11,306 | Lab observations (part-level) |
| **Total** | **475,700** | |

### Prompt structure
```
System: [medical translator instruction] + [full Korean SNOMED style guide]

User:
Here are similar Korean SNOMED translations for reference:
|English|Korean|
|---|---|
|Excision of lung|폐 절제|
|Excision of trachea|기관 절제|
|...(3 more)...|

Translate this SNOMED CT procedure term from English to Korean.
English: Excision of tracheal tumor by thoracic approach
Korean:
```

## Pipeline Architecture

### Two-step process
1. **Lookup phase** (`--prepare-lookups`): loads BGE-M3, queries Qdrant for each term, saves results to `lookup_cache.json`, exits (frees GPU memory)
2. **Translation phase**: loads cache from disk, sends 16 concurrent requests to vLLM (no embedder in memory)

### Performance
- Lookup phase: 3,693 terms in ~8 minutes (sequential, GPU-bound embedding)
- Translation phase: 3,693 terms in 248 seconds (**14.9 req/s**, 0 errors)
- Total wall time: ~12 minutes
- Previous sequential approach: ~60+ minutes estimated

### Infrastructure
- **LLM:** Gemma 4 26B-A4B (AWQ-4bit) via vLLM, `gpu_memory_utilization=0.60`, `max_model_len=16384`
- **Prefix caching:** enabled — the ~22k-char system prompt (style guide) is cached in KV, only the user message (~200 chars) recomputes per request
- **Vector store:** Qdrant with 951,400 vectors (475,700 bilingual pairs × 2 directions), BGE-M3 hybrid (dense 1024-d + BM25 sparse)
- **Concurrency:** 16 in-flight HTTP requests via ThreadPoolExecutor. vLLM handles the server-side batching via continuous batching — the threads just keep the request queue full so vLLM has multiple sequences to batch together each step. A single-threaded client would leave vLLM's scheduler idle between requests.

## Metrics Explained

- **Exact%**: translation exactly matches KR extension reference
- **Norm%**: matches after stripping all whitespace
- **CharSim**: 1 - (Levenshtein distance / max length) on normalised strings
- **Jaccard**: Jaccard similarity over space-separated tokens

## Reproducing

```bash
# Step 0: Build EN-KO bilingual pairs (if not already done)
.venv/bin/python scripts/data_prep/build_en_ko_pairs.py --skip-icd11

# Step 1: Index into Qdrant (requires BGE-M3 + Qdrant running)
.venv/bin/python scripts/data_prep/build_qdrant_index_ko.py

# Step 2: Prepare lookups (loads BGE-M3, queries Qdrant, saves cache)
.venv/bin/python scripts/translation/translate_korean_with_lookup.py --prepare-lookups

# Step 3: Translate (requires vLLM serving Gemma 4)
.venv/bin/python scripts/translation/translate_korean_with_lookup.py --concurrency 16

# Step 4: Score
# (use inline scorer or scripts/evaluation/score_korean_translations.py)
```

## Files

| File | Description |
|------|-------------|
| `translations_gemma4-26b_lookup.csv` | 3,693 translations from this run |
| `lookup_cache.json` | Cached Qdrant lookup results (reusable across models) |
| `procedure_eval_set.csv` | Full eval set (3,693 procedures with KR reference) |
| `procedure_eval_sample_100.csv` | 100-row sample used in earlier runs |
| `configs/models.json` | Model configs and job definitions |

## Next Steps

- Run the same lookup-augmented pipeline with **Qwen 122B** to see if a larger model improves on 68% exact match
- Analyse the 32% non-matching translations — are they wrong, or acceptable alternatives?
- Consider adding ICD-11 Korean pairs (via WHO API) to further expand lookup coverage
- Explore using the lookup cache with the full agentic pipeline (reflection + forced revision) for additional quality gains
