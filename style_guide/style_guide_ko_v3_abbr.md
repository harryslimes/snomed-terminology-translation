# Korean SNOMED CT translation style guide (v3, abbreviated)

> Trimmed version of `style_guide_ko_v3.md` for deployments with an 8k
> context budget. Meta sections (stubs, provenance, open questions,
> recommended sources) are stripped. All normative rules, tables, and
> worked examples are preserved.

---

# general

**Term length.** Maximum 255 characters, matching SNOMED CT specification.

**Script and case.** Korean terms are written in Hangul (한글). Latin
characters inside a Korean term (gene symbols, drug names, chemical
formulae, eponyms) preserve the case used in the source.

**Spacing (띄어쓰기).** Korean terms in the KR extension are predominantly
**space-separated by word unit**:

- `컴퓨터 단층 촬영` (Computed tomography), not `컴퓨터단층촬영`
- `자기 공명 영상` (Magnetic resonance imaging)
- `부분 위 절제` (Partial gastrectomy)

Well-established medical compounds and short procedural nouns are written
without spaces:

- `절제술`, `내시경술`, `생검`, `측정` — never internally spaced.
- `복강경`, `흡인`, `봉합`, `연결`.

**Rule of thumb:** Default to space-separated word units. Do not insert
spaces inside fixed nominalisations ending in `-술`, `-법`, `-검`,
`-증`, `-염`.

**Punctuation.** UTF-8 encoding. Korean terms generally do **not** end in
punctuation. Commas are rare and used only in list-like constructions.
Hyphens are preserved inside hyphenated foreign names (`Lloyd-Davies`,
`M-mode`, `25-OH`).

**Numbers.** Arabic numerals throughout.

**Abbreviations and Latin loan words.** The KR extension keeps a small
consistent set of items in Latin script:

- **Eponymous procedures** keep the surgeon's name in Latin and place it
  *after* the procedural description, often joined by `수술`:
    - `Lloyd-Davies operation` → `복회음 절제 Lloyd-Davies 수술`
    - `Polya operation, gastrectomy` → `위 절제 Polya 수술`
- **Gene/marker symbols** preserved verbatim: `HER2`, `AFB`.
- **Chemical / radioisotope names** keep Latin form when no established
  Korean equivalent exists: `Iobenguane (123-I)`, `M-mode`.
- **Hepatitis virus letters** kept in Latin: `B형 간염`, `C형 간염 항체`.
- **Vitamins** keep the Latin letter and number: `비타민 B12`, `25-OH 비타민D`.
- **Chemical / biochemical analytes** use the **established Korean
  phonetic transliteration**; do **not** back-translate to a descriptive
  Korean compound.
    - `Carboxyhemoglobin` → `카복시헤모글로빈`, not `일산화탄소헤모글로빈`.
    - `Ferritin` → `페리틴`. `Insulin` → `인슐린`.
    - `Triglycerides` → `중성 지방` (conventional Korean term, not
      transliterated).
    - When in doubt, prefer transliteration of the English name over a
      descriptive Korean compound, unless the descriptive form is the
      established Korean clinical term.

**Singular and plural.** Korean does not mark plural obligatorily. Use the
bare noun form regardless of whether the source FSN is singular or plural
unless plurality is semantically essential.

**Parentheses.** Avoid unless they appear in the source FSN and removing
them would lose information.

---

# body structure

**Practical rule:** Use the **Sino-Korean (한자어) form by default** for
anatomical sites, because it has higher exact-match rates against the KR
reference data.

- `appendix` → **충수** (not 막창자꼬리)
- `cecum` → **맹장** (not 막창자)
- `mesentery` → **장간막** (not 창자간막)
- `axilla` → **겨드랑이** (pure Korean — standard reference term)
- `colon` → **결장** (or `대장` for "large intestine")
- `kidney` → **신장** (`콩팥` is acceptable but `신장` is more frequent)
- `prostate` → **전립샘** (partially-pure form is the reference)
- `mediastinum` → **세로칸** (pure Korean is the reference)
- `clavicle`, `sternum`, `tibia`, `incus`: pure Korean (`빗장뼈`,
  `복장뼈`, `정강뼈`, `모루뼈`).
