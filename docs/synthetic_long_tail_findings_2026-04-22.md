# Synthetic long-tail simulation — findings (2026-04-22)

## TL;DR

**Every "baseline" exact-match number in this project so far is a measurement
artefact.** The BGE-M3 exemplar cache contains each eval concept's own
Korean translation at rank 1–2. The LLM copies it. When the self-hit is
removed from the retrieval pool — which is the condition every long-tail
concept would face — exact-match drops by 34–37 percentage points.

| Scope | Baseline (cache leaks reference) | Self-excluded (realistic) | Drop |
|---|---|---|---|
| **Imaging (774)** | **78.0%** | **44.1%** | **−34 pp** |
| **Full procedure (3,693)** | **71.3%** | **34.1%** | **−37 pp** |

The actual long-tail translation quality ceiling on this pipeline is
~**34–44% exact match**, not the 71–78% we've been reporting.

## Why the previous numbers were inflated

Qdrant is indexed from `all_bilingual_pairs.csv`, which contains — among
other sources — every KR-release preferred term and synonym. For any eval
concept, the BGE-M3 lookup returns the concept's own FSN→preferred-term
pair at or near the top of results. We cache the top-5 per concept and
inject them as a few-shot table into the user prompt:

```
Here are similar Korean SNOMED translations for reference:

|English|Korean|
|Echography of kidney (procedure)|신장 초음파 촬영|          ← synonym from this sctid
|Echography of kidney (procedure)|신장 초음파 검사|          ← ref: preferred term from this sctid
|Calculus of kidney              |신장의 결석   |
|Injury of kidney                |신장의 손상   |
|Electroencephalography          |...|

Translate this SNOMED CT procedure term from English to Korean.
English: Echography of kidney
Korean:
```

The first two rows are the target concept's own pairs — one is literally
the reference answer (`ko_reference`). The LLM has been given the exam
with the answer sheet attached. Exact-match stats were largely
"does the model copy row 2?"

On long-tail concepts (~55k procedures KR hasn't translated), that
answer sheet does not exist. Retrieval returns genuinely lateral concepts
("Electroencephalography" for "Echography of kidney") and the model has
to synthesise from style guide + neighbours. That's where the honest
~34–44% lives.

## Method

**Synthetic long-tail simulation**: at translation time, filter the
cached top-K pairs by resolving each pair's source SCTID (via a
pre-built FSN→SCTID reverse map from the SNOMED graph) and dropping
pairs that are "too close" to the target concept. Four exclusion
policies:

- **none** — no filtering (equivalent to the standard baseline).
- **self** — drop pairs from the target's own SCTID.
- **method** — self + drop pairs from any concept sharing the Method
  attribute (e.g. for a CT target, drop all CT concepts' pairs).
- **site+method** — union of shared Procedure site and Method.

Implemented in
[scripts/experiments/translate_synthetic_long_tail.py](../scripts/experiments/translate_synthetic_long_tail.py).

The filter uses only the existing cache — no Qdrant re-indexing. Pairs
whose source SCTID cannot be resolved (non-SNOMED entries like EDI /
KCD7 / LOINC) pass through unchanged, which is conservative but
realistic: those are genuine external-source exemplars a long-tail
concept would also see.

## Results

Remote gemma4-26b-NVFP4 via the user's vLLM, v3-abbreviated style guide,
concurrency 256. Each run is ~6–24s of wall-time.

### Imaging eval (n = 774)

| Exclusion | Exact | Rate | Avg pairs kept | Zero-pair concepts |
|---|---|---|---|---|
| none (baseline) | 604 | 78.0% | 5.00 | 0 |
| self | 341 | **44.1%** | 3.49 | 2 |
| site | 321 | 41.5% | 3.37 | 2 |
| method | 342 | 44.2% | 2.79 | 5 |
| site+method | 339 | 43.8% | 2.73 | 11 |

### Full procedure eval (n = 3,693)

| Exclusion | Exact | Rate | Avg pairs kept | Zero-pair concepts |
|---|---|---|---|---|
| none (baseline) | 2,633 | 71.3% | 5.00 | 0 |
| self | 1,258 | **34.1%** | 3.51 | 7 |
| method | 1,231 | 33.3% | 2.90 | 40 |
| site+method | 1,203 | 32.6% | 2.74 | 78 |

### Shape of the curve

- **Self-exclusion alone accounts for essentially all of the drop.**
  Going from `self` → `method` → `site+method` moves the metric by <2 pp.
  The self-hits are carrying the baseline. Neighbour concepts that
  *also* have KR translations don't leak the reference directly, so
  removing them has small incremental cost.
- **Imaging holds up slightly better than full procedure** at every
  exclusion level (44% vs 34%). Consistent with earlier findings:
  imaging has tighter conventions, more reliable structural patterns.
- **Zero-pair concepts grow quickly under method exclusion** — 40/3693
  on procedure/method, 78/3693 on site+method. Those are concepts the
  LLM translates with no exemplar signal at all (style guide + user
  prompt only).

## Implications for every prior result in this project

Re-reading each ablation with this in mind:

| Prior finding | Measured against | Still valid? |
|---|---|---|
| "Editorial addendum + KAA + KARP hurt baseline" (ablation A vs B, Apr 20) | Baseline leaked reference | Direction probably valid; magnitudes suspect. Re-run against self-excluded baseline to confirm. |
| "Style guide v4 loses to v3" | Leaky baseline | Same — direction likely valid, magnitude suspect. |
| "Qwen36b/122b lose to gemma4-26b" | Leaky baseline | The models were compared at the same leakage level, so the *relative* comparison is fair. But absolute exact-match numbers for all models are inflated. |
| "KR-native body-site dict ≈ baseline" | Leaky baseline | The ~78% baseline it was matching was inflated. The dict's real impact on long-tail conditions is untested. |
| "NVFP4 beats AWQ" | Leaky baseline | Relative comparison fair; both leaked equally. |

The headline pattern most experiments surfaced — **prescriptive extras
hurt when strong exemplars are available** — is directionally fine. But
the theory of the case has always been that dictionaries / addenda /
style rules would earn their keep when exemplars are weak. This now has
a controlled way to test. None of the previous ablations actually
stress-tested the weak-exemplar condition.

## What we should do now

### 1. Re-run the key ablations under self-exclusion

Specifically the ones most likely to flip direction:

- **KAA / KR-native body-site dictionary**: under self-exclusion the
  LLM no longer has the target's own body-site rendering in the pool,
  so an authoritative dictionary might actually help.
- **Editorial addendum**: likewise, in a zero-pair or low-pair state,
  explicit rules have more to contribute.
- **v4 style guide**: the empirical rules it added may not matter when
  exemplars carry the signal, but may matter when they don't.

Concrete experiment: take the 3,693 procedure eval, run at
`--exclusion self` with and without each resource. Anything that showed
a small loss against the leaky baseline might show a gain under
realistic conditions.

### 2. Extend Tier 1 with back-translation + consistency

Once we have a reliable self-excluded number, add the other
reference-free metrics from
[long_tail_evaluation_plan.md](long_tail_evaluation_plan.md):

- Back-translation similarity (KO → EN through a different model,
  embedding-match against source EN).
- Consistency: within groups of eval concepts sharing an attribute, how
  much does the shared element's rendering vary in the output?

Both give signals that don't depend on `ko_reference`, so they'd
generalise cleanly to the actual long-tail run over the untranslated
55k concepts.

### 3. Bump the cache to top-20 so filtering still leaves useful K

Currently the cache stores top-5 pairs per concept. After self-exclusion
2 of 5 are typically gone, leaving 3. After method exclusion we're down
to 1–2 or zero. Re-running `translate_korean_with_lookup.py
--prepare-lookups` with `--topn 20` would give the synthetic runner
headroom to keep K=5 after filtering even under aggressive exclusion.

### 4. Patch the retrieval pipeline to always self-exclude in production

For actually translating the long tail, there's no reason to return the
target's own pair in the exemplar pool — it wouldn't exist in the real
world. Filtering it out by default would make the production numbers
match real long-tail conditions and remove the "exam with answer sheet"
behaviour from production runs. Trivial one-line change at retrieval time
given the FSN→SCTID map we just built.

## Artefacts

- Runner: `scripts/experiments/translate_synthetic_long_tail.py`
- Attribute builder: `scripts/experiments/build_eval_attributes.py`
- FSN→SCTID cache: `data/cache/fsn_to_sctid.json`
- Procedure eval attributes: `data/evals/korean/synthetic_long_tail/procedure_attributes.json`
- Translation outputs: `data/evals/korean/synthetic_long_tail/translations_{imaging,procedure}_{none,self,site,method,site_method}.csv`
