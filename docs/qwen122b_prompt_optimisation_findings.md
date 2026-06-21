# Prompt Optimisation Findings: Qwen 3.5 122B-A10B SNOMED CT English-to-Estonian Translation

## Setup

- **Model**: Qwen 3.5 122B-A10B (MoE, 10B active params), GGUF Q4_K_XL quantization, served via llama.cpp with `--reasoning off`
- **Task**: Translate 100 SNOMED CT medical terms from English to Estonian using a RAG pipeline (SNOMED graph context, paired translations from Qdrant, style guide)
- **Baseline comparison**: Claude Sonnet 4.6 translations of the same 100 terms
- **Inference settings**: temperature=0 (greedy decoding), concurrency=8 via asyncio

## Version Summary

| Version | System Prompt | Style Guide | Other Changes | Claude Exact Match |
|---------|--------------|-------------|---------------|-------------------|
| v3 (baseline) | Rules 1--8 | Truncated to 400 chars (bug) | -- | 35/100 |
| v4 | Rules 1--9 (added word-order rule) | Keyword-matched rules (fix) | Exact-match detection for paired translations | 35/100 |
| v5 | Rules 1--10 (added causal disambiguation) | Keyword-matched rules | Word-order rule restricted to disorder/procedure | 32/100 |
| v6 | Rules 1--8 (removed 9--10) | Keyword-matched rules | General style guide limit 300 to 500 chars | 33/100 |
| v7 (final) | Rules 1--8 | Keyword-matched rules | General style guide 300 chars, no exact-match detection | 36/100 |
| v3 rerun (control) | Rules 1--8 (identical to v3) | Truncated to 400 chars (identical to v3) | No changes at all | 37/100 |

### Pairwise comparison: v4 vs v3

| Category | Count |
|----------|-------|
| Identical | 62 |
| Improved | 15 |
| Degraded | 13 |
| Neutral | 10 |

### Pairwise comparison: v7 vs v3

22 terms changed. Of those, 12 overlapped with terms that also changed in the v3 rerun (nondeterminism noise). Only 10 were potentially attributable to the prompt change, and of those 10, only 4 had style guide rules actually fire.

## Critical Finding: 14% Nondeterminism

Re-running the exact v3 prompt with no changes produced **14 different translations out of 100**.

**Cause**: llama.cpp `--parallel 8` batched inference. Request ordering affects KV cache state, which changes output even at temperature=0.

**Implications**:

- All version comparisons carry a noise floor of roughly +/-2--3 on the Claude match count.
- The v3 rerun scoring 37/100 (vs the original 35/100) is a +2 improvement from pure noise.
- Single-run A/B comparisons are unreliable at this noise level.

## Style Guide Truncation Bug

The most consequential fix across all versions was correcting how the style guide is injected into the prompt.

### The bug

The old prompt truncated the hierarchy-specific style guide to 400 characters. For the "finding/disorder" section (~4838 chars total), this captured only:

- The "Uldised pohimotted" (general principles) preamble
- The first bullet about RHK-10 coding

It completely missed the "Kokkulepitud reeglid ja erandid" (Agreed rules and exceptions) table, which contains the actual translation patterns:

| English pattern | Estonian translation |
|----------------|---------------------|
| "due to" | "pohjustatud" / "-tekkeline" |
| "co-occurrent" | "X koos Y-ga" |
| "associated with" | "millegagi seotud" |
| "primary" | "primaarne" |
| "mixed" | "segatuupi" |
| "in remission" | "remissioonis" |

### The fix

Parse style guide sections into individual rules by bold keyword patterns, then match against keywords in the English source term. Only inject rules relevant to the specific term being translated.

**Result**: 6 out of 100 terms in the test set had matching rules. For those terms, the model now receives actual translation guidance instead of a truncated preamble.

## What Did Not Work

### 1. Word-order system prompt rule (rule 9)

Instruction: "Follow Estonian word order: condition + location + etiology." Helped 3 disorder terms but broke 1 body structure term. The rule is hierarchy-sensitive and would need per-hierarchy variants. Dropped because adding any system prompt text destabilised approximately 5% of unrelated translations.

### 2. Causal vs circumstantial disambiguation (rule 10)

Instruction: "due to -> tottu, in -> korral." Correctly fixed 1 term, but the model already handles this well from context. Adding it to the system prompt caused a net regression.

### 3. Exact-match detection for paired translations

Idea: check whether paired translations contain an exact match for the English term and highlight it. No terms in the 100-item test set had exact matches in the Qdrant database. Dead code with no effect; removed.

### 4. Increasing general style guide from 300 to 500 chars

Changed output for 94 terms that had no specific rules firing. This was pure destabilisation from altering prompt structure. Reverted.

## Recommendations

1. **Keep keyword-matched style guide rules (v7)**. This is an architecturally correct fix even though single-run metrics cannot reliably measure the impact due to the noise floor.

2. **Reduce nondeterminism**. Options: use `--parallel 1` in llama.cpp (slower but deterministic), run each term sequentially, or average over multiple runs.

3. **Do not add more system prompt rules**. The system prompt is at a local optimum for this model. Adding more rules hurts more than it helps -- the model is sensitive to system prompt length.

4. **Run 3+ repetitions per configuration for meaningful A/B testing**. Compare averages, not single-run numbers. The 14% noise floor makes single-run comparisons unreliable.

5. **Improve paired translation retrieval rather than prompt engineering**. Of the approximately 1000 tokens in a typical prompt, the style guide keyword matching only affects around 6% of terms. The biggest quality lever is likely improving retrieval from Qdrant, which affects all 100 terms.

## Files

| File | Description |
|------|-------------|
| `scripts/qwen122b_prompt.py` | Prompt template with keyword-matched style rules (v7 final) |
| `scripts/translate_sample_qwen122b.py` | Translation runner |
| `data/evals/sample/100_translations_qwen122b_v3.csv` | v3 baseline |
| `data/evals/sample/100_translations_qwen122b_v4.csv` | v4 (full changes) |
| `data/evals/sample/100_translations_qwen122b_v5.csv` | v5 (extra system rules) |
| `data/evals/sample/100_translations_qwen122b_v6.csv` | v6 (no system rules + style fix) |
| `data/evals/sample/100_translations_qwen122b_v7.csv` | v7 final |
| `data/evals/sample/100_translations_v3_rerun.csv` | v3 rerun (nondeterminism control) |