- **Surface anatomy / limb regions: prefer pure Korean.**
    - `thigh` → **넓적다리**, `lower leg` → **종아리**
    - `upper arm` → **위팔**, `forearm` → **아래팔**
    - `wrist` → **손목**, `ankle` → **발목**
    - `palm` → **손바닥**, `sole` → **발바닥**
    - `axilla` → **겨드랑이**

**Heuristic:** Internal organs and viscera → Sino-Korean. Bones and
surface anatomy → pure Korean.

---

# procedure

### General principles

Korean is head-final SOV, so the **procedural action / modality appears at
the end** of the term, opposite to most English FSNs. The KR extension is
highly consistent on this.

- **Anatomical site → action**: `Excision of appendix` → `충수 절제`
- **Modifier → site → action**: `Magnetic resonance imaging of pelvis` → `골반 자기 공명 영상`
- **Approach → modifier → site → action**: `Percutaneous core needle biopsy of liver` → `피부 경유 간의 중심부 바늘 생검`

Other principles observed in the KR extension:

- Use **nominalised verbs** (`-술`, `-검`, `-법`) rather than verbal forms.
- **Avoid long unspaced compounds**; prefer space-separated word units for
  readability, except for fixed nominalisations.
- Do **not** translate the same English word two different ways within one
  term unless the source distinguishes them.
- **Default to no particles between site and action.** The genitive `의`
  is **omitted** in the KR extension's preferred terms more often than
  not. Write `간 배액`, not `간의 배액`. Write `유방 병변 절제`, not
  `유방 병변의 절제`. Only insert `의` if removing it creates an
  unambiguous parsing problem.
- **`-술` (operation suffix) discipline.** Many KR preferred terms use the
  bare nominal form (`절제`, `절개`, `생검`, `배액`) **without** appending
  `-술`. Default to the bare form. Only append `-술` for the following
  **fixed compounds**:
    - `내시경술` (endoscopy), `우회술` (bypass), `절단술` (amputation)
    - **`창냄술`** (stomy / ostomy — `장 창냄술`, `결장 창냄술`,
      `돌창자 창냄술`, `위 창냄술`). Always `-술` for ostomy creation.
    - `조성술`, `형성술` (creation/formation procedures — `장루 조성술`,
      `J형 회장낭 조성술`)
    - `이식술` (transplantation, optional — `이식` alone also common)
    - `치환술`, `교환술` (replacement, optional)
    - `검사` is **not** suffixed with `-술` (already a noun).
- **Do not introduce extra `검사`, `시술`, or generic action nouns** that
  are not in the source. `Urine culture` → `소변 배양`, not
  `소변 배양 검사`. `Pregnancy detection examination` → `임신검사`, not
  `임신 검출 검사`.
- **Do not drop modality qualifiers.** `Doppler ultrasonography` must
  include `도플러`. `fine needle biopsy` must include `가는 바늘` or
  `세침`.
- **Past-tense verbs are not used.**

### Rules and patterns

#### Surgical actions (verb-equivalents)

| English | Korean | Notes |
|---|---|---|
| Excision / -ectomy | **절제** (or **절제술** for "operation") | Most common (637×). Bare `절제` for the act, `-술` when emphasising "operation". |
| Incision / -otomy | **절개** (or **절단** for cutting through) | 189×. Distinguish from `절제` (implies removal). |
| Biopsy | **생검** | 215×. Always one word. |
| Suture | **봉합** | |
| Repair | **복구** (general) / **성형** (plastic) | `성형` when source says "plastic repair" or "reconstruction". |
| Reconstruction | **재건** | Often combined: `재건 성형`. |
| Anastomosis | **연결** (or **문합** for some bowel anastomoses) | `연결` preferred in newer entries. |
| Bypass | **우회술** / **두름길 조성** | |
| Aspiration | **흡인** | |
| Drainage | **배액** | |
| Insertion | **삽입** | |
| Replacement | **치환** (definitive) / **교환** / **교체** (catheter etc.) | `치환` for permanent, `교환`/`교체` for routine maintenance. |
| Removal | **제거** | |
| Revision | **교정** | Not `수정`, not `재시술`, not `재시행`. |
| Supervision | **감독** | Not `지도`. |
| Support (of patient) | **지지** | |
| Closure (of fistula, defect, wound) | **봉합** (suture) / **폐쇄** (general) | Default `봉합`. |
| Giving / Administration (of enema) | bare action noun, no patient subject | `Giving patient an enema` → `관장`. |
| Fixation | **고정** | |
| Ligation | **결찰** | |
| Cauterisation / Ablation | **소작** / **지짐** / **절제** | Modality-dependent. |
| Examination / Test | **검사** | 266×. Generic catch-all. |
| Measurement | **측정** | 126×. |
| Education | **교육** | |
| Counselling | **상담** | |
| Therapy | **치료** / **요법** | `요법` for named therapies; `치료` for generic. |

