# Korean SNOMED CT translation style guide (v5)

> Derived from v3-abbreviated + corrections distilled from KHIS Korean
> clinician feedback on a 100-term radiology sample (May 2026). Changes
> from v3 are concentrated in: spacing inside fixed imaging compounds,
> derivational suffix preservation (`-graphy → -조영술`, `-gram → -조영상`),
> placement of the contrast modifier, choice between Sino-Korean and
> native limb-region terms, and handling of unfamiliar -graphy / -gram
> roots. All rules below are general; **none cite the specific 100-term
> review set**.

---

# general

**Term length.** Maximum 255 characters, matching SNOMED CT specification.

**Script and case.** Korean terms are written in Hangul (한글). Latin
characters inside a Korean term (gene symbols, drug names, chemical
formulae, eponyms) preserve the case used in the source. Hanja (漢字) is
not used in clinical terms.

**Spacing (띄어쓰기) — read carefully, this rule has two layers.**

Korean terms in the KR extension separate **word units** with spaces.
However, *inside* a fixed Korean compound that is itself the established
single-referent name of an imaging modality, an established procedural
noun, or an imaging product, the compound is written **without internal
spaces**. The space rule applies *between* compounds, not *inside* them.

This produces a consistent two-level layout:

```
[modifier]   [body site]   [modality-compound]   [optional product/suffix]
```

Where each bracketed unit is one space-separated chunk; the
modality-compound itself contains no internal space.

Fixed compounds that are **always written solid** (no internal space):

- **Modality names** that function as a single clinical referent:
  `자기공명영상` (MRI), `컴퓨터단층촬영` (CT), `양전자단층촬영` (PET),
  `단일광자단층촬영` (SPECT), `방사선영상촬영` (X-ray), `초음파검사`
  (ultrasound study).
- **Imaging products / studies** that combine modality + study suffix:
  `혈관조영술` (angiography), `정맥조영술` (venography), `동맥조영술`
  (arteriography), `림프관조영술` (lymphangiography), `관절조영(술)`
  (arthrography), `척수조영상` (myelogram), `자궁난관조영술`
  (hysterosalpingography), `누관조영술` (dacryocystography), `유방영상`
  (mammogram-as-image), `유방촬영술` (mammography-as-procedure).
- **Established procedural / surgical compounds** ending in `-술`,
  `-법`, `-검`, `-증`, `-염`: never internally spaced
  (`내시경술`, `생검`, `절제술`, `봉합술`, …).

Pattern, with synthetic illustrative examples (not from any
review set):

| English construction | Korean layout (chunks shown with `·`) |
|---|---|
| MRI of cervical spine | `목뼈 · 자기공명영상` |
| CT of liver with contrast | `조영제 사용 · 간 · 컴퓨터단층촬영` |
| Angiography of renal artery | `콩팥동맥 · 혈관조영술` |
| Venography of pulmonary vein | `폐정맥 · 정맥조영술` |

**Rule of thumb:** if the Korean string is the **name of a thing**
(one specific modality, one specific imaging product), keep it solid.
If it is a sequence of **separate words** describing the procedure
(body site + modality + qualifier), put spaces between those words.
The KR extension's older entries sometimes write modality names with
spaces (e.g. `자기 공명 영상`); the spaced form is *acceptable* but the
solid form is preferred and is what radiology SMEs validate against.

**Punctuation.** UTF-8 encoding. Korean terms generally do **not** end
in punctuation. Commas are rare and used only in list-like
constructions. Hyphens are preserved inside hyphenated foreign names
(`Lloyd-Davies`, `M-mode`, `25-OH`).

**Numbers.** Arabic numerals throughout.

**Abbreviations and Latin loan words.** The KR extension keeps a small
consistent set of items in Latin script:

- **Eponymous procedures** keep the surgeon's name in Latin and place it
  *after* the procedural description, often joined by `수술`:
    - `Lloyd-Davies operation` → `복회음 절제 Lloyd-Davies 수술`
- **Gene / marker symbols** preserved verbatim: `HER2`, `AFB`.
- **Chemical / radioisotope names** keep Latin form when no established
  Korean equivalent exists: `Iobenguane (123-I)`, `M-mode`.
- **Hepatitis virus letters** kept in Latin: `B형 간염`, `C형 간염 항체`.
- **Vitamins** keep the Latin letter and number: `비타민 B12`,
  `25-OH 비타민D`.
- **Chemical / biochemical analytes** use the **established Korean
  phonetic transliteration**, not back-translation. Default to
  transliteration unless the descriptive Korean form is the
  established clinical term.

**Singular and plural.** Korean does not mark plural obligatorily. Use
the bare noun form regardless of source FSN plurality unless plurality
is semantically essential.

**Parentheses.** Avoid unless they appear in the source FSN and removing
them would lose information.

---

# body structure

**Default rule:** Use the **Sino-Korean form (한자어)** for internal
organs and viscera; use **native Korean** for surface anatomy, limb
regions, and broad regional descriptors.

**Internal organs / viscera → Sino-Korean (한자어):**

- `appendix` → **충수**
- `cecum` → **맹장**
- `mesentery` → **장간막**
- `colon` → **결장**
- `kidney` → **신장**
- `prostate` → **전립샘**
- `mediastinum` → **세로칸** (this is a partial exception — `세로칸` is
  the pure-Korean form but it is the established reference term)

**Surface anatomy / bones / limb-region descriptors → native Korean
(고유어):**

This category is broader than v3 indicated. It covers not only specific
small surface parts but also the **broad regional descriptors that
SNOMED uses as parent bracketing terms** — "upper limb" (the whole
arm), "lower limb" (the whole leg), "lumbar region", "thoracic
region", "retroperitoneal space", and similar. SME reviewers
consistently prefer the native term over the Sino-Korean in these
positions:

| Category | Native Korean (preferred) | Sino-Korean (avoid in this position) |
|---|---|---|
| Whole upper extremity ("upper limb") | **팔** | 상지 |
| Whole lower extremity ("lower limb") | **다리** | 하지 |
| Lumbar region | **허리부위** | 요부 / 요 부위 |
| Thoracic region | **가슴부위** | 흉부 (acceptable in narrower contexts) |
| Retroperitoneal | **후복막** | 복막뒤 |
| Pelvic organs | **골반장기** | 골반기관 |
| Bone of [limb-region] | **`[native limb]뼈`** (`팔뼈`, `다리뼈`) | 위팔 뼈, 상지골 |
| Brachial plexus | **신경얼기** (when "plexus" is the head noun) | 신경총 |
| Skull | **머리뼈** | 두개골 |
| Buttock | **볼기** | 둔부 |
| Thorax | **가슴** | 흉부 |

**Heuristic:** Internal organs and viscera → Sino-Korean. Bones, surface
anatomy, **and broad limb / regional descriptors** → native Korean.

**Do not add an extra anatomical word** that is not in the source. If
the source FSN is "external auditory meatus", the Korean is the single
established term for that referent — do not prepend an additional body
part name as a descriptor. One referent in, one referent out.

---

# procedure

### General principles

Korean is head-final SOV, so the **procedural action / modality appears
at the end** of the term, opposite to most English FSNs. The KR
extension is highly consistent on this.

- **Anatomical site → action**: `Excision of appendix` → `충수 절제`
- **Modifier → site → action**: `MRI of pelvis` → `골반 자기공명영상`
- **Approach → modifier → site → action**:
  `Percutaneous core needle biopsy of liver`
  → `피부 경유 간의 중심부 바늘 생검`

Other principles observed in the KR extension and confirmed by SMEs:

- Use **nominalised verbs** (`-술`, `-검`, `-법`) rather than verbal
  forms.
- **Avoid long unspaced compounds for description**, but **do keep
  fixed nominal compounds solid** (see "spacing" above).
- Do **not** translate the same English word two different ways within
  one term unless the source distinguishes them.
- **Default to no particles between site and action.** The genitive
  `의` is omitted in the KR extension's preferred terms more often than
  not.
- **Do not introduce extra `검사`, `시술`, or generic action nouns**
  that are not in the source.
- **Do not drop modality qualifiers.** `Doppler ultrasonography` must
  include `도플러`. `fine needle biopsy` must include `가는 바늘` or
  `세침`.
- **Past-tense verbs are not used.**

### Derivational suffixes — preserve them

The English suffixes `-graphy`, `-gram`, `-scopy`, `-metry`, `-otomy`,
`-ectomy`, etc. are **load-bearing semantic content**. Each maps to a
specific Korean suffix; **do not drop the suffix** to produce a
shorter noun. The suffix tells the reader whether the term names the
procedure, the imaging product, or the study type.

