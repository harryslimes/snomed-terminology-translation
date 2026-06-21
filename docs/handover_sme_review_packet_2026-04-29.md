# Handover — 100-concept SME review packet for Korean terminologists

**Date:** 2026-04-29
**Branch:** `feature/qwen122b-translation-pipeline`
**Working dir:** `data/sme_review/2026-04-24/`

## Goal

Deliver a 100-concept Korean translation review packet to KHIS Korean
medical terminologists. They rate machine translations of long-tail
imaging concepts (no KR reference exists), correct the wrong ones, and
their judgements calibrate our Sonnet LLM-judge.

## Where we are

The packet is **built and Sonnet-judged**. What remains is final QA,
delivery format, and recipient comms.

### Artifacts already produced

In [data/sme_review/2026-04-24/](../data/sme_review/2026-04-24/):

- `sme_review_critique.csv` (100 rows) — fast-review CSV (rate + correct).
- `sme_review_independent.csv` (100 rows) — translate-first-then-compare CSV.
- `sme_review_internal.csv` (100 rows) — full audit trail (our records).
- `sonnet_review_100.csv` (100 rows) — Sonnet judgements already populated:
  - **27 ACCEPTABLE / 63 PARTIAL / 3 WRONG** (raw count; CSV has a few
    embedded-comma quoting quirks that miscount in naive `awk` — verify
    with a CSV-aware parser before quoting these numbers externally).
- `methodology.md` — packet methodology, ready to ship to SMEs as-is.
- `sample_100.csv`, `back_trans.csv`, `translations_sme_pool.csv`,
  `untranslated_imaging.csv`, `untranslated_imaging_attributes.json` —
  supporting data.

### Pipeline that produced the translations

- Model: `gemma4-26b` (AWQ-4bit, local vLLM on DGX Spark).
- Style guide: `style_guide/style_guide_ko_v3_abbr.md`.
- Retrieval: BGE-M3 hybrid lookup → top-5 exemplars from
  `paired_translations_ko` Qdrant collection.
- KR-native body-site dictionary: fired on 61% of rows.

## What the next agent needs to do

### 1. Verify the Sonnet judgements joined cleanly into the SME CSVs

The two `sme_review_*.csv` files were built by
[scripts/sme_review/build_sme_csvs.py](../scripts/sme_review/build_sme_csvs.py).
Re-run it now that `sonnet_review_100.csv` is populated and confirm the
`sonnet_label` / `sonnet_what_is_wrong` / `sonnet_suggested_translation`
columns are filled in `sme_review_critique.csv`. (Spot check from the
earlier session: row 1 SCTID 394501000119108 has these columns
populated — looks good. But re-run to be safe; the methodology doc still
says "currently blank — to be populated when our Sonnet rate-limit
resets".)

```bash
python -m scripts.sme_review.build_sme_csvs \
  --sample      data/sme_review/2026-04-24/sample_100.csv \
  --translations data/sme_review/2026-04-24/translations_sme_pool.csv \
  --back-trans  data/sme_review/2026-04-24/back_trans.csv \
  --sonnet      data/sme_review/2026-04-24/sonnet_review_100.csv \
  --out-dir     data/sme_review/2026-04-24/
```

### 2. Update `methodology.md`

The "currently blank — to be populated when our Sonnet rate-limit resets"
sentence is stale. Replace with a short summary of the Sonnet
distribution (27/63/3) and a sentence on how the SMEs should treat the
Sonnet column (advisory hint, not authoritative).

### 3. Final QA on the SME-facing CSVs

Open `sme_review_critique.csv` and `sme_review_independent.csv` and check:

- No empty `pipeline_translation_ko` cells.
- Korean strings are clean Hangul (no leftover `<think>` tags, no
  English tail-text, no leading/trailing punctuation noise).
- `snomed_body_site_ko_kr_dict` is populated where the body site is in
  `data/korean/dictionaries/kr_body_sites.tsv`. Random-sample a few
  rows where it's blank to confirm the body site really is missing from
  the dict, not a join bug.
- Stratum balance matches methodology (30 / 20 / 20 / 15 / 10 / 5). Use
  `sme_review_internal.csv` or `sample_100.csv` to verify.

### 4. Decide delivery format

The SMEs almost certainly want **xlsx**, not raw CSV. Convert both
`sme_review_critique.csv` and `sme_review_independent.csv` to a single
`.xlsx` workbook with two tabs (one per review style), and a third
`README` tab summarising the methodology — ask the user before producing
the final file. Suggested approach: `pandas` + `openpyxl`, freeze header
row, set column widths so Korean strings aren't clipped.

The SMEs may not have a strong CSV-encoding setup; **save xlsx as
UTF-8** and verify Hangul renders in Excel before sending.

### 5. Confirm scope with the user before sending

Don't send anything to KHIS or post anywhere external without an
explicit go-ahead. Specifically confirm:

- Recipient list (likely the KHIS contacts — user should name them).
- Delivery channel (email, shared drive, etc.).
- Whether to include `methodology.md` as a separate file or fold into
  the xlsx README tab.
- Cover note tone — KHIS is a collaborator, not a vendor.

## Don'ts / gotchas

- **Don't re-sample.** The seed-42 sample is final; re-running
  `sample_concepts.py` with a different seed would invalidate the
  Sonnet judgements that already exist for these 100 SCTIDs.
- **Don't re-translate.** The translations in `translations_sme_pool.csv`
  are the production-candidate config. Switching models/style guides
  mid-packet would muddy the SME signal.
- **Don't run Sonnet again.** It already cost ~$1 and we have
  judgements for all 100. If a row legitimately needs re-judging,
  re-run only that row.
- **Don't commit the packet's CSVs to git.** `data/sme_review/` is
  intentionally untracked (check `.gitignore`); these are work-product
  artifacts, not source. Source scripts in
  [scripts/sme_review/](../scripts/sme_review/) and `methodology.md`
  are fine to commit.

## Key files (clickable)

- Methodology: [data/sme_review/2026-04-24/methodology.md](../data/sme_review/2026-04-24/methodology.md)
- Sampler: [scripts/sme_review/sample_concepts.py](../scripts/sme_review/sample_concepts.py)
- Sonnet reviewer: [scripts/sme_review/sonnet_review_no_ref.py](../scripts/sme_review/sonnet_review_no_ref.py)
- CSV builder: [scripts/sme_review/build_sme_csvs.py](../scripts/sme_review/build_sme_csvs.py)
- Sonnet judge cross-check (context): [docs/sonnet_judge_cross_check_2026-04-22.md](sonnet_judge_cross_check_2026-04-22.md)
- Long-tail evaluation plan (context): [docs/long_tail_evaluation_plan.md](long_tail_evaluation_plan.md)

## Open questions for the user

1. Confirm KHIS recipient list and delivery channel.
2. Critique-only, independent-only, or both? (Methodology offers both;
   SMEs may only have bandwidth for one.)
3. Deadline to give the SMEs.
4. Should the sonnet_label/sonnet_suggested columns be visible to SMEs
   in the critique CSV (current design — anchors them on Sonnet) or
   stripped (cleaner independent signal, but then the
   `sme_agree_with_sonnet` column is meaningless)?
