# TODO: Exemplar-retrieval relevance investigation

## Question

When the Korean translation pipeline retrieves top-K "similar EN→KO pairs" from the
KR release (via BGE-M3 hybrid search over Qdrant), how often does it surface
pairs that are *structurally* relevant — same modality, same anatomical region,
same procedural action — versus pairs that match only on surface text?

If there is a **generalisable** structural mismatch (e.g. "target is imaging,
exemplar is not"), that becomes a single universal pre-filter on the retrieval
step. If the noise is diffuse, we leave retrieval as-is and invest elsewhere.

This does **not** belong in the per-resource manifest (see
`configs/resources_ko.yaml`). It is a pipeline-level question about whether
retrieval itself needs a standard filter.

## Why it matters

The current lookup (see
[scripts/translation/translate_korean_with_lookup.py](../scripts/translation/translate_korean_with_lookup.py)) ranks the entire KR release by BGE-M3 similarity. Spot-checks
suggest BGE-M3 sometimes pulls neighbours that share only surface words
(e.g. the `Excision of X` pattern pulls in unrelated excisions for a CT-of-X
target) instead of structurally-related exemplars. We don't yet know how often
that happens, nor how much it hurts translation quality.

## Method

1. **Sample across hierarchies.** 50 concepts each from:
   - `<<71388002` Procedure
   - `<<404684003` Clinical finding
   - `<<123037004` Body structure
   - `<<363787002` Observable entity
   - `<<105590001` Substance

   Restrict to concepts with a KR-release preferred term so we have ground
   truth for the target as well.

2. **Run existing BGE-M3 lookup** against Qdrant for each, capture top-20
   (English FSN, Korean preferred term, similarity score, exemplar SCTID).

3. **Hand-rate each hit** for structural relevance on a small ordinal scale:
   - 3: structurally close (shares modality, site, and action class)
   - 2: partially relevant (shares 1 of {modality, site, action})
   - 1: surface-only (shared English tokens but different structure)
   - 0: noise

4. **Look for cheap, generalisable filters.** For every low-rated hit, ask:
   would a simple structural check have removed it?
   - Same top-level hierarchy as target?
   - Shares an attribute (`Method`, `Procedure site`, `Finding site`) with
     target?
   - Same `Associated morphology`?

   Tally which checks would have improved ratings, and at what cost
   (how many high-rated exemplars they'd also remove).

5. **Decide.**
   - If a simple check wins on >X% of noise hits without nuking good
     exemplars, it becomes a **universal** pipeline filter on the retrieval
     step. Not a manifest entry.
   - If the noise is diffuse, leave retrieval unchanged and record that.

## Outputs

- `scripts/analysis/exemplar_relevance_sample.py` — builds the sample and
  runs lookups.
- `data/analysis/exemplar_ratings_<date>.csv` — hand-rated results.
- `docs/exemplar_retrieval_findings_<date>.md` — summary and decision.

## Dependencies

- Existing Qdrant collection `paired_translations_ko`
  ([scripts/data_prep/build_qdrant_index_ko.py](../scripts/data_prep/build_qdrant_index_ko.py))
- For attribute-based filters to be testable, Qdrant payloads would need to
  carry each pair's SCTID and defining attributes. They currently carry
  `text` / `translation` / `direction` only. A re-index is required before
  step 4 can test attribute-based filters — confirm scope before starting.

## Explicitly out of scope

- Per-domain ECL-tiered retrieval scoped in a manifest. That was considered
  and rejected: if a rule is generalisable it belongs in the pipeline, not
  in config.
- Anything about the static resources (Editorial Guide addendum, KAA / KARP
  dictionaries, KFDA corpus) — those live in
  [../configs/resources_ko.yaml](../configs/resources_ko.yaml).