| English suffix | Korean suffix | Reading |
|---|---|---|
| `-graphy` | **`-조영술`** (when imaging with contrast / contrast study) or **`-촬영(술)`** (when no contrast emphasis) | the study / procedure |
| `-gram` | **`-조영상`** (imaging product, with contrast) or **`-영상`** (imaging product, general) | the produced image |
| `-otomy` | **`-절개(술)`** | incision |
| `-ectomy` | **`-절제(술)`** | excision |
| `-scopy` | **`-내시경(술)`** / **`-경 검사`** | endoscopic study |
| `-metry` | **`-측정(법)`** | measurement |
| `-plasty` | **`-성형(술)`** | reconstruction |
| `-stomy` | **`-창냄술`** | stoma creation |
| `-pexy` | **`-고정(술)`** | fixation |

**Special-case modality + suffix combinations** (use the fixed compound,
not a calque):

| English | Korean fixed compound |
|---|---|
| -graphy of vein / venography | `정맥조영술` |
| -graphy of artery / arteriography | `동맥조영술` |
| -graphy of vessel / angiography | `혈관조영술` |
| -graphy of lymph vessel / lymphangiography | `림프관조영술` |
| -graphy of joint / arthrography | `관절조영(술)` |
| -gram of spinal cord / myelogram | `척수조영상` |
| -gram of breast / mammogram | `유방영상` (the image) / `유방촬영술` (the procedure) |
| -graphy of bile duct / cholangiography | `담관조영술` |
| -graphy of uterus and tubes / hysterosalpingography | `자궁난관조영술` |

**When the model encounters an unfamiliar `-graphy / -gram` root**
(e.g. an organ-specific compound it has not seen), the correct
behaviour is to **decompose**, not transliterate:

1. Identify the body part / referent from the root.
2. Translate the body-part stem to Korean.
3. Append `조영술` (procedure) or `조영상` (image) depending on whether
   the English ends in `-graphy` / `-gram` respectively.

**Never produce a phonetic Hangul rendering of an English `-graphy` /
`-gram` word** (e.g. do not invent `*-그램`, `*-그래피` strings). If
decomposition fails, prefer the literal English word in Latin script
to a malformed transliteration; the next reviewer can then correct
it.

### Avoid phonetic transliteration for established medical concepts

Do not use phonetic Hangul for a procedure / structure that has a
Sino-Korean or descriptive Korean clinical term.

| English | Avoid | Prefer |
|---|---|---|
| Debridement | 데브리망 | 죽은 조직 제거 |
| Plasmapheresis | 플라즈마페레시스 | 혈장분리 교환 |
| Herniation (as suffix) | `*-니아` / `*-니에이션` | use descriptive Korean for the structure |

Transliteration is reserved for chemical names, drug INNs, eponyms,
and a small set of biochemical analytes (see "general").

### Surgical actions (verb-equivalents)

| English | Korean | Notes |
|---|---|---|
| Excision / -ectomy | **절제** (or **절제술**) | Bare for the act, `-술` when emphasising "operation". |
| Incision / -otomy | **절개** (or **절단** for cutting through) | |
| Biopsy | **생검** | Always one word. |
| Suture | **봉합** | |
| Repair | **복구** (general) / **성형** (plastic) | |
| Reconstruction | **재건** | |
| Anastomosis | **연결** (or **문합**) | |
| Bypass | **우회술** / **두름길 조성** | |
| Aspiration | **흡인** | |
| Drainage | **배액** | |
| Insertion | **삽입** | |
| Replacement | **치환** (definitive) / **교환** / **교체** | |
| Removal | **제거** | |
| Revision | **교정** | Not `수정`, not `재시술`. |
| Closure | **봉합** (suture) / **폐쇄** (general) | |
| Fixation | **고정** | |
| Ligation | **결찰** | |
| Cauterisation / Ablation | **소작** / **지짐** / **절제** | |
| Examination / Test | **검사** | |
| Measurement | **측정** | |
| Education | **교육** | |
| Counselling | **상담** | |
| Therapy | **치료** / **요법** | |
| Crushing (of stone) | **분쇄(술)** / **파쇄(술)** | Use established compound for lithotripsy. |
| Lithotripsy (specifically) | **결석 파쇄술** (general) / **체외 충격파 쇄석술** (ESWL) | |

