# TODO: Imaging-resources ablation experiment

## Question

Do the radiology-specific resources (Editorial Guide addendum, KAA anatomy
termbase, KARP radiation glossary) actually improve translation of imaging
concepts, or does the base style guide + existing exemplar lookup already
capture what's needed?

## Hypothesis

For concepts in `<<363679005 |Imaging (procedure)|` (7,059 concepts in the
International Edition as of 2026-04), adding the Editorial Guide addendum
plus deterministic body-site and radiation-term lookups will materially
improve agreement with the KR release's preferred Korean term.

## Design

Pairwise ablation with LLM-as-judge scoring.

### Concept set

All descendants (including self) of `363679005 |Imaging (procedure)|`
intersected with the KR release's preferred-term coverage. Sanity-check the
intersection size before running — full 7,059 is the ceiling; actual eval
size depends on how many imaging concepts KHIS has translated.

Command to enumerate:

```
ECL: <<363679005
Terminology: snomedct (or snomedct-kr for the translated subset)
```

### Arms

- **A (baseline)**: base `style_guide_ko_v3.md` + existing BGE-M3 exemplar
  lookup. Matches the current pipeline exactly.
- **B (with extras)**: everything in A, plus:
  - `radiology_editorial_guide` prompt addendum (from
    `configs/resources_ko.yaml`)
  - `kaa_anatomy` term-dictionary injection
  - `karp_radiation` term-dictionary injection

Hold the LLM, decoding parameters, exemplar count, and Qdrant collection
constant across arms. The only variables are the three resources.

### Judgement

Pairwise comparison per concept, blinded and order-randomised:

- **Reference**: KR release preferred Korean term (ground truth).
- **Candidates**: arm A translation, arm B translation.
- **Judge LLM prompt** asks: which candidate more closely matches the reference
  on (a) adherence to KR conventions in word order, modality naming, contrast
  phrasing, and body-site rendering, and (b) overall adequacy.
- Output: `A wins`, `B wins`, or `tie`, plus a one-line rationale.

Report aggregate win-rate plus stratified win-rates by imaging sub-scope
(CT, MRI, US, X-ray, nuclear medicine, bone density) to see where — if
anywhere — the extras help.

### Secondary metrics

Alongside the LLM judgement, compute for each arm:

- Exact-match rate against KR reference.
- Normalised edit distance to reference (character-level).
- Space-token Jaccard similarity to reference.

These are cheap and serve as a sanity check on the judge.

## Prerequisites

Before this experiment can run, the following need to exist:

1. **Resource file creation** — the manifest points at paths that don't yet
   exist:
   - `style_guide/addenda/radiology_editorial_guide_ko.md` (compile from
     `data/korean/RadiologyEditorialGuide_markdown/RadiologyEditorialGuide.md`)
   - `data/korean/dictionaries/kaa_anatomy.tsv` (extract from
     `Terms_from_KoreanAssociation_of_Anatomies.md`, three columns: `ko_preferred`,
     `en`, `la`; preserve KAA synonyms as a `ko_synonyms` column)
   - `data/korean/dictionaries/karp_radiation.tsv` (extract from
     `Terms_from_TheKoreanAssociation_for_RadiationProtection.md`, two
     columns: `en`, `ko`)

2. **Manifest-aware prompt builder** — current pipeline hard-codes the style
   guide path and user-prompt template in
   [scripts/translation/translate_korean_with_lookup.py](../scripts/translation/translate_korean_with_lookup.py#L53-L72).
   For the ablation we need a thin prompt-assembly layer that:
   - Loads `configs/resources_ko.yaml`.
   - For a given concept, evaluates which resources' scopes match.
   - Extracts each `term_dictionary` key via its `key_path`, does the lookup,
     and injects hits.
   - Concatenates matching `prompt_addendum` payloads in declared order.
   - Keeps `exemplar_set` behaviour identical to today.
   - A boolean `--enable-extras` flag can toggle arms A vs B by gating
     everything except `base_style_guide` and `kr_release_exemplars`.

3. **ECL scope resolution** — need a way to check, per target concept, whether
   its SCTID falls within a scope. Options:
   - Pre-compute a (SCTID → resource_ids) map once using Snowstorm ECL
     expansion; persist as JSON.
   - Or call Snowstorm per-concept per-scope (slower but simpler). Choose
     based on eval-set size; at a few thousand concepts, either works.

4. **Attribute extraction** — `kaa_anatomy`'s `key_path` needs the English FSN
   of the `Procedure site (363704007)` target concept. Need a Snowstorm lookup
   (or pre-cache) of each imaging concept's `363704007` and `363698007`
   attribute values.

## Outputs

- `scripts/experiments/ablate_imaging_resources.py` — runs both arms.
- `scripts/experiments/judge_imaging_ablation.py` — pairwise LLM judging.
- `data/evals/korean/imaging_ablation/<date>/translations_A.csv`,
  `translations_B.csv`, `judgements.csv`.
- `docs/imaging_resources_ablation_findings_<date>.md` — summary, win-rates
  by sub-scope, qualitative examples of where extras helped or hurt.

## Risks and considerations

- **KR coverage bias**: the eval set is exactly the concepts KHIS has
  already translated. If KHIS used the Editorial Guide when authoring, the
  reference *already encodes* the guide's rules and arm B gets an unfair
  tailwind. Mitigation: spot-check a handful of cases where A and B disagree
  and the reference matches B — is the KR term truly what the guide
  recommends, or is the match coincidental?
- **Dictionary lookup miss rate**: if KAA keys don't normalise cleanly onto
  SNOMED body-site FSNs (e.g. "appendix" vs "Appendix structure"), hit rates
  will be low and the KAA arm will effectively fall back to A. Measure and
  report hit rate as a diagnostic.
- **Judge bias**: instruction sensitivity and position bias are well-known.
  Randomise candidate order per call; consider running the judge twice with
  arms swapped and only counting consistent verdicts.

## Not in scope

- Finding / disorder translation (KFDA corpus). That resource is declared
  but disabled in the manifest; pick it up in a separate phase.
- Any change to exemplar retrieval. See
  [todo_exemplar_retrieval_investigation.md](todo_exemplar_retrieval_investigation.md).
