# KHIS clinician feedback — findings and improvement plan

**Date:** 2026-05-18
**Branch:** `feature/qwen122b-translation-pipeline`
**Source feedback file:** [data/analysis/clinician_feedback/RadiologyTranslation.xlsx](../data/analysis/clinician_feedback/RadiologyTranslation.xlsx)
**Original packet:** [data/sme_review/2026-04-24/](../data/sme_review/2026-04-24/) (translations produced by `gemma4-26b` AWQ-4bit + `style_guide_ko_v3_abbr.md` + BGE-M3 RAG)

---

## 1. What the clinicians said

100 long-tail radiology terms, no KR-extension reference (these are concepts not in the official Korean SNOMED extension):

| SME rating  | Count |
|-------------|-------|
| ACCEPTABLE  | 47    |
| PARTIAL     | 51    |
| WRONG       | 2     |

61 rows carry an SME-corrected Korean translation; 50 rows carry explanatory notes (mostly bilingual glossary fragments).

### Where errors concentrate

By modality:

| Modality                     | Acc | Part | Wrong |
|------------------------------|-----|------|-------|
| Radiographic imaging         | 1   | 10   | 2     |
| Magnetic resonance imaging   | 6   | 11   | 0     |
| Fluoroscopic imaging         | 6   | 6    | 0     |
| Computed tomography          | 14  | 6    | 0     |
| Ultrasound imaging           | 8   | 2    | 0     |

Ultrasound and CT are mostly fine; radiographic/MR/fluoroscopy concentrate the defects.

### Recurring defect patterns

1. **Spacing inside fixed compound terms.** The MT inserts spaces inside Korean medical compounds that are conventionally written solid:
   - `자기 공명 영상` → `자기공명영상` (MRI)
   - `컴퓨터 단층 촬영` → `컴퓨터단층촬영` (CT)
   - `관절 조영` → `관절조영(술)`, `정맥 조영` → `정맥조영술`

   This alone drives a large share of PARTIAL ratings.

2. **Body-site lexical preference.** SMEs consistently prefer native Korean anatomical names over Sino-Korean compounds:

   | English          | MT (rejected)     | SME (preferred) |
   |------------------|-------------------|-----------------|
   | upper limb       | 상지 / 위팔       | 팔              |
   | lower limb       | 하지 / 아래 다리  | 다리            |
   | bone of upper limb | 위팔 뼈         | 팔뼈            |
   | lumbar region    | 요 부위           | 허리부위        |
   | retroperitoneal  | 복막뒤            | 후복막          |
   | brachial plexus  | 신경총            | 신경얼기        |
   | pelvic organs    | 골반기관          | 골반장기        |

   MT also occasionally **adds** an extra body-site word (`귓바퀴 외이도` for "external auditory meatus" — `귓바퀴` is wrong).

3. **`-graphy / -gram` suffix handling.** MT drops `술`/`상` or paraphrases the noun form:
   - arthrography → `관절조영술`
   - venography → `정맥조영술`
   - myelogram → `척수조영상`
   - mammogram → `유방영상` (not `유방 촬영`)
   - herniogram → `탈장 조영술` / `헤르니오그램` (MT produced the meaningless `허니오그램`)

4. **Contrast-modifier ordering.** SME convention places `조영제 사용 / 조영제 미사용` at the **front** of the term; MT often puts it at the end or omits the "without" form entirely.

5. **Semantic misses (the two WRONG):**
   - "Mammogram – symptomatic": MT translated `symptomatic` as `증상치료` (symptom-*treatment*). Correct reading is `진단 유방영상` (= diagnostic mammogram).
   - "Herniogram" → transliteration was malformed (`허니오그램`).

6. **Word-order in long noun phrases** (e.g. the transapical mitral valve concept) — MT reorders complex multi-modifier procedures awkwardly even when each lexical piece is right.

---

## 2. How we evaluate today, and how to extend it for this dataset

### Current setup

[scripts/evaluation/eval_translations.py](../scripts/evaluation/eval_translations.py) is the current automated harness. It treats the **Korean SNOMED extension (KR1000267)** as the golden source: each reference row carries a list of accepted Korean strings (`ee_all` column, pipe-separated), and per term it computes:

- `chrF` against the best-matching reference
- BGE-M3 dense cosine similarity against the best-matching reference
- Exact match (case-insensitive)
- Composite: `0.5 * chrF/100 + 0.3 * cosine + 0.2 * exact`

In parallel, [scripts/evaluation/judge_korean_sonnet.py](../scripts/evaluation/judge_korean_sonnet.py) runs Sonnet 4.6 as an LLM-as-judge over the same CSV shape (`sctid, preferred_term, ko_reference, translation`) and emits an `ACCEPTABLE / PARTIAL / WRONG` label plus reasoning. Sonnet 4.6 is the current "gold standard surrogate" we point at runs where no KR-extension reference exists.

### The hook for the KHIS dataset

These 100 KHIS-reviewed terms have **no KR-extension reference** (that's why we sent them for SME review). The cheapest, least-divergent path is to treat the SME-corrected column as the reference and feed both evaluators the same CSV:

1. Build a one-off reference CSV from the xlsx with columns that exactly match what `eval_translations.py` expects:

   ```
   sctid, preferred_term, hierarchy, ee_reference, ee_all
   ```

   Map `english_term → preferred_term`; `sme_corrected_translation_ko` → `ee_reference` and `ee_all` (if the corrected column is empty, fall back to `machine_translation_ko` since the SME rated it acceptable). Tag every row with `hierarchy = "Procedure (KHIS-SME-radiology)"`. Land it at `data/evals/korean/khis_sme_radiology_100.csv`.

2. Build a translations CSV in the standard `sctid, translation` shape from any pipeline run we want to score. The original packet's run is already in [data/sme_review/2026-04-24/translations_sme_pool.csv](../data/sme_review/2026-04-24/translations_sme_pool.csv) (column rename only).

3. Run both evaluators **unchanged**:

   ```bash
   python scripts/evaluation/eval_translations.py \
     --translations data/sme_review/2026-04-24/translations_sme_pool.csv \
     --reference   data/evals/korean/khis_sme_radiology_100.csv \
     --output      data/evals/korean/khis_eval_gemma4-26b_2026-04-24.csv

   python scripts/evaluation/judge_korean_sonnet.py \
     --translations data/sme_review/2026-04-24/translations_sme_pool.csv \
     --output       data/evals/korean/khis_sonnet_gemma4-26b_2026-04-24.csv
   ```

   Nothing in either script needs to change — they're already reference-agnostic with respect to where the reference came from.

Caveat to record in the eval doc: the SME-corrected column is a **single accepted form**, not a list of synonyms. Multiple-reference scoring (`ee_all`) will therefore behave like single-reference scoring, which depresses chrF compared to KR-extension scoring where 5–10 synonyms are typical.

### Watch for exemplar leakage

The SME packet was sampled from concepts not in the KR extension. Make sure the BGE-M3 exemplar index used during translation does **not** include any of these 100 SCTIDs as exemplars (see the [BGE-M3 cache-leakage finding](../memory/) — prior baseline exact-match was ~35 pp inflated when the eval set leaked into the retriever pool). The same hygiene applies to any future eval cut against this 100.

---

## 3. Sonnet judge vs Korean clinician judgement

The SMEs rated the **exact same 100 machine translations** that Sonnet judged in `sonnet_review_100.csv`. Joining on SCTID gives 98 rows (2 dropped for missing data). MT strings were verified identical on all 98 — so this is a clean head-to-head between Sonnet and the clinicians.

### Confusion matrix (rows = SME, cols = Sonnet)

| SME ↓ \ Sonnet → | ACCEPTABLE | PARTIAL | WRONG | Total |
|------------------|------------|---------|-------|-------|
| ACCEPTABLE       | 26         | 21      | 0     | 47    |
| PARTIAL          | 4          | 43      | 2     | 49    |
| WRONG            | 0          | 0       | 2     | 2     |
| **Total**        | 30         | 64      | 4     | 98    |

- **Raw 3-class agreement:** 71 / 98 = **72.4%**
- **Cohen's κ (3-class):** **0.476** — "moderate" agreement
- **Binary (ACCEPTABLE vs needs-fix):** 74.5% agreement, κ = **0.482**

### Direction of disagreement

Of the 27 disagreements:

| Pattern                       | Count |
|-------------------------------|-------|
| SME ACCEPTABLE → Sonnet PARTIAL | 21 |
| SME PARTIAL → Sonnet ACCEPTABLE | 4  |
| SME PARTIAL → Sonnet WRONG      | 2  |
| SME WRONG → Sonnet *             | 0 (Sonnet caught both)  |

**Sonnet is systematically harsher than the SMEs.** It flags 21 SME-accepted translations as PARTIAL — almost entirely because Sonnet penalises the spacing/Sino-Korean stylistic choices that the SMEs personally don't love but accept as valid (see the row-1 reasoning in `sonnet_review_100.csv`: Sonnet flagged missing `조영제 없는`, suffix `조영` vs `조영술`, etc. — exactly the patterns SMEs called PARTIAL when they cared and ACCEPTABLE when they didn't).

