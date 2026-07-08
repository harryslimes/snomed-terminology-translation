# EN→KO SNOMED Translation Guide (for a smaller model)

A rule-based cheat sheet distilled from 33 model critiques (A), 60 minimal pairs (B), 95 gold references (C), and 60 breadth pairs (D). Cite the guide back to yourself before you commit each translation.

---

## 1. Global word order (head-final slot template)

Fill this template left → right; omit empty slots; never reorder:

```
[Contrast] [Guidance] [Laterality] [Body site (+ region)] [Approach / target] [Action / Modality]
```

- **Contrast qualifier goes FIRST**, before the site. `조영제 사용` (with contrast) / `조영제 미사용` (without contrast). Do not park it at the end. (A7, A8, A10, A11, A22, A24; B "MRI of left breast with contrast → 조영제 사용 왼쪽 유방 자기 공명 영상"; C "MRI of left breast without contrast → 조영제 미사용 왼쪽 유방 자기 공명 영상")
- **Guidance goes next**, as `X 유도하` (X = modality). Precedes the site. (A17, A18, A30, A32; B "Biopsy of left breast using US guidance → 초음파 유도하 왼쪽 유방 생검", "Biopsy of left lung using CT guidance → 컴퓨터 단층 촬영 유도하 왼쪽 폐 생검")
- **Laterality (`왼쪽 / 오른쪽 / 양쪽`) immediately precedes the body site.** (B ~50 exemplars; C "양쪽 유방 초음파")
- **Action/modality closes the phrase.** Never let a temporal or contextual qualifier trail it. (A15: `부검` at end is wrong; correct is `사후 뇌 방사선 영상 촬영`)
- **Do not split the site with a modifier.** Keep multi-word sites intact: `발목 관절 컴퓨터 단층 관절조영술`, not `발목 [CT] 관절` (A20). Modifiers of the site precede the whole site: `표재 대퇴 정맥`, not `대퇴 정맥 표면` (A25).
- **When two procedures are combined (hybrid modality)**, put the *qualifier procedure* immediately before the *head procedure* it modifies (A9: `심근 관류 CT 병용 SPECT`, not `CT 동반 심근 관류 SPECT`).

---

## 2. Nominalisation — `-술` vs bare stem

Rule (from A1, A11, A14, A20, A22, A24, A26, A33; C):

- **Use bare stem** for productive site + action pairings: `절제`, `절개`, `재건`, `흡인`, `생검`, `배액`, `측정`, `이식`, `확장`, `조영`, `촬영`. (B "왼쪽 유방 절제", "오른쪽 유방 재건"; C "담낭 절개", "각막 이식", "폐 병변 흡인 생검")
- **Retain `-술`** for **fixed lexicalised compounds** that name a specific procedure:
  - `혈관 조영술` (angiography) (A11, A24, A26)
  - `관절 조영술` (arthrography) (A20, A22, A33)
  - `쇄석술` / `체외 충격파 쇄석술` (lithotripsy) (A1, A18)
  - `혈관 성형술` (angioplasty) (A14, A25)
  - `내시경술` (endoscopy) (C "복부 내시경술", "질확대경술")
  - `절제술` inside fixed lumpectomy-type compounds: `덩어리절제술`, `골연절제술`, `괴사딱지 절제술` (C)
  - `조영술` for named -graphy procedures: `정맥 조영술`, `내경동맥 조영술`, `저장성 십이지장 조영술` (A24; C)
- **Never `-상`** as the tail: `조영상` = the image, not the procedure. Use `조영` or `조영술` instead. (A4, A20, A21)

**⚠ Open question — flag to SME:** the -술 boundary is inconsistent in the gold data. `Angiography of pulmonary blood vessel → 폐 혈관 조영` (no -술, C) contradicts `Angiography of right femoral artery → 오른쪽 넓적다리 동맥 혈관 조영술` (with -술, C). Same for `혈관 조영` vs `혈관 조영술` in C. Default to `-술` for angiography/venography/arthrography per A11/A22/A24, and mark the output for review.

---

## 3. Sino-Korean vs pure-Korean vocabulary choice

- **Viscera / soft-tissue organs → Sino-Korean.** `담낭`, `신장`, `심근`, `대장`, `폐`, `자궁`, `식도`, `유방`, `전립샘` (A1, A6, A9, A12, A16, A18, A32; D)
- **Individual bones → pure Korean is preferred.** `엉덩뼈` (ilium), `목뼈` (cervical vertebra as bone), `등뼈`, `어깨뼈`, `넓적다리뼈`, `위팔뼈`, `빗장뼈`, `장딴지` (A5, A8; B MRI series)
- **Vertebral *column* / spinal *region* → Sino-Korean** (`경추 / 흉추 / 요추`) not mixed with bone names. Do not write `허리 척추` or `요 부위`; use `요추(부)`. Keep register **parallel across coordinated lists** — do not mix `목뼈` with `흉추` in the same enumeration. (A7, A8, A21)
- **Whole systems → Sino-Korean.** Skeletal system as a whole = `골격`, not `뼈대 계통`. (A27)
- **Whole limbs → Sino-Korean medical** `상지 / 하지`. Do **not** use `위팔` for "upper limb" (= humerus only) or `아래 다리` for "lower limb" (reads as lower leg). Pure-Korean `팔 / 다리` is acceptable and unambiguous; `아래 다리` is not. (A23, A30; B "Doppler US of vein of right lower limb → 오른쪽 하지 정맥 …")

