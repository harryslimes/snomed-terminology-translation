# Long-tail translation evaluation — design plan

## Problem

Every evaluation metric we've used so far — exact-match, char-similarity,
pairwise LLM-judge against a reference — depends on having a KR-authored
Korean translation to compare against. We have that for 3,693 procedure
concepts (the KR release's coverage) and have driven all experiments off
that set.

The **project goal** is to translate the rest of the SNOMED procedure
hierarchy — ~55,000 concepts with no KR reference. That's the long tail.
We currently have no way to measure translation quality on it, because:

- The 3,693 KR-covered concepts are also the source of the BGE-M3 exemplar
  pool. Every eval concept has its own (or a very near) neighbour sitting
  in Qdrant. Our numbers reflect "best-case" retrieval conditions.
- On a truly novel concept — e.g. a procedure SNOMED added in 2024 that
  KHIS hasn't translated — there's no ground truth and no close
  exemplar. Our current pipeline's behaviour there is unmeasured.

Without a way to evaluate the long tail, every conclusion about pipeline
improvements is limited to "works well on concepts where the answer is
already in the retrieval pool." That's a very weak claim about production
readiness.

## Five candidate approaches

### 1. Synthetic long-tail simulation (primary)

Use the 3,693 KR-covered eval concepts, but at translation time
**exclude each concept's own translation from the Qdrant retrieval
pool** — and optionally exclude close neighbours (same body site, same
method). This simulates "I have a concept but its direct match isn't in
the exemplar table" without losing ground truth.

Why it's the best starting point:

- Uses only data we already have.
- Produces real exact-match / char-sim numbers with real KR-authored
  ground truth.
- Directly answers "how much does exemplar sparsity cost?" — which is
  the right framing for "what should we do for the long tail?"
- Cheap to build: one filter on the Qdrant query at lookup time.
- Unlocks re-testing of every parked resource (KAA, editorial addendum,
  KARP, v4 style guide) under harder conditions. The theory was always
  that these help where exemplars are weak; we've never actually tested
  that because our eval never had weak exemplars.

Configurable degrees of difficulty:

- **Exclude self only** — exemplars for exact SCTID filtered out.
  Mild penalty; close neighbours (sibling procedures with same method +
  site) still available.
- **Exclude self + same Procedure site** — e.g. for "CT of kidney,"
  remove all procedures that also reference Kidney structure. Harder.
- **Exclude self + same Method** — e.g. for a CT concept, remove all
  CT procedures. Very hard.
- **Exclude self + same Method + same Procedure site** — nearly
  zero-shot. Gives an upper bound on worst-case long-tail quality.

### 2. Consistency metrics on actual long-tail output (no reference needed)

Run translation across the full ~55k long tail once. Group outputs by
shared SNOMED attributes (Procedure site, Method, Access, Using
substance). Within each group, measure rendering variance for the shared
element:

- All kidney-site procedures → how many distinct Korean renderings for
  "kidney" appear?
- All CT procedures → how many distinct Korean renderings for "computed
  tomography" appear?

High variance = the model is giving inconsistent Korean for structurally
identical English. Low variance ≠ correctness, but high variance is a
defect on its own and measurable without a reference.

This is exactly what the KR inconsistency audit
(`imaging_inconsistencies_2026-04-20.md`,
`procedure_inconsistencies_2026-04-20.md`) does for the KR release.
Applying the same machinery to our output measures "are we at least as
internally consistent as KHIS's own authored set?" — a reasonable lower
bar.

### 3. Back-translation similarity

Pipe each Korean output through a different model doing KO→EN (Claude
Sonnet, GPT-4, or even gemma itself). Compute embedding similarity
between the back-translated English and the source English.

- **Catches:** hallucinated concepts, wrong anatomy, completely off-topic
  translations.
- **Misses:** stylistic / convention drift. `충수 절제` and `막창자꼬리 절제`
  will both back-translate to "excision of appendix" and score the same,
  but one matches KR convention and the other doesn't.
- **Cost:** ~N extra LLM calls (N = eval size).

Worth running because it's cheap and catches a class of error other
metrics miss.

### 4. LLM-as-judge for style-guide conformance

Give a strong external model (Claude Sonnet, GPT-4) the style guide +
the source English + the candidate Korean; ask "does this conform to the
rules?"

- **Circularity risk:** the generator was steered by the same style
  guide, so a judge using the same rules has an obvious bias toward
  calling the output "conforming." Partly mitigated by using a different
  model than the generator.
- **Useful for:** catching specific categorical violations (wrong word
  order, wrong suffix, wrong body-site form).
- **Cost:** one LLM call per concept.

Worth running alongside back-translation as a paired automated check.

### 5. SME spot-check (gold standard, doesn't scale)

Send N=100–200 random long-tail translations to a Korean medical
translator for review. Ratings on a clinically meaningful scale
(acceptable / partial / wrong).

- Not a per-experiment benchmark — too slow, too expensive.
- **The calibration standard:** if the automated metrics in (1)–(4) say
  "good" but the SME rates "bad," the automated metrics are broken.
- Should be run once after a major pipeline change (e.g. switching
  models, adopting a new resource) to confirm the automated signals
  still track real quality.

## Proposed two-tier architecture

| Tier | What runs | Cadence | Produces |
|---|---|---|---|
| Tier 1 — Automated | Synthetic long-tail (1) + consistency (2) + back-translation (3) + style-guide conformance (4) | Every experiment | Quantitative metrics, regression detection |
| Tier 2 — Human | SME spot-check (5) on 100–200 stratified samples | After major pipeline changes | Calibration, qualitative findings |

Tier 1 metrics are measured against each other for internal consistency
(e.g. if back-translation and synthetic long-tail disagree on which model
is better, something is wrong with one of them).

Tier 2 periodically checks that Tier 1 correlates with real quality.

## First experiment: synthetic long-tail runner

### What it does

A variant of `translate_imaging_ablation.py` that, at translation time
for each target concept, filters the Qdrant exemplar lookup to exclude:

- The concept's own exemplars (always).
- Optionally, concepts sharing any of: `Procedure site`, `Method`,
  `Finding site` attributes.

Runs against the same 3,693 eval concepts. Produces the same output CSV
shape (translation + ko_reference) so existing scoring / judging
machinery works unchanged.

### What it unlocks

- **Baseline long-tail quality**: how much does exemplar sparsity cost?
  Run with self-exclusion, compare exact-match to the current ~69%.
- **Gradient of difficulty**: same run at increasing exclusion levels
  (self only → self + site → self + method → self + site + method) maps
  the quality curve against retrieval weakness.
- **Re-testing parked resources**: run the synthetic long-tail with and
  without each of (KAA dictionary, editorial addendum, KARP, v4 style
  guide). The theory has always been these help when exemplars are weak
  — this is the first condition that can actually test it.

### Success criteria

A usable long-tail eval harness exists when:

- Tier 1 metrics can be computed end-to-end on a new model / pipeline
  change in under 30 minutes of wall-time.
- A regression in long-tail quality is visible in at least one Tier 1
  metric (synthetic-match / consistency / back-translation disagreement).
- The harness output is a single markdown report auto-generated from the
  CSVs, suitable for KHIS review.

### What's parked for later

- Tier 2 SME review — needs a Korean clinical reviewer; out of scope
  until we have one.
- Back-translation and style-guide LLM-judge — cheap to add, but worth
  getting the synthetic long-tail runner landed first so we have an
  anchor metric.
- Consistency metrics on real long-tail output — requires first running
  the translation across the ~55k long tail, which is a 6-minute job at
  the remote NVFP4 throughput but depends on pipeline stability.

## Open questions for later

- What counts as a "close neighbour" for exclusion? Same SCTID is
  trivial; same attribute target (site, method) is conservative; full
  hierarchy-distance is principled but expensive. Starting with SCTID
  self-exclusion.
- When the KR release next ships new translations, that's a free
  held-out eval. Worth wiring in a diff tool that re-scores our
  existing outputs against the new reference.
- Tier 2 SME review cadence — every major model change, every style
  guide revision, or only at project milestones. Depends on reviewer
  availability.