### Practical reading

- As a **screen** for "needs fixing", Sonnet has high recall: it caught both WRONG cases and flagged 47 / 51 SME-PARTIALs as not-acceptable. False-negative rate vs SME is 4 / 51 = 8%.
- As an **estimate of overall quality**, Sonnet is biased ~20 pp pessimistic on the ACCEPTABLE rate (30% vs 48% SME). When we report a Sonnet ACCEPTABLE fraction in ablations, add a "Sonnet is conservative — KHIS SMEs accept ~17 pp more" footnote.
- **Calibration action:** consider a Sonnet prompt rev that explicitly downweights spacing-only and synonym-only deviations to ACCEPTABLE. The current prompt already says spacing is OK, but Sonnet still cites it in PARTIAL reasoning — the instruction isn't sticking. Worth a v2.

### What this means for using Sonnet to drive ablations

We have prior ablations whose only signal was Sonnet. Given κ ≈ 0.48 vs the clinicians, the **direction** of small Sonnet-only deltas is suspect at the ±5 pp level. Large deltas (10+ pp) are likely real; sub-5 pp deltas need a SME sanity-check before being treated as moves.

---

## 4. Does gemma4-26b reproduce the SME-packet translations today?

**Re-ran 2026-05-18.** Two runs against the live `snomed-gemma4` vLLM container (`cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit`, `temperature=0`, `style_guide_ko_v3_abbr.md`, concurrency 16, identical script and prompt template):

| Run                       | Lookup cache (RAG exemplars)         | Bit-exact vs original | Ignoring spaces |
|---------------------------|--------------------------------------|-----------------------|-----------------|
| Re-run, **packet cache**  | `data/sme_review/2026-04-24/lookup_cache.json` (5796 entries) | **68 / 100** | **72 / 100** |
| Re-run, **current cache** | `data/evals/korean/lookup_cache.json` (3793 entries)          | 23 / 100     | 24 / 100     |

Same model, two re-runs against the two different caches: only **27 / 100** identical to each other → the exemplar pool drives ~73% of output variation.

Conclusion:

- **The BGE-M3 exemplar index is the dominant source of drift.** It has changed since 2026-04-24 (5796 → 3793 entries; collection rebuilt or filtered). With the original cache restored, the model reproduces 68% of outputs bit-for-bit.
- **The remaining 32% non-determinism is the model itself** — temp=0 in vLLM is not strictly deterministic for this AWQ MoE under concurrent batching. The diffs are typically small (single-token substitutions, swap of synonymous body-site terms), not semantic drift. Examples from the diff:
  - `위팔 정맥 조영` ↔ `위팔 혈관 조영` (vein → vessel)
  - `상지 자기 공명 관절 조영` ↔ `위팔 자기 공명 관절 조영` (Sino-Korean → native body site — incidentally matches what SMEs prefer)
  - `복강 신경얼기 차단` ↔ `복강 신경총 차단` (native ↔ Sino-Korean — flips between runs).
- **Net effect against the SME ground truth:** the re-run is *not* an improvement — it matches the SME-accepted form on 33/98 rows vs the original packet's 39/98. Variation is noise, not signal.

### Run-to-run variance — 8× back-to-back with identical config

To isolate pure model non-determinism from any other moving part, I ran the same script 8 times in immediate succession (packet-time exemplar cache, `style_guide_ko_v3_abbr.md`, temp=0, concurrency=16, same container, ~6 s per pass).

- **Fully stable across all 8 runs:** **76 / 100** terms produce the exact same string every time.
- **Distinct outputs per term:** 76 terms = 1 output, 22 terms = 2 outputs, 2 terms = 3 outputs.
- **Mean pairwise bit-exact agreement:** 90.2 / 100 (std 2.4, range 87–96 across the 28 run-pairs).
- **Mean pairwise agreement ignoring spaces:** 91.1 / 100.
- **Terms with a clear majority** (≥5/8 votes for one answer): **95 / 100** — majority voting converges fast.

