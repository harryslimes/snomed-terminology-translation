# Style guide v4 vs v3 — ablation (2026-04-20)

## Question

Does encoding the empirical findings from the imaging ablation + procedure
inconsistency audit into the style guide (as v4) actually improve
translation quality on the 774 KR-imaging concepts?

## Arms

Both arms use the same pipeline: BGE-M3 exemplar lookup + style guide.
The only difference is which style-guide file is attached to the system
prompt.

- **v3**: [style_guide/style_guide_ko_v3.md](../style_guide/style_guide_ko_v3.md).
- **v4**: [style_guide/style_guide_ko_v4.md](../style_guide/style_guide_ko_v4.md).

Deltas v4 adds over v3:

- Explicit **contrast-first word-order rule** (new, 68:1 empirical basis).
- **Resolved** `절제` vs `절제술` open question — default bare (525:5).
- Per-method `-술` discipline with frequencies from Phase 2.
- Modality spacing strengthened (CT 100%, MRI 99% spaced).
- Updated worked example that used `충수 절제술` to bare `충수 절제`.
- Appendix / bone / upper-limb split status noted as resolved-but-tied.

## Results

### Exact-match rate against KR reference

| Arm | Exact matches | Rate |
|---|---|---|
| v3 (baseline) | 599 / 774 | **77.4%** |
| v4 | 594 / 774 | 76.7% |

### Pairwise LLM-judge (two-pass order-swapped)

| identical | judged | v3 wins | v4 wins | tie | inconsistent |
|---|---|---|---|---|---|
| 713 | 61 | **34 (56.7%)** | 26 (43.3%) | 0 | 1 |

v4 is **slightly worse** than v3 on both metrics. The margin is small but
consistent across exact-match and pairwise judge.

### Where v4 helped (22 cases)

The new rules did their job on specific regressions v3 had:

- **Contrast word order**: v3 sometimes produced site-first
  (`무릎 컴퓨터 단층 촬영 조영제 미사용`); v4's rule flipped these to
  contrast-first, matching the KR reference.
- **`-술` discipline**: v3 occasionally appended `-술` where the KR
  reference uses bare (`혈관 조영술` → `혈관 조영`). v4 dropped it.
- **Laterality preference**: v3 used `좌측 / 우측` (accepted synonym);
  v4 corrected to `왼쪽 / 오른쪽` (preferred in KR).

### Where v4 regressed (27 cases)

v4's rules also over-fired in cases the KR reference handles differently:

- **Dropped `의` particle too aggressively**: v3 preserved
  `골반과 고관절의 자기 공명 영상` (matches reference); v4 dropped the
  `의`. The style guide's "default no particle" bias got stronger.
- **Body-site forced toward canonical form**: where KR in fact uses both.
  v4 pushed `골반강` (Sino) where the reference uses `골반안` (pure) and
  `빗장밑 정맥` (pure) where the reference uses `쇄골하 정맥` (Sino). The
  style guide's canonical preference fights KR's actual per-concept
  variation.
- **Radiography form substitution**: v3 produced `유방 방사선 촬영`
  (matches reference for Mammography); v4 used the more formal
  `유방 방사선 영상 촬영` as dictated by the modality table, which
  doesn't match the reference here.
- **Laterality generalisation backfired**: for concepts where KR reference
  uses `양쪽 신장`, v4 sometimes wrote `양측 신장`.

## Interpretation

The net result is a slight regression (−0.7 pp exact match, 57% / 43% on
judge). The new rules that directly target observed errors (contrast
word-order, `-술` discipline, laterality) worked as intended. But v4 also
strengthened other rules in ways that pushed the model past what the KR
reference actually does — particularly on particle use and body-site
canonical selection.

This is the **third time** in this session we've seen the same pattern:
adding more explicit rules to the prompt hurts more than it helps for
KR-covered content, because **the BGE-M3 exemplar table already carries
the signal**. The exemplars encode the reference's choices per concept,
including its internal inconsistencies. Any rule we write is necessarily
a generalisation that will over-fire on concepts where the KR author
made a different choice.

## Conclusion for the project

- **Production pipeline**: keep v3 as the active style guide for KR-covered
  content. v4's content is correct about what KR *should* do but loses
  ground against what KR *did* do.
- **v4 is still valuable as documentation** for KHIS reviewers and new
  translators. The empirical frequencies and the contrast-first rule are
  real findings worth preserving. Just don't expect them to move the
  translation-quality needle above baseline.
- **Deliverable to KHIS**: extract the v4 additions as a separate
  `kr_curation_recommendations.md` document (canonicalisation list,
  typo fix, contrast word-order as a KHIS standard). That doc has
  real value even though injecting it into the prompt doesn't help.
- **Where does quality improvement come from?** Not from more rules. Three
  remaining candidates:
  1. **Better exemplar retrieval** (the parked investigation).
  2. **Long-tail evaluation** — concepts outside KR coverage, where rules
     may help because exemplars can't.
  3. **A different model** — gemma4-26b may be the ceiling; larger /
     differently-trained models might extract more from the same prompt.

## Files

- Translations: `data/evals/korean/imaging_ablation/translations_v4_gemma4-26b.csv`.
- Judgements: `data/evals/korean/imaging_ablation/judgements_v3_vs_v4.csv`.
- Style guide: [style_guide/style_guide_ko_v4.md](../style_guide/style_guide_ko_v4.md).