#### Imaging modality patterns

Highly standardised — do not invent variants:

| English | Korean | Notes |
|---|---|---|
| Computed tomography (CT) | **컴퓨터 단층 촬영** | Always 3 spaced words. |
| Magnetic resonance imaging (MRI) | **자기 공명 영상** | Spaced is more common than `자기공명영상`. |
| Ultrasound / Ultrasonography / Echography | **초음파 검사** | `Echography` → `초음파 검사` (not `에코그래피`). |
| Radiography / X-ray | **방사선 영상 촬영** | |
| Angiography | **혈관 조영** | |
| Scintigraphy / radionuclide imaging | **방사성 핵종 영상** | |
| Fluoroscopy | **투시** | |
| Endoscopy / -scopy | **내시경술** (or **내시경 검사**) | |

**Site-name precedes modality:**
- `Computed tomography of brain` → `뇌 컴퓨터 단층 촬영`
- `Magnetic resonance imaging of prostate` → `전립샘 자기 공명 영상`
- `Ultrasonography of breast` → `유방 초음파 검사`

**Combined / compound modalities follow English order.** Base modality
first, then sub-modality.

| English | Korean |
|---|---|
| Computed tomography angiography with contrast | 조영제 사용 컴퓨터 단층 촬영 혈관 조영 |
| Magnetic resonance angiography | 자기 공명 혈관 조영 |
| Doppler ultrasonography of vein of lower limb | 하지 정맥 도플러 초음파 촬영 |

Do **not** put `혈관 조영` before `컴퓨터 단층 촬영`. CT/MRI base comes
first.

#### Approach / method modifiers

| English | Korean |
|---|---|
| Laparoscopic | **복강경** |
| Laparoscopic-assisted | **복강경 보조** |
| Percutaneous | **피부 경유** |
| Endoscopic | **내시경** |
| Cystoscopic | **방광경하** |
| Transthoracic | **경흉부** |
| Open (surgery) | **개방** (rare; usually omitted) |
| Under [X] guidance | **[X] 유도하** (81+ occurrences) |
| With contrast | **조영제 사용** |
| Without contrast | **조영제 미사용** |
| Using [device] | **[device] 이용 / [device] 사용** |
| Via [route] | **[route] 통한 / [route]로** |

**Approach precedes the rest:**
- `Laparoscopic appendectomy` → `복강경 막창자꼬리 절제`
- `Percutaneous aspiration of liver` → `피부 경유 간의 흡인`
- `Replacement of nephrostomy tube using fluoroscopic guidance` → `투시 유도하 신루관 교체`

#### Combined procedures: "with", "and", "by", "using"

These connectors map to **different** Korean constructions. Do not
conflate them.

**`with` (subordinate step) → `동반`, order reversed.** Only for the
literal word **with** introducing a subordinate concurrent procedure. The
secondary procedure is named *first*, followed by `동반`, then the main
procedure.

| English | Korean |
|---|---|
| Hemigastrectomy with vagotomy | 미주 신경 절단술 동반 반 위절제 |
| Partial colectomy with anastomosis | 연결 동반 결장 부분 절제 |

**`and` or `with` (parallel equal procedures) → `및`, original order.**

| English | Korean |
|---|---|
| Total abdominal colectomy with ileostomy | 배 전체 잘록 창자 절제술 및 돌창자 창냄술 |

**`by [approach]` → `[approach]에 의한 [procedure]`.** Approach first, no
`동반`, no comma, no reversal.

| English | Korean |
|---|---|
| Excision of lesion of rectum by transanal minimal invasive surgery | 경항문 최소 침습 수술에 의한 직장 병변 절제 |

**`using [device or guidance]` → `[device] 이용 [procedure]` or
`[device] 유도하 [procedure]`.** Device/guidance first, no `동반`.

**Critical:** use the **bare nominal** `이용`, not the adnominal
`이용한` / `이용하여`. Do **not** insert verb endings, suffixes, or
particles between `이용` and the procedure noun.

| English | Korean |
|---|---|
| Biopsy of peritoneum using computed tomography guidance | 컴퓨터 단층 촬영 유도하 복막 생검 |
| External beam radiation therapy using electrons | 전자 이용 외부 빔 방사선 치료 |
| Anastomosis of colon to rectum using staples | 봉합기 이용 결장 직장 연결 |
| Repair of gastroschisis with prosthesis | 인공삽입물 이용 복벽갈림증 복구 |

**Critical:** **never** use `동반` for `by`, `using`, `via`, `through`,
or `under guidance`. `동반` is reserved for literal `with` introducing a
*concurrent surgical step*. Keep modifier clause → site → action.

**Critical:** secondary and main clauses join **without a comma**.
`직장 병변 절제, 경항문 최소 침습 수술` is wrong. One continuous noun phrase.

#### Total / Subtotal / Partial

| English | Korean |
|---|---|
| Total | **전체** (or **완전** in some contexts) |
| Subtotal | **부분** / **대부분** |
| Partial | **부분** |
| Distal | **먼쪽** (pure) / **원위부** (Sino) — both used |
| Proximal | **몸쪽** (pure) / **근위부** (Sino) — both used |

Quantifiers precede the site:
- `Distal subtotal pancreatectomy` → `먼쪽 부분 췌장 절제`
- `Total replacement of hip` → `전체 엉덩관절 치환`

#### Laterality

| English | Korean |
|---|---|
| Left | **왼쪽** (77×) |
| Right | **오른쪽** (74×) |
| Bilateral | **양측** |

Laterality precedes the site:
`Magnetic resonance imaging of sciatic nerve` → `왼쪽 궁둥 신경 자기 공명 영상`

#### Education / counselling / therapy

- `... education` → `... 교육`
- `... counseling` → `... 상담`
- `... therapy` → `... 요법` (named therapies) / `... 치료` (generic)
- `Guidance / instruction` → `... 교육` or `... 지도`

Examples: `Diet education` → `식이 교육`, `Genetic counseling` → `유전 상담`,
`Cold therapy` → `저온 요법`, `Behavioral therapy` → `행동 요법`.

### Worked examples

| SCTID | English PT | Korean reference |
|---|---|---|
| 80146002 | Excision of appendix | 충수 절제술 |
| 73761001 | Colonoscopy | 결장 내시경술 / 대장 내시경 검사 |
| 18027006 | Transplantation of liver | 간 이식 |
| 232717009 | Coronary artery bypass graft | 관상 동맥 우회술 |
| 401004 | Distal subtotal pancreatectomy | 먼쪽 부분 췌장 절제 |
| 165001 | Behavioral therapy | 행동 요법 |
| 306005 | Echography of kidney | 신장 초음파 검사 |
| 388008 | Blepharorrhaphy | 눈꺼풀 봉합 |
| 116142003 | Radical hysterectomy | 근치 자궁절제 |

### Additional rules (from error analysis)

**Avoid phonetic transliteration for established medical concepts.** Do
not use phonetic Hangul for a procedure that has a Sino-Korean /
descriptive Korean clinical term.

| English | Avoid | Prefer |
|---|---|---|
| Debridement | 데브리망 | 죽은 조직 제거 |
| Plasmapheresis | 플라즈마페레시스 | 혈장분리 교환 |

**Maintain distinction between specific structures and generic terms.**
Do not generalise a specific anatomical pathology into a different
structure (e.g. `ureterocele` is not `ureteral cyst`; `pouch of Douglas`
is not `cecum`).

**Keep established pure-Korean forms where KR uses them.** Do not force
Sino-Korean when pure is the standard (e.g. `가슴` for thorax,
`머리뼈` for skull, `볼기` for buttock).

**Distinguish anastomosis from stoma creation.**

| English | Korean | Note |
|---|---|---|
| Anastomosis / Connection | **연결** / **문합** | Joining two structures. |
| Stoma creation / Ostomy | **창냄술** / **조루술** | Creating an opening. |

**Do not word-for-word translate compound modifiers.** For `with`
(subordinate step): `[Secondary] 동반 [Main]`. For `using` / `by`:
`[Method] 유도하 [Procedure]` or `[Method] 이용 [Procedure]`.

**Do not add clinical or administrative detail not in the source.** A
general concept (`Consultation`) stays general; do not append
fee/billing-specific wording.