Variants are uniformly small — synonym swaps (`요 부위` ↔ `요부`, `오금窩` ↔ `오금와`), word-boundary shifts (`아래다리` ↔ `아래 다리`), `-술` suffix presence/absence. Two pathological rows degenerate badly (the long transapical mitral valve term emits unfinished English in 1 of 8 runs) — these are edge cases worth catching with an output validator.

### Implications for evaluation

1. **Single-run results on the 100-row set have a ~±3 pp noise floor** on exact-match-like metrics. Any ablation delta below ~5 pp is in the noise.
2. **Always report mean ± std across ≥3 runs** on this eval set, or use majority-vote decoding (self-consistency, N=5) before scoring. Cost is trivial — ~6 s per pass against the local container.
3. The 8-run variance (24% unstable) is *larger* than the apparent drift between the packet and today's re-run with packet-time cache (32% bit-non-identical). So **most of the "drift since 2026-04-24" is just normal run-to-run noise**, not real index/model regression. The exemplar-pool rebuild (current cache, 23% bit-exact) is still a real and large effect *on top of* that noise floor.
4. For the 100-term regression harness in §5, lock in: (a) the exemplar-cache snapshot, (b) N=5 self-consistency or N=3 independent runs reported as mean±std.

**Implication for the work plan:** Treat the 2026-04-24 packet translations as a **frozen historical snapshot**, not a current baseline. Before any ablation claims an improvement, re-translate the 100 SCTIDs *now* under the new exemplar pool and use that as the comparison baseline — comparing a new run against the packet would attribute exemplar-index drift to whichever change is being tested. We should also pin the exemplar cache used for the 100-row regression set so it doesn't drift again silently.

A few process notes for the next time we want bit-exact reproducibility:

- Pin the exemplar cache. The script reads from the hardcoded `data/evals/korean/lookup_cache.json` path; whatever lives there at run time becomes part of the result. Either snapshot it alongside each ablation run, or refactor the script to take `--lookup-cache` so the path is explicit in the command line.
- The job config in [configs/models.json](../configs/models.json) (`translate_korean_lookup`) is already `temperature=0`, `max_tokens=128`, `stop=["\n\n", "English:"]`. That part has not drifted.
- The `snomed-gemma4` container has been up for 3 weeks; it has not been restarted between the packet and this re-run, so weights/quant are identical.

### Exact commands used (for the record)

```bash
# Re-run with current exemplar pool (drifted index)
INPUT_CSV=/tmp/sample_100_with_ref.csv \
OUTPUT_TAG=gemma4-26b-rerun-2026-05-18 \
  python scripts/translation/translate_korean_with_lookup.py \
  --style-guide style_guide/style_guide_ko_v3_abbr.md

# Re-run with packet-time exemplar pool (swap cache then restore)
cp data/sme_review/2026-04-24/lookup_cache.json data/evals/korean/lookup_cache.json
INPUT_CSV=/tmp/sample_100_with_ref.csv \
OUTPUT_TAG=gemma4-26b-rerun-pkt-cache \
  python scripts/translation/translate_korean_with_lookup.py \
  --style-guide style_guide/style_guide_ko_v3_abbr.md
```

Outputs:
- [data/evals/korean/translations_gemma4-26b-rerun-2026-05-18_lookup.csv](../data/evals/korean/translations_gemma4-26b-rerun-2026-05-18_lookup.csv)
- [data/evals/korean/translations_gemma4-26b-rerun-pkt-cache_lookup.csv](../data/evals/korean/translations_gemma4-26b-rerun-pkt-cache_lookup.csv)

---

## 5. Plan to use the feedback to improve the pipeline

The 100-row dataset is now our highest-signal asset. Five complementary uses, in priority order:

### P0 — Curate a structured lexicon from the SME notes

Most `sme_notes` cells are already in `English = Korean` form. Extract them into a maintained glossary at `style_guide/glossaries/radiology_ko.yaml`:

```yaml
- en: magnetic resonance imaging
  ko: 자기공명영상
  abbr: MRI
  source: KHIS-SME-2026-05
- en: upper limb
  ko: 팔
  alt: [상지]
- en: arthrography
  ko: 관절조영술
```