### Imaging modality patterns

Highly standardised — do not invent variants. **These compounds are
written solid (no internal space).**

| English | Korean (solid) | Notes |
|---|---|---|
| Computed tomography (CT) | **컴퓨터단층촬영** | |
| Magnetic resonance imaging (MRI) | **자기공명영상** | |
| Ultrasound / Echography | **초음파검사** | "Echography" → `초음파검사`, not `에코그래피`. |
| Radiography / X-ray | **방사선영상촬영** | Or shorter `X선 촬영` when the source uses "X-ray" directly. |
| Angiography (vessel-generic) | **혈관조영술** | |
| Venography | **정맥조영술** | |
| Arteriography | **동맥조영술** | |
| Scintigraphy / radionuclide imaging | **방사성핵종영상** | |
| SPECT (single photon emission CT) | **단일광자단층촬영** | |
| PET (positron emission tomography) | **양전자단층촬영** | |
| Fluoroscopy | **투시** | |
| Cineradiography / cine imaging | **시네촬영(술)** | |
| Endoscopy / -scopy | **내시경술** / **내시경 검사** | |

**Site-name precedes modality** (general rule):

- `CT of brain` → `뇌 컴퓨터단층촬영`
- `MRI of prostate` → `전립샘 자기공명영상`

**Combined / compound modalities follow English order.** Base modality
first, then sub-modality. Each compound is solid; the two compounds
are space-separated:

| English | Korean |
|---|---|
| CT angiography with contrast | `조영제 사용 컴퓨터단층촬영 혈관조영` |
| MR angiography | `자기공명 혈관조영` |
| Doppler ultrasonography of vein of lower limb | `다리 정맥 도플러 초음파검사` |
| SPECT with CT of [site] | `[site] 단일광자단층촬영 및 컴퓨터단층촬영` |

Do **not** put `혈관조영` before `컴퓨터단층촬영`. Base modality first.

### Contrast modifier — placement and form

The contrast modifier translates with a fixed two-form pair:

| English | Korean |
|---|---|
| With contrast | **조영제 사용** |
| Without contrast | **조영제 미사용** |

**Place the contrast modifier at the FRONT of the term** (before site
and modality), not at the end. This is the dominant convention in
clinician-validated radiology terms.

```
조영제 사용 / 미사용  +  [laterality]  +  [site]  +  [modality compound]  +  [study suffix]
```

**Critical:** the "without contrast" form is `조영제 미사용`. It must
not be dropped. If the source FSN contains the words "without
contrast", the Korean must include `조영제 미사용` at the front. The
absence of any contrast phrase in the Korean output is *not* a valid
rendering of "without contrast".

### Approach / method modifiers

| English | Korean |
|---|---|
| Laparoscopic | **복강경** |
| Laparoscopic-assisted | **복강경 보조** |
| Percutaneous | **피부 경유** |
| Endoscopic | **내시경** |
| Cystoscopic | **방광경하** |
| Transthoracic | **경흉부** |
| Open (surgery) | **개방** (rare; usually omitted) |
| Under [X] guidance | **[X] 유도하** |
| Using [device] | **[device] 이용 / [device] 사용** |
| Via [route] | **[route] 통한 / [route]로** |
| With contrast / Without contrast | see above — fronted |

**Approach precedes the rest:**

- `Laparoscopic appendectomy` → `복강경 충수 절제`
- `Percutaneous aspiration of liver` → `피부 경유 간 흡인`

### Combined procedures: "with", "and", "by", "using"

These connectors map to **different** Korean constructions. Do not
conflate them.

**`with` (subordinate concurrent step) → `동반`, order reversed.** Only
for the literal word **with** introducing a subordinate concurrent
procedure. Secondary procedure first, then `동반`, then the main
procedure.

| English | Korean |
|---|---|
| Hemigastrectomy with vagotomy | 미주 신경 절단술 동반 반 위절제 |
| Partial colectomy with anastomosis | 연결 동반 결장 부분 절제 |

**`and` or `with` (parallel equal procedures) → `및`, original order.**

| English | Korean |
|---|---|
| Total abdominal colectomy with ileostomy | 배 전체 잘록창자 절제술 및 돌창자 창냄술 |