**⚠ Open question — flag to SME:** register competition on
- **colon**: `결장` (B "Left colectomy → 왼쪽 결장 절제") vs `볼록 창자` (B "Laparoscopic-assisted left colectomy → 왼쪽 볼록 창자 절제"). Prefer `결장` in professional radiology/surgery contexts; flag when unsure.
- **femoral**: `넓적다리 동맥` (B, C) vs `대퇴 정맥` (A25 suggested). Both attested. Default to pure-Korean `넓적다리` for MSK imaging, `대퇴` for vascular/interventional.

---

## 4. Canonical modality / action lexicon

| English | Preferred Korean | Evidence |
|---|---|---|
| Magnetic resonance imaging (MRI) | `자기 공명 영상` (spaced) | A7, A8, B (~15) |
| Computed tomography (CT) | `컴퓨터 단층 촬영` (spaced) | A9, A10, A20, C |
| CT angiography | `컴퓨터 단층 혈관 조영술` (drop redundant `촬영`) | A10 |
| SPECT | `단일 광자 방출 컴퓨터 단층 촬영` (`방출`, **not** `방사`) | A12, A23 |
| Fluoroscopy (imaging) | `투시 검사` | A6 |
| Fluoroscopic guidance | `투시 유도하` (not `영상 유도하`, not `형광투시` unless fluorescence-imaging distinct) | A1, A18, A26 |
| Ultrasonography (procedure) | `초음파 검사` | A13, B (~14) |
| Doppler ultrasonography | `도플러 초음파 검사` (or `도플러 초음파` in short names) | B, C |
| Plain X-ray | `일반 X선 촬영` **or** `방사선 촬영`; do not write `방사선 영상 촬영` (redundant) | A5, A29, C |
| Cine (radiology) | `시네` / `시네 영상` (not `동영상`) | A2 |
| Radionuclide imaging | `방사성 핵종 영상` | A16 |
| Angiography | `혈관 조영술` | A11, A14, A26; C |
| Venography | `정맥 조영술` (do **not** substitute `혈관 조영술`) | A24 |
| Arthrography | `관절 조영술` | A20, A22, A33 |
| Myelography | `척수 조영` (+ `술` when standalone) | A21 |
| Lithotripsy (ESWL) | `체외 충격파 쇄석술` | A1, A18 |
| Angioplasty | `혈관 성형술` | A14, A25 |
| Biopsy | `생검` (bare); FNA = `세침 흡인 생검` | A17, A30, A32; C |
| Percutaneous | `경피적` (not `피부 경유`) | A14, A32 |
| Transluminal | `경관` / `경관강` (not `혈관 경유`) | A14 |
| Transapical | `경심첨` | A19 |
| Transoesophageal echo | `경식도 심초음파` (keep `심`) | A19 |
| Stereotactic | `정위적` | A31 |
| Postmortem (qualifier) | `사후` (not `부검`, which = autopsy) | A15 |
| "Superficial" (anatomical) | `표재` (not `표면`) | A25 |
| "with" (combined modality) | `병용` (formal); `및` acceptable in gold (A23) | A9, A23 |
| "with" (accompanying feature, e.g. stent) | `동반` after the site cluster | A28 |
| Destruction (radiosurgery) | `파괴` (not `소작`, which = cautery) | A31 |
| Cephalometric | must include `계측` | A29 |

**⚠ Open question — FNA phrasing:** A17 mandates `세침 흡인 생검`; but C has `Fine needle aspiration biopsy of ear → 귀의 가는 바늘 흡인 생검`. Prefer `세침 흡인 생검` for formal terminology; flag the ear entry as legacy.

---

## 5. Scope preservation (do not add, drop, or narrow)

- **Do not add un-sourced targets.** "Lithotripsy of gall bladder" ≠ "gall bladder stone lithotripsy" — do not insert `결석`. (A1)
- **Do not narrow the site.** `여성 생식기` ≠ `자궁` (A3); "cerebral vein" ≠ `뇌혈관` general (A24); "intracranial vessel" ≠ `뇌혈관` (A13); "upper limb bone" ≠ `위팔뼈` (A23); "lower limb" ≠ `아래 다리` (A30); "apophyseal joint" = `관절돌기관절` not generic `뼈돌기` (A4).
- **Do not broaden the modality.** "Fluoroscopic guidance" ≠ `영상 유도하` (A18). "Venography" ≠ `혈관 조영` (A24). "Cephalogram" needs `계측` (A29). "Gamma-ray destruction" needs `정위적` (A31).
- **Do not drop clinically critical qualifiers**: contrast (A22), stereotactic (A31), radiographic (A27), postmortem (A15), cephalometric (A29), "into the ring / valve-in-ring" (A19).
- **Do not translate paraphrastically** where a fixed Sino-Korean compound exists (see §4: `세침`, `경피적`, `경관`, `표재`).

