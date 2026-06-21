# Imaging-resources ablation — findings (2026-04-20)

## TL;DR

Every extra resource we added — radiology editorial addendum, KAA anatomy
dictionary, KARP radiation glossary — **degrades translation quality against
the KR reference**. Baseline (style guide + BGE-M3 exemplar lookup only)
beats both alternative arms ~3:1 on the LLM-as-judge pairwise comparison and
by ~10 percentage points on exact-match.

The root cause is the same divergence that was flagged as a risk before the
experiment: the extras encode **prescriptive** standards (what the KHIS
editorial document, the KAA, and the KARP authorities say Korean medical
terminology *should* be), while the KR SNOMED release is **descriptive**
(what KHIS translators actually wrote). These two authorities disagree, and
when they disagree the extras drag the model away from the reference.

## Setup

- **Concept set**: 774 imaging-procedure concepts (intersection of
  `<<363679005 |Imaging (procedure)|` with the existing 3,693-concept
  procedure eval set).
- **Model**: gemma4-26b, temperature 0, concurrency 16.
- **Shared infrastructure**: same style guide (`style_guide_ko_v3.md`), same
  BGE-M3 exemplar lookup against the KR release, same decoding parameters.

**Arms**:

| Arm | Addendum | KAA | KARP |
|---|---|---|---|
| baseline | — | — | — |
| all_extras | ✓ | ✓ | ✓ |
| no_kaa | ✓ | — | ✓ |

## Results

### Exact-match rate against KR reference

| Arm | Exact matches | Rate |
|---|---|---|
| baseline | 599 / 774 | **77.4%** |
| all_extras | 525 / 774 | 67.8% |
| no_kaa | 541 / 774 | 69.9% |

On the 226 concepts where KAA fired (arm B), exact-match rates were:
baseline 77%, all_extras 57%, no_kaa 64%. So KAA-firing concepts are the
hardest hit, but KARP + addendum alone also cost ~13 pp.

### Pairwise LLM-judge (gemma4-26b, two-pass order-swapped)

Consistent two-pass verdicts only. "Inconsistent" = judge flipped between
orderings.

| Comparison | identical | judged | A wins | B wins | tie | inconsistent |
|---|---|---|---|---|---|---|
| baseline vs all_extras | 469 | 305 | **171 (75.0%)** | 56 (24.6%) | 1 | 77 |
| baseline vs no_kaa | 497 | 277 | **152 (74.1%)** | 51 (24.9%) | 2 | 72 |
| all_extras vs no_kaa | 689 | 85 | 19 (28.4%) | **47 (70.1%)** | 1 | 18 |

Reading the three rows together:

- **Baseline beats all_extras 3:1** — the extras-bundle is net-negative.
- **Baseline beats no_kaa 3:1** — dropping KAA is an improvement over
  all_extras but still worse than baseline. The addendum and/or KARP hurt
  on their own.
- **no_kaa beats all_extras 2.5:1** — KAA specifically is net-negative,
  confirming the KAA-vs-KR tension observed in the smoke test.

Inconsistency rates (25–28% of judged pairs) are high, which tempers the
confidence on individual close calls but not the directional conclusion.
Consistent-verdict margins are too large to be explained by judge noise.

## Why the extras hurt

Qualitative analysis of the 107 concepts where baseline was exact and
all_extras was not surfaced four recurring failure modes:

### 1. Modality spacing (biggest single regression)

Reference forms for CT / MRI:

| Form | KR reference count | baseline | all_extras | no_kaa |
|---|---|---|---|---|
| Spaced `컴퓨터 단층 촬영`, `자기 공명 영상` | 337 | 338 | 198 | 206 |
| Unspaced `컴퓨터단층촬영`, `자기공명영상` | 2 | 0 | 141 | 133 |

The KR release overwhelmingly uses **spaced** forms. The editorial addendum
(derived from `RadiologyEditorialGuide.md`) explicitly prescribes the
**unspaced** form. When the addendum is present the model reliably flips
140+ concepts to the wrong spacing.

### 2. Word-order reversal for contrast + site

Reference order: `[contrast] [site] [modality]` — e.g.
`조영제 미사용 뇌 컴퓨터 단층 촬영`.
Addendum's prescribed order: `[site] [contrast] [modality]` — e.g.
`뇌 조영제 미사용 컴퓨터단층촬영`.

The addendum wins the format tug-of-war against the exemplars and the model
emits the wrong order on dozens of CT-with-contrast concepts.

### 3. KAA body-site overrides

Where KAA's preferred term differs from KR's de facto preference:

| English | KR reference prefers | KAA injected |
|---|---|---|
| Kidney | 신장 | 콩팥 |
| Oral cavity | 구강 | 입안 |
| Colon | 결장 | 잘록창자 |
| Gastrointestinal tract | 위장관 | 위창자길 |
| Appendix | 충수 | 막창자꼬리 |

In each case the KAA reference successfully over-rode the (correct)
exemplar signal.

### 4. KARP token-matching misfires

KARP produces lexical matches that don't fit the compound-term conventions
of the KR release:

- `tomography → 단층촬영법` injected alongside CT compounds where the KR
  form uses `단층 촬영` (no `법`).
- `angiography → 혈관조영술` where the KR form is bare `혈관 조영` (no `술`).
- `localization → 국부화` where the KR form uses `국소`.
- `cavity → 공동` where the KR form uses `구강` for anatomical cavities.

### 5. "Preferred vs accepted synonym" framing

The addendum explicitly lists accepted synonyms alongside preferred forms
(e.g. `정맥 조영 (preferred) / 정맥 조영술 (accepted)`). The presence of both
in the prompt induces the model to pick the accepted synonym when the
exemplar table shows the preferred one, costing the match.

## The underlying pattern

All three resource types come from **prescriptive Korean medical-terminology
authorities** — the KHIS editorial guide, the Korean Association of
Anatomies, the Korean Association for Radiation Protection. They were
authored to standardise Korean medical language.

The **KR SNOMED release is descriptive**: it captures whatever translations
KHIS authors actually committed, which reflects pragmatic clinical use and
often diverges from the prescriptive standards.

When we translate *to match the KR release*, we are trying to replicate
descriptive reality, not prescriptive ideals. Injecting prescriptive
authorities as "ground truth" actively misleads the model whenever the two
disagree.

## Implications

### What to do with the current pipeline

**Disable the radiology addendum, KAA, and KARP for production imaging
translations.** The BGE-M3 exemplar lookup already carries the signal for
KR conventions; adding prescriptive overlays makes things worse, not
better.

This doesn't invalidate the effort of extracting these resources. They
remain useful as:

- **Style guide authoring references** — when writing the next version of
  `style_guide_ko_v3.md`, the editorial guide and KAA are still reasonable
  secondary sources. But their guidance must be validated against KR
  release data before being adopted as rules.
- **Fallback termbase for concepts the KR hasn't translated** — for the
  long tail where no exemplars exist, a prescriptive standard is better
  than nothing. The gating question becomes "is this concept in KR
  coverage?" rather than "is this an imaging concept?".

### The generalisable lesson for other hierarchies

Before building a prescriptive-source dictionary for any hierarchy
(finding, body structure, substance), run a small pilot: extract ~100
reference concepts, inject vs don't inject, pairwise judge. If the
prescriptive source and the national extension disagree on preferred
terms, injection will cost quality.

### Next step worth trying: KR-native body-site dictionary

Rebuild the body-site dictionary directly from the KR release (every body
structure concept that has a Korean preferred term in the KR extension
becomes a TSV row). This gives a lookup that matches KR conventions by
construction. Expected result: an arm using this dictionary instead of KAA
should at worst tie baseline, and may help on concepts where the exemplars
are weak.

That experiment is cheap to bolt onto the current pipeline — same runner,
same judge, different dictionary file.

## Reproducibility

All inputs and outputs under
`data/evals/korean/imaging_ablation/`:

- `imaging_eval_set.csv`, `imaging_attributes.json` — inputs.
- `translations_{baseline,all_extras,no_kaa}_gemma4-26b.csv` — per-arm outputs.
- `judgements_*.csv` — three pairwise judgement files.

Commands to reproduce:

```
python scripts/experiments/translate_imaging_ablation.py --arm-name baseline
python scripts/experiments/translate_imaging_ablation.py --arm-name all_extras --use-addendum --use-kaa --use-karp
python scripts/experiments/translate_imaging_ablation.py --arm-name no_kaa --use-addendum --use-karp

python scripts/experiments/judge_imaging_ablation.py --arm-a .../translations_baseline_gemma4-26b.csv --arm-b .../translations_all_extras_gemma4-26b.csv --output .../judgements_baseline_vs_all_extras.csv
python scripts/experiments/judge_imaging_ablation.py --arm-a .../translations_baseline_gemma4-26b.csv --arm-b .../translations_no_kaa_gemma4-26b.csv --output .../judgements_baseline_vs_no_kaa.csv
python scripts/experiments/judge_imaging_ablation.py --arm-a .../translations_all_extras_gemma4-26b.csv --arm-b .../translations_no_kaa_gemma4-26b.csv --output .../judgements_all_extras_vs_no_kaa.csv
```

Wall time end-to-end on gemma4-26b single-backend: ~7 minutes of
translation + ~3 minutes of judging.

---

## Follow-up: KR-native body-site dictionary (2026-04-20, same day)

Having established that **prescriptive** KAA hurts, the natural next
question was whether a **descriptive** body-site dictionary extracted
directly from the KR release would fix the regression.

### Build

[scripts/data_prep/build_kr_native_body_sites.py](../scripts/data_prep/build_kr_native_body_sites.py)
joins the KR release's Korean description file with its language refset
(`refsetId = 21000267104`, acceptability = preferred) and filters to
descendants of `<<123037004 |Body structure|` from the international
graph. Output: [data/korean/dictionaries/kr_body_sites.tsv](../data/korean/dictionaries/kr_body_sites.tsv)
(3,843 body-structure concepts with a Korean preferred term, same schema as
`kaa_anatomy.tsv` for drop-in replacement).

Same terms KAA got wrong for imaging are now right by construction:

| English | KR reference (ablation target) | KAA | KR-native dict |
|---|---|---|---|
| Kidney | 신장 | 콩팥 | **신장** |
| Colon | 결장 | 잘록창자 | **결장** |
| Appendix | 충수 | 막창자꼬리 | **충수** |
| Gastrointestinal tract | 위장관 | 위창자길 | **위장관** |

### Arm

**kr_site**: base style guide + exemplar lookup + KR-native body-site
injection (no addendum, no KARP). Used `--use-kaa --kaa kr_body_sites.tsv`
to reuse the runner unchanged.

Fire rate: KR-native dict fired on 478/774 concepts (62%), compared to
KAA's 226/774 (29%). Coverage roughly doubled because the KR-native dict
is keyed on real SNOMED body-structure FSNs (`Kidney structure`,
`Lumbar plexus structure`), while KAA keyed on shorter anatomy names that
miss many SNOMED concept labels.

### Results

Exact-match:

| Arm | Exact matches | Rate |
|---|---|---|
| baseline | 599 | **77.4%** |
| all_extras | 525 | 67.8% |
| no_kaa | 541 | 69.9% |
| **kr_site** | 589 | **76.1%** |

Pairwise judge (baseline vs kr_site):

| identical | judged | baseline wins | kr_site wins | tie | inconsistent |
|---|---|---|---|---|---|
| 694 | 80 | **43 (58.1%)** | 30 (40.5%) | 1 | 6 |

### Reading the result

The KR-native dict **eliminates the catastrophic regression** KAA caused:
76.1% vs 67.8% exact match, and the judge margin shrinks from 75% / 25%
against KAA-extras to 58% / 41% against baseline. So the prescriptive /
descriptive hypothesis is confirmed — using a KR-sourced reference dictionary
is nowhere near as harmful as a KAA-sourced one.

But the KR-native dict **does not beat baseline**. On exact-match they're
within noise (~1pp), and the pairwise judge still slightly favours baseline.

### Why injection still doesn't win

Inspecting the 62 diverging cases surfaces a second layer of
"descriptive reality": **the KR release is internally inconsistent**.
Different SNOMED concepts that reference the same anatomical site use
different Korean renderings. Examples where kr_site gave the KR-preferred
**body-structure** term but the reference **procedure** translation used
a different rendering of the same site:

| Concept | KR reference | KR-native dict said | Result |
|---|---|---|---|
| MRI of intestine | `장의 자기 공명 영상` | `Intestinal structure → 장` | Dropped `의`, lost match |
| Ultrasound of hip | `고관절 초음파 스캔` | `Hip joint structure → 엉덩관절` | Used pure form, lost match |
| Radiography of chest wall | `가슴벽 방사선 영상 촬영` | `Chest wall structure → 흉벽` | Used Sino form, lost match |
| Ultrasound of pleural cavity | `흉막강 초음파 검사` | `Pleural cavity structure → 가슴막안` | Used pure form, lost match |
| Automated ultrasound of entire breast | `자동 유방 초음파 검사` | `Entire breast → 유방 전체` | Added `전체`, lost match |

Conversely, 26 cases where kr_site **beat** baseline are exactly the ones
where the exemplars contained only weak or misleading neighbours and the
dict correctly filled the gap (`nasopharynx`, `lumbar plexus`,
`lumbar vertebroplasty`, `vessels`).

Net: ~26 dict-wins vs ~36 dict-losses, balanced by 694 identical. The dict
is roughly neutral on a pool where exemplars already provide good coverage.

### Conclusion reinforced

For the imaging eval set — where the KR release has already translated
most relevant concepts and the BGE-M3 exemplar lookup reliably surfaces
structurally-related neighbours — **prompt-time dictionary injection of
any body-site reference material adds noise without adding signal.** Even
a dictionary sourced from the KR release itself can't beat "just use the
exemplar table."

The finding likely changes for the long tail: concepts that have no close
neighbours in the exemplar Qdrant index (novel procedures, rare anatomy).
For those, a KR-native dictionary is a reasonable fallback because a weak
reference beats no reference. The gating condition for dictionary
injection should therefore be **exemplar quality / coverage**, not concept
hierarchy:

```
if top_exemplar_score < threshold AND body_site_in_kr_dict:
    inject kr_body_site_reference
```

Threshold tuning is a future experiment.

### Practical summary

- **Production recommendation unchanged**: run baseline (style guide +
  exemplars, no addenda, no dictionaries) for KR-covered imaging concepts.
- **Save the KR-native dictionary** (it's in
  `data/korean/dictionaries/kr_body_sites.tsv`); it's the right source to
  use *if* we ever find a use case where injection helps — most likely
  long-tail concepts.
- **The editorial addendum and KARP should be rebuilt or dropped.** Same
  prescriptive / descriptive logic: the addendum's modality-spacing rules
  and KARP's token mappings don't match what KHIS wrote in the release.
  A "KR-native modality patterns" equivalent could be mined from the KR
  release (e.g. extract the modality compound and spacing per concept in
  the imaging subhierarchy), but the same "exemplars already carry this"
  argument probably applies.