**`by [approach]` → `[approach]에 의한 [procedure]`.** Approach first,
no `동반`, no comma, no reversal.

**`using [device or guidance]` → `[device] 이용 [procedure]` or
`[guidance] 유도하 [procedure]`.** Device / guidance first, no `동반`.

| English | Korean |
|---|---|
| Biopsy of [site] using CT guidance | `컴퓨터단층촬영 유도하 [site] 생검` |
| External beam radiation therapy using electrons | 전자 이용 외부 빔 방사선 치료 |

**Critical:** secondary and main clauses join **without a comma**.

### Total / Subtotal / Partial / laterality / quantifiers

| English | Korean |
|---|---|
| Total | **전체** (or **완전**) |
| Subtotal / Partial | **부분** |
| Distal | **먼쪽** / **원위부** |
| Proximal | **몸쪽** / **근위부** |
| Left | **왼쪽** |
| Right | **오른쪽** |
| Bilateral | **양측** |

Laterality precedes the site:
`MRI of right sciatic nerve` → `오른쪽 궁둥신경 자기공명영상`

### Radiology-specific idioms (new in v5)

- **`Symptomatic [study]`** in a radiology context is **not** the
  symptom-treatment form. It is shorthand for "diagnostic", i.e. a
  study performed because the patient has symptoms (as opposed to
  screening). Translate `symptomatic` as **`진단`** in this position,
  never as `증상치료` or `증상성`.
- **`Screening [study]`** stays as **`선별`** + study (e.g. screening
  mammogram → `선별 유방영상`). Do not conflate with `진단`.
- **`Limited [study]`** → **`제한적 [study]`** — the limiter goes
  before the study compound, not appended after.
- **`Diagnostic`** as a redundant qualifier (e.g. "diagnostic
  ultrasound") is **dropped** if it would be implied; only include
  it if the source explicitly contrasts diagnostic vs therapeutic /
  screening / interventional.

### Long noun phrases

For long procedure FSNs with several stacked modifiers (often
seen in interventional cardiology / radiology), the assembly order is:

```
[contrast]  +  [guidance / imaging modality used for guidance]  +
[approach / route]  +  [device / appliance]  +
[main procedure / action]
```

Translate each modifier separately, place them in this order, and
keep them all space-separated; do **not** try to reflect English
word order one-to-one when it conflicts with the Korean SOV
modifier-stacking convention. Resist literal word-by-word
back-translation — read the source phrase as a whole, identify the
five slots above, then assemble.

### Education / counselling / therapy

- `... education` → `... 교육`
- `... counseling` → `... 상담`
- `... therapy` → `... 요법` (named therapies) / `... 치료` (generic)

### Worked examples (synthetic — illustrative only, not from any review set)

| Synthetic English | Korean reference |
|---|---|
| CT of pancreas with contrast | 조영제 사용 췌장 컴퓨터단층촬영 |
| MRI of cervical spine without contrast | 조영제 미사용 목뼈 자기공명영상 |
| Angiography of renal artery | 콩팥동맥 혈관조영술 |
| Venography of pulmonary vein | 폐정맥 정맥조영술 |
| Myelogram of thoracic spinal cord | 등뼈 척수조영상 |
| Ultrasound-guided biopsy of liver | 초음파 유도하 간 생검 |
| Mammogram (screening) of right breast | 선별 오른쪽 유방영상 |
| Mammogram (diagnostic) of left breast | 진단 왼쪽 유방영상 |

### Additional rules (from error analysis)

**Maintain distinction between specific structures and generic
terms.** Do not generalise a specific anatomical pathology into a
different structure.

**Distinguish anastomosis from stoma creation.**

| English | Korean | Note |
|---|---|---|
| Anastomosis / Connection | **연결** / **문합** | Joining two structures. |
| Stoma creation / Ostomy | **창냄술** / **조루술** | Creating an opening. |

**Do not word-for-word translate compound modifiers.** For `with`
(subordinate step): `[Secondary] 동반 [Main]`. For `using` / `by`:
`[Method] 유도하 [Procedure]` or `[Method] 이용 [Procedure]`.

**Do not add clinical or administrative detail not in the source.**

**Output one referent per source referent.** Do not add an extra
anatomical word as a "helpful descriptor" when the SNOMED source
names a single referent — the SME convention is to match the
source's level of specificity, not to expand it.
