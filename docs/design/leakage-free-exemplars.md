# Design: leakage-free exemplar retrieval (sctid self-exclusion)

**Status:** DRAFT — awaiting sign-off. **Date:** 2026-07-03.

## Problem

The exemplar corpus `pooled_legacy` (`data/EN-KO/all_bilingual_pairs.csv`)
contains the Korean SNOMED extension itself (39k `SNOMED` + 18k
`SNOMED_synonyms` pairs). The eval sets (dspy_splits) are *also* extension
procedure concepts. So when we translate a test term, BGE-M3 retrieval returns
the term's own concept description — **the exact gold Korean — as a top
exemplar for 87.9% of test terms** (measured in the eval's exemplar cache). The
held-out numbers (GEPA 55.6%, hand v5_1 58.1%, induced ~50%) therefore measure
exemplar-selection, not translation. See note-2 / conclusion-6 on problem
`translation-prompt-context`.

We want retrieval that **excludes the query concept's own canonical entries**,
and a run that **reports exactly what was excluded**.

## Root causes in the current build

`scripts/data_prep/build_en_ko_pairs.py`:
- `build_snomed()` iterates over `conceptId` but emits only `(en, ko)` — **the
  sctid, which we need for exclusion, is discarded.**
- The pool is 2 data columns (`EN,KO`) + a coarse `source` tag.
- Combined-file dedup is by `(en_lower, ko)` with **first-source-wins** in a
  fixed order (`EDI` first, and EDI is 385k rows). A canonical SNOMED pair that
  also appears in EDI is tagged `EDI` and its concept identity is lost — so
  source-based exclusion alone would miss it. Exclusion must key on **sctid**,
  carried on the row regardless of source tag.

`snomed_translation/exemplars.py`:
- Index payload is `{source, direction, lang, text, translation}` — **no
  sctid**.
- `iter_source_pairs` yields only `(en, tgt)`.
- Collection name is a content hash of the CSV, so enriching the schema forces a
  new collection (see D2).

`scripts/translation/translate_korean_with_lookup.py::lookup_pairs`:
- Retrieves top-N by the query's English text; **no self-exclusion filter**
  (only a direction filter). The query sctid is available upstream
  (`ensure_exemplars` iterates rows with `sctid`) but is not threaded in.

## Design

### 1. Richer, sctid-bearing pool schema
New columns for `all_bilingual_pairs.csv` (and the per-source files):

| EN | KO | source | sctid |
|----|----|--------|-------|

- `source` = provenance (`EDI`/`KCD7`/`SNOMED`/`SNOMED_synonyms`/`LOINC`/…).
- `sctid` = SNOMED concept id, **populated for SNOMED/SNOMED_synonyms rows**,
  blank otherwise. This is the canonical key we exclude on.
- Regenerate **only** `SNOMED.csv` + `SNOMED_synonyms.csv` from the present KR +
  International RF2 releases (carry `cid` through). EDI/KCD7/LOINC keep their
  existing CSVs (Athena raw source is gone but the built CSVs are on disk);
  they get a blank sctid column.

### 2. Dedup rethink (D1)
- Dedup key becomes `(en_lower, ko, sctid)` — genuine duplicates collapse, but
  the **same surface form from two different concepts stays as two rows** so
  exclusion is complete.
- When one `(en_lower, ko)` exists both with a sctid (SNOMED, canonical) and
  without (e.g. EDI), **keep the sctid-bearing row and drop the plain
  duplicate** (canonical origin wins — the opposite of today's EDI-first rule).
- Net effect: every canonical extension pair carries its sctid; non-canonical
  sources fill gaps without shadowing canonical identity.

### 3. sctid into the index (D2 — compute tradeoff)
The exclusion needs `sctid` in each point's payload. Two options:

- **(A) Re-index** from the enriched CSV. Cleanest / most reproducible, but
  re-embeds ~475k pairs with BGE-M3 (dense+sparse) — contends with the vLLM that
  holds the GPU; roughly tens of minutes on GPU, hours on CPU.
- **(B) Payload-patch in place.** Keep the existing 475k collection, `set_payload`
  the sctid onto matching points (by `text`+`translation`), and **pin
  `cfg.qdrant.exemplar_collection`** so the flow uses it regardless of CSV
  digest. No re-embedding (minutes). Slightly less "pure" (payload enriched
  out-of-band from the CSV) but fully correct for exclusion; reproducible via
  the enriched CSV + a one-shot patch script.

Recommendation: **(B)** for speed now, with the enriched CSV committed so a
future clean re-index (A) is a drop-in.

### 4. Self-exclusion in retrieval + reporting
- Thread the query `sctid` from `ensure_exemplars` → `lookup_pairs`.
- `lookup_pairs` retrieves a larger buffer, then **drops any hit whose
  `payload.sctid == query_sctid`** (belt-and-suspenders: also drop hits whose
  tag-stripped English equals the query's, catching any canonical row that lost
  its sctid). Returns the top-N survivors **plus the list of dropped exemplars**.
- The `translate` stage accumulates and emits:
  - **run metrics**: `self_excluded_total`, `queries_with_self_hit`,
    `queries_with_gold_at_rank1_before_exclusion` (this last one *quantifies the
    leakage we just found*).
  - **artifact**: `excluded_exemplars_<tag>.csv` — one row per dropped exemplar
    (`query_sctid, query_en, excluded_sctid, excluded_en, excluded_ko, rank`),
    so a run shows exactly what was excluded.

### 5. Clean eval (D3 — research scope)
- **Minimum:** re-run the eval of the existing GEPA guide **and** v5_1 on
  `kr_test_split` with self-exclusion ON → the leakage-corrected comparison.
- **Fuller:** GEPA already *trained* gold-free (its translator used the
  `sme_review` cache, 0% leak, cache-miss = no exemplars), so a re-eval is the
  priority. Optionally also **re-run GEPA optimization** against the new clean
  pooled exemplars so train and eval share one clean regime — bigger, but
  removes the train/eval mismatch entirely.

## Decisions (signed off 2026-07-03)
- **D1 = keep all provenance rows.** Dedup within `(EN, KO, source)` only; do
  NOT collapse across sources. The same pair from EDI and SNOMED stays as two
  rows (EDI row blank sctid, SNOMED row with sctid). Bigger pool / more index
  points, but full provenance preserved.
- **D2 = full re-index.** Re-embed the enriched pool into a fresh collection
  (accept the BGE-M3 compute cost). No payload-patching.
- **D3 = re-eval only for now.** Re-run the GEPA guide + v5_1 eval on
  `kr_test_split` with self-exclusion. A clean GEPA *re-optimization* comes later.

## Added requirement: show exemplar provenance to the model
When exemplars are put in the translation prompt, **each one carries its
`source`** (e.g. `SNOMED`, `SNOMED_synonyms`, `EDI`, `KCD7`, `LOINC`). Rationale
(user): after we exclude the query concept's own canonical SNOMED entry, a
remaining exemplar may still be a *correct* translation from another vocabulary
(Athena EDI/KCD7 etc.). That is legitimate — but the model must know it is NOT a
canonical SNOMED reference for this concept and still weigh how to translate. So
provenance is shown, not hidden.

### Residual-leak consequence (must measure)
sctid-exclusion removes the concept's canonical SNOMED self-reference, but an
independent source (EDI/KCD7) could carry the same English→gold-KO pair (no
sctid, so not excluded). This is accepted, but the run MUST report it:
`queries_with_gold_via_other_source_after_exclusion` — so residual leakage is
visible, not silent.

## Index payload change
Point payload gains **`sctid`** (blank for non-SNOMED) and **`row_source`** (the
per-row provenance; distinct from the existing `source = spec.id`). Exclusion
keys on `sctid`; the prompt renders `row_source`.

## Results (implemented + run 2026-07-03)
Built: pool regenerated (514,756 rows, 95,834 with sctid; `EN,KO,source,sctid`),
index payload carries `sctid`+`row_source`, `lookup_pairs` self-excludes by
sctid and returns `(kept, excluded)`, `format_pairs_table` shows a `Source`
column, `ensure_exemplars` persists an exclusions sidecar, the translate stage
emits self-exclusion metrics + an `excluded_exemplars_<tag>.csv` audit. Tests in
`tests/test_self_exclusion.py` (185 pass). Pool re-indexed on GPU (gemma vLLM
stopped to free memory, relaunched at **0.45** util — was 0.60).

Clean held-out eval, kr_test_split (124), sctid self-exclusion ON:

| guide | LEAKY exact/chrF | CLEAN exact/chrF |
|---|---|---|
| hand v5_1 | 58.1 / 84.1 | **36.3 / 70.1** (run 6646ab05591c) |
| GEPA(Fable) | 55.6 / 81.6 | **21.8 / 63.9** (run df42e169939c) |

Exclusion audit (shared cache): 270 exemplars dropped across 111/124 queries;
**gold removed for 108 (87%)** — confirms the measured leak; **residual gold via
another source = 0**. Leakage inflated both guides ~+20 exact points and hid a
14.5-pt gap behind an apparent 2.5-pt one. See conclusion-7. Caveat: the GEPA
guide was optimised in a near-exemplar-free regime (sme_review cache), so a clean
GEPA RE-OPTIMISATION in this pooled-excluded regime is the fair next test.