Then:
- Inject the matching glossary subset into the translation prompt as a **mandatory** term-substitution table (RAG over the glossary keyed on the English source). Add this to [scripts/data_prep/extract_dictionaries.py](../scripts/data_prep/extract_dictionaries.py) or a sibling extractor.
- Post-translation, run a validator that flags any output missing the canonical Korean form when the English term hits the glossary.

**Expected uplift:** addresses the bulk of PARTIAL ratings (spacing, body-site, `-graphy` suffix).

### P0 — Promote the corrections into the style guide (v5)

Extend [style_guide/style_guide_ko_v4.md](../style_guide/style_guide_ko_v4.md) with descriptive rules derived from the SME pattern (per the [prescriptive-vs-descriptive finding](../memory/), do not import prescriptive authority text wholesale):

- "Do not insert spaces inside the fixed compounds: `자기공명영상`, `컴퓨터단층촬영`, `단일광자단층촬영`, `관절조영술`, `정맥조영술`, `척수조영상`."
- "Translate *with/without contrast* as `조영제 사용` / `조영제 미사용`. Place this phrase at the **start** of the term."
- "Prefer native body-site terms (`팔`, `다리`, `허리`) over Sino-Korean (`상지`, `하지`, `요부`) unless the SNOMED body-site axis explicitly uses the Sino-Korean form."
- "`-graphy` → `조영술`; `-gram` (as imaging product) → `조영상`. Special case: `mammogram` → `유방영상`."
- "`symptomatic [study]` in radiology = `진단 [study]`, never `증상치료`."

### P1 — Use the 100 rows as a fixed eval set

Treat `sme_corrected_translation_ko` as ground truth (per §2 above). Add a regression script at `scripts/evaluation/eval_khis_radiology_100.py` that wraps `eval_translations.py` + `judge_korean_sonnet.py` with the right input/reference paths, and emits a one-line summary suitable for inclusion in every ablation doc. Keep results in `docs/khis_radiology_100_baseline_2026-05-18.md`.

Eval hygiene: confirm none of the 100 SCTIDs are in the BGE-M3 exemplar pool used by the translator (cache-leakage risk).

### P1 — Use corrected pairs as few-shot exemplars

Add the 61 `(english_term, sme_corrected_translation_ko)` pairs to the Qdrant exemplar pool used by the RAG translator, **tagged** `source = KHIS-SME-verified` so retrieval ranking can prefer them over synthetic or self-generated exemplars. This gives the model concrete in-context examples for spacing, ordering, and `-graphy` suffixes without a model change.

### P1 — Recalibrate the Sonnet judge prompt

Given the 17 pp pessimism (§3), iterate on `JUDGE_SYSTEM` in `judge_korean_sonnet.py` to be more explicit that:
- pure spacing differences inside compound terms are ACCEPTABLE,
- native vs Sino-Korean body-site variants of the same concept are ACCEPTABLE,
- contrast-modifier position is a style preference, not a correctness issue,
- only score PARTIAL when a clinically meaningful modifier is missing/wrong.

Re-run the calibrated judge on the same 98 rows and recompute κ against SME. Target κ ≥ 0.65.

### P2 — Preference data for DPO/LoRA on the translation model

With 53 PARTIAL+WRONG rows we have 53 `(chosen = sme_corrected, rejected = mt)` preference pairs. Too small for SFT alone, but enough to:
- Run a small LoRA-DPO step on the local gemma4-26b checkpoint.
- Hold out a 20-row slice as a never-seen test.
- Compare against P0 glossary-only baseline; if DPO is <5 pp better than glossary alone, the complexity isn't worth it yet — wait for a bigger SME batch.

### Sequencing

1. **Reproduce the baseline** (§4 verification) — ~½ day.
2. **Build glossary + style guide v5 + 100-term regression harness** — 1 day.
3. **Wire SME pairs into the exemplar pool** — ½ day. Re-run baseline; report delta.
4. **Recalibrate Sonnet judge prompt** — ½ day. Re-run κ vs SME.
5. **Request a second SME batch from KHIS** — 300–500 terms, biased toward Radiographic imaging and complex multi-modifier procedures where errors cluster. Needed before DPO or before declaring any of the above "validated".
