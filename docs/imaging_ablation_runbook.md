# Imaging-resources ablation — runbook

End-to-end steps to run the experiment planned in
[todo_imaging_resources_ablation.md](todo_imaging_resources_ablation.md).

## What the experiment measures

Do the radiology-specific resources (editorial addendum, KAA anatomy
dictionary, KARP radiation glossary) improve translation of imaging
concepts beyond what the base style guide + existing BGE-M3 exemplar
lookup already produces?

- **Arm A (baseline)**: base `style_guide_ko_v3.md` + exemplar lookup.
- **Arm B (with extras)**: arm A + `radiology_editorial_guide_ko.md`
  addendum + KAA body-site lookup + KARP radiation-term lookup.

Judge: LLM pairwise comparison against the KR reference translation,
order-swapped for position-bias control.

## Prerequisites (one-off)

Assumes the project venv is set up (`source .venv/bin/activate`) and the
existing translation pipeline's Qdrant index `paired_translations_ko` and
`data/evals/korean/lookup_cache.json` have already been built via
[scripts/translation/translate_korean_with_lookup.py](../scripts/translation/translate_korean_with_lookup.py)
`--prepare-lookups`. The ablation reuses the cache unchanged.

### 1. Build the dictionaries (stdlib only, ~2s)

```
python scripts/data_prep/extract_dictionaries.py
```

Produces:

- `data/korean/dictionaries/kaa_anatomy.tsv` — KAA anatomy termbase (~7.5k entries)
- `data/korean/dictionaries/karp_radiation.tsv` — KARP radiation glossary (~3.5k entries)

### 2. Build the imaging eval subset and attribute map (~30s, needs networkx)

```
python scripts/experiments/build_imaging_ablation_inputs.py
```

Loads `snomed_graph/full_concept_graph.gml`, filters
`data/evals/korean/procedure_eval_set.csv` to descendants of
`<<363679005 |Imaging (procedure)|`, and extracts body-site /
method attributes for each.

Produces:

- `data/evals/korean/imaging_ablation/imaging_eval_set.csv` (~774 rows)
- `data/evals/korean/imaging_ablation/imaging_attributes.json`

On the current release this yields **6,570 imaging descendants** and **774**
eval concepts with KR reference translations. 700 of the 774 carry a
body-site attribute (direct, indirect, or generic).

### 3. Start a vLLM backend for the translator

Use the existing docker-compose setup for whichever model you want to test.
Default in `configs/models.json` is `gemma4-26b` on port 8083.

```
docker compose up -d snomed-gemma4    # or whichever model container
```

## Running the ablation

### 4. Translate under each arm

```
# baseline
python scripts/experiments/translate_imaging_ablation.py --arm A --tag gemma4-26b

# with extras
python scripts/experiments/translate_imaging_ablation.py --arm B --tag gemma4-26b
```

Each run writes:

- `data/evals/korean/imaging_ablation/translations_A_gemma4-26b.csv`
- `data/evals/korean/imaging_ablation/translations_B_gemma4-26b.csv`

Columns: `sctid, preferred_term, ko_reference, translation, kaa_hit, karp_hits`.
The last two are diagnostic (empty in arm A) — they show which resources
fired per concept.

Flags of interest:

- `--limit N` — cap rows for a smoke test.
- `--concurrency N` — override job concurrency.
- `--resume` — append to an existing output.
- `--model <key>` — switch model.

### 5. Pairwise judge

```
python scripts/experiments/judge_imaging_ablation.py \
    --arm-a data/evals/korean/imaging_ablation/translations_A_gemma4-26b.csv \
    --arm-b data/evals/korean/imaging_ablation/translations_B_gemma4-26b.csv \
    --output data/evals/korean/imaging_ablation/judgements_gemma4-26b.csv
```

Each non-identical pair is judged twice with candidate order swapped. Only
verdicts that agree across both orderings are counted as "consistent";
inconsistent ones are flagged separately (an early warning for position
bias).

Defaults to the `gemma4-26b` judge model. Use a different model with
`--model qwen122b` for a cross-check.

On exit the script prints a summary of A-wins, B-wins, ties, and
inconsistents.

### 6. Post-hoc analysis (manual)

Suggested drill-downs using the written CSVs:

- **Exact-match and char-similarity rates per arm** — reuse
  [scripts/evaluation/score_korean_translations.py](../scripts/evaluation/score_korean_translations.py).
- **Where B wins** — filter `judgements.csv` for `winner == "B"` and sort by
  `kaa_hit` and `karp_hits` presence. Does winning correlate with resource
  firing?
- **Where B loses** — look for KAA mismatches with KR-release preferred
  terms (e.g. KAA says `콩팥` for kidney but KR release prefers `신장`). This
  is a known tension and the most likely source of regressions.

## Costs and timings (ballpark, gemma4-26b @ concurrency 16)

- Translation arm: ~774 concepts × 2 arms ≈ 1500 LLM calls. ~2–5 minutes per arm.
- Judgement: ~774 pairs × 2 orderings ≈ 1500 LLM calls. ~3–8 minutes.
- Total wall time on a single H-class GPU: well under 30 minutes.

## Known risks (restated from the TODO)

- **KR coverage bias.** The eval references come from KR. If KHIS authored
  using the editorial guide, arm B gets a tailwind. Check manually for a
  handful of cases where A and B disagree and the reference aligns with B.
- **KAA vs KR disagreement.** KAA prefers pure-Korean for some body sites
  where the KR release prefers Sino-Korean (e.g. 콩팥 vs 신장 for kidney).
  The ablation should show where injecting KAA hurts. If the win-rate
  split is driven by body-site choice, consider either switching to the
  KR-release body-site strings (via a pre-compiled site-preference map)
  or dropping KAA injection and relying on the existing exemplar lookup.
- **Position bias.** Mitigated by running each pair in both orderings and
  counting only consistent verdicts. If the `inconsistent` count is high
  (say >15% of judged), upgrade the judge model.
- **KARP over-matching.** The token matcher drops keys shorter than 4
  characters but can still over-fire on common words. Inspect the
  `karp_hits` column; if many rows carry 4+ matches of little relevance,
  tighten `lookup_karp_tokens`.