---

## 6. Particles, spacing, and punctuation

- **Drop the genitive particle `의`** between body site and action in procedure names. Write `유방 생검`, not `유방의 생검`. (A17)
  - **⚠ Open question:** gold data still uses `의` in many entries: `직장의 고위 전방 절제`, `척추의 피로 골절`, `담관의 누공`, `오른쪽 손목의 일반 X선 촬영` (C, D). Rule of thumb: drop `의` when the site directly modifies the action head; keep it when the site owns a **lesion / substructure / finding** (`폐 병변`? bare; `담관의 누공`? with `의`). Flag borderline cases.
- **Space multi-morpheme modality names**: `자기 공명 영상`, `컴퓨터 단층 촬영`, `혈관 조영술`, `체외 충격파 쇄석술`. (A7, A10, A18)
- **Never concatenate near-synonyms.** `방사선 영상 촬영` = redundant → use `방사선 촬영`. `컴퓨터 단층 촬영 혈관 조영술` = redundant → `컴퓨터 단층 혈관 조영술`. `엉덩관절 투시 관절 조영` = doubled `관절` → `엉덩관절 투시 조영술`. (A5, A10, A33)
- **Coordinated lists**: `A, B 및 C` (comma + final `및`), not `A 및 B 및 C`. (A10)
- **Do not use hyphens** as separators between Korean segments. (A3)

---

## 7. Feature-specific micro-rules

- **Laterality** always renders as `왼쪽 / 오른쪽 / 양쪽` (native), placed immediately before the site. (B ~50 pairs) Do **not** substitute Sino-Korean `좌 / 우` unless copying a fixed compound; note however D has `우측 하지` — acceptable in *finding/disorder* text, less standard in *procedure* text.
- **With / without contrast**: `조영제 사용` / `조영제 미사용` — always at the head of the phrase. (A7, A8, A22; B, C)
- **Guidance vs modality**: same imaging modality is `X 검사` when it's the primary study, `X 유도하` when it guides another procedure. Do not conflate. (A13 vs B)
- **Combined SPECT/CT and similar hybrids**: put the *secondary* modality (with `병용` or `및`) between the physiologic target and the primary modality head. (A9, A12, A23)

---

## 8. Non-procedure content (findings, disorders, substances, body structures)

From D:
- **Substances (drugs, chemicals)**: transliterate in Korean orthography (`이미페넴`, `설파다이아진`, `사이클로포스퍼마이드`). Enzymes → descriptive Sino-Korean (`카복실에스터분해효소`).
- **Disorders**: `[site] [pathology]` with optional `의`. `전립샘 샛길`, `담관의 누공`, `척추의 피로 골절`, `입천장의 표재 손상`.
- **Neoplasm patterns**:
  - "Primary malignant neoplasm of X" → `X의 원발성 악성 신생물`
  - "Metastatic malignant neoplasm to X" → `X의 이차성/전이성 악성 신생물` (both attested — flag)
  - "Benign neoplasm of X" → `X의 양성 신생물`
- **History/family history** patterns: `X 과거력`, `X 가족력` (D).
- **Body structures**: usually a single Sino-Korean or pure-Korean noun (`소뇌`, `코 안`, `목구멍편도`, `전정틈새`).

---

## 9. Self-check checklist (run BEFORE emitting the answer)

1. **Slot order OK?** `[Contrast] [Guidance] [Laterality] [Site] [Approach] [Action/Modality]` — action is last?
2. **Contrast qualifier at the very front?** Not stranded at the tail?
3. **Site register consistent?** No `목뼈 + 흉추` mixed. Whole-limb → `상지/하지`, whole system → Sino-Korean.
4. **Modality canonical?** MRI/CT/SPECT/US/angiography spellings match §4 table?
5. **`-술` decision made deliberately?** Bare stem for productive verb-nouns; `-술` for fixed compounds (angiography, arthrography, lithotripsy, angioplasty). No `-상`.
6. **Scope preserved?** No added `결석`, no narrowed sites, no dropped `정위적/조영제/사후/계측`, no swapping `방출`↔`방사`, `표재`↔`표면`, `경피적`↔`피부 경유`, `투시`↔`영상`.
7. **No redundancy?** Not doubling `관절`, `영상 + 촬영`, `CT 촬영 + 혈관 조영술`.
8. **No stray `의`** between site and action (unless the site owns a lesion/substructure).
9. **No hyphens; correct spacing** in multi-morpheme modality names.
10. **Laterality present iff present in source** — never invent, never drop.
11. **When gold-data conflicts** touched (colon, femoral, FNA, `조영` vs `조영술`), pick the §4 default and mark the item for SME review rather than silently guessing.