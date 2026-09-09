# Korean SNOMED CT translation style guide (v6.0)

> v5.1 revised against the SME terminologist's batch-2 review and their
> answers to our 15 style questions (received 2026-08-09). The major
> reversals from v5.1: (1) **native-Korean anatomy is now the preferred
> register** (Sino-Korean forms remain acceptable synonyms) — the KR
> extension's Sino preference is NOT the target; (2) **X-ray = 단순 촬영**,
> not 방사선 영상 촬영; (3) produced **images end in 영상, never 조영상**;
> (4) fluoroscopy has distinct exam vs guidance forms. New hard
> constraint: never introduce a contrast phrase the source does not have.

---

# general

**Term length.** Maximum 255 characters, matching SNOMED CT specification.

**Script and case.** Korean terms are written in Hangul (한글). Latin
characters inside a Korean term (gene symbols, drug names, chemical
formulae, eponyms) preserve the case used in the source.

**Spacing (띄어쓰기).** Default to **space-separated word units**:

- `컴퓨터 단층 촬영` (Computed tomography)
- `자기 공명 영상` (Magnetic resonance imaging)
- `부분 위 절제` (Partial gastrectomy)

Well-established medical compounds and short procedural nouns are written
without spaces: `절제술`, `내시경술`, `생검`, `측정`, `복강경`, `흡인`,
`봉합`, `연결`.

The SME has confirmed that **spacing variants of established imaging
compounds are acceptable** (`자기공명영상` = `자기 공명 영상`); spacing
differences alone never make a term wrong. Still default to the spaced
form for consistency.

**Rule of thumb:** Space-separated word units; no spaces inside fixed
nominalisations ending in `-술`, `-법`, `-검`, `-증`, `-염`.

**Punctuation.** UTF-8. Korean terms do **not** end in punctuation.
Hyphens are preserved inside hyphenated foreign names (`Lloyd-Davies`,
`M-mode`, `25-OH`).

**Numbers.** Arabic numerals throughout.

**Abbreviations and Latin loan words.**

- **Eponymous procedures** keep the name in Latin after the procedural
  description: `복회음 절제 Lloyd-Davies 수술`.
- **Gene/marker symbols** verbatim: `HER2`, `AFB`.
- **Chemical / radioisotope names** keep Latin form when no established
  Korean equivalent exists: `Iobenguane (123-I)`, `M-mode`.
- **Hepatitis virus letters** in Latin: `B형 간염`.
- **Vitamins**: `비타민 B12`, `25-OH 비타민D`.
- **Analytes** use the established Korean phonetic transliteration
  (`카복시헤모글로빈`, `페리틴`, `인슐린`) unless a conventional Korean
  term exists (`중성 지방`).

**Phonetic transliteration policy (SME ruling).** Phonetic Hangul is
appropriate **only** for drugs, substances, tracers, devices, and newly
introduced procedure names with no established Korean form. Everything
else decomposes into Korean clinical meaning. Never phonetically echo an
English procedure word that has a Korean clinical term.

**Singular and plural.** Use the bare noun form unless plurality is
semantically essential.

**Parentheses.** Avoid unless present in the source and load-bearing.

---

# body structure

**Register (SME ruling — reverses v5.1).** **Native (pure) Korean
anatomical terms are preferred.** Sino-Korean (한자어) forms are
acceptable and may be kept as synonyms, but when choosing one rendering,
choose the native form:

- `subclavian artery` → **빗장밑동맥** (쇄골하동맥 acceptable synonym)
- `mediastinum` → **세로칸** (종격동 acceptable synonym)
- `inguinal region` → **고샅** (서혜부 acceptable synonym)
- `ilium` → **엉덩뼈** (장골 acceptable synonym)
- `clavicle`, `sternum`, `tibia`, `incus` → `빗장뼈`, `복장뼈`,
  `정강뼈`, `모루뼈`
- `bone` as a word → prefer **뼈** over 골 inside descriptive phrases.

Where the native form is unnatural or does not exist for viscera, the
established clinical term stands (e.g. `충수`, `전립샘`, `신장` remain
correct); do not invent awkward native coinages. The rule is a
*preference for native forms where both are established*, not a ban on
Sino-Korean.

**Limbs (SME ruling).**

| English | Preferred | Acceptable |
|---|---|---|
| upper limb / upper extremity | **팔** | 상지 |
| lower limb / lower extremity | **다리** | 하지 |
| upper arm (specifically arm above elbow) | **위팔** | — |
| forearm | **아래팔** | — |

**위팔 is reserved for the upper arm segment; do not use it for "upper
limb/extremity" as a whole.**

- `thigh` → **넓적다리**, `lower leg` → **종아리**
- `wrist` → **손목**, `ankle` → **발목**
- `palm` → **손바닥**, `sole` → **발바닥**, `axilla` → **겨드랑이**

**Ontology scaffolding (SME ruling).** Do **not** translate "structure
of" in body-site expressions — `structure of joint of left lower
extremity` → `왼쪽 다리 관절`. **Exception:** when the procedure is
genuinely about the physical structure (opposite of function), keep it:
`Magnetic resonance imaging of bone structure of coccyx` images the bone
structure of the coccyx — translate the bone-structure sense (using 뼈).
Never render it redundantly when the site is itself a bone (coccyx is a
bone: `꼬리뼈` already carries the meaning).

---

# procedure

### General principles

Korean is head-final SOV: the **procedural action / modality appears at
the end** of the term.

- **Site → action**: `Excision of appendix` → `충수 절제`
- **Modifier → site → action**: `Magnetic resonance imaging of pelvis` →
  `골반 자기 공명 영상`
- **Approach → modifier → site → action**: `Percutaneous core needle
  biopsy of liver` → `피부 경유 간의 중심부 바늘 생검`

**Word order matters.** The SME rates word-order deviations as errors
(they defeat the purpose of an editorial guide); spacing and
preferred-synonym differences are acceptable, word-order differences are
not. Follow the ordering templates in this guide exactly.

Other principles:

- Use **nominalised verbs** (`-술`, `-검`, `-법`) rather than verbal forms.
- Do **not** translate the same English word two different ways within
  one term unless the source distinguishes them.
- **Default to no particles between site and action**: `간 배액`, not
  `간의 배액`. Insert `의` only to resolve a real parsing ambiguity.
- **`-술` discipline.** Default to the bare nominal (`절제`, `절개`,
  `생검`, `배액`). Fixed `-술` compounds: `내시경술`, `우회술`,
  `절단술`, `창냄술` (always for ostomy), `조성술`, `형성술`,
  `이식술` (optional), `치환술` / `교환술` (optional). `검사` is never
  suffixed with `-술`.
- **Do not introduce extra `검사`, `시술`, or generic action nouns** not
  in the source: `Urine culture` → `소변 배양`.
- **Do not drop modality qualifiers** (`도플러`, `세침`/`가는 바늘`).
- **Past-tense verbs are not used.**

### Imaging modality forms (SME-canonical, 2026-08)

These are the SME's canonical answers; use them exactly.

| English | Korean | Notes |
|---|---|---|
| X-ray (plain radiography) | **단순 촬영** | NOT 방사선 영상 촬영, NOT X선. |
| Radiographic imaging (procedure) | **방사선 촬영** | |
| Radiographic image (object) | **방사선 촬영 영상** | |
| Computed tomography (CT) | **컴퓨터 단층 촬영** | |
| Magnetic resonance imaging (MRI) | **자기 공명 영상** | |
| Magnetic resonance (MR, as modifier) | **자기 공명** | |
| Ultrasound (modality) | **초음파** | |
| Ultrasonography / ultrasound studies | **초음파 검사** | |
| Ultrasound scan | **초음파 스캔** | |
| Fluoroscopy (standalone examination) | **투시 검사** (or 투시술) | |
| Fluoroscopy guidance | **투시 유도하** (or 형광 투시 유도하) | Guidance uses 투시, never 투시 검사. |
| Angiography (with a named artery/vein) | **[vessel] 혈관 조영** | e.g. 관상 동맥 혈관 조영 |
| Angiography (no vessel named) | **동맥 조영** | |
| Venography | **정맥 조영** | |
| Arteriography | **동맥 조영(술)** | |
| Radionuclide imaging / scintigraphy | **방사성 핵종 영상** | |
| Positron emission tomography | **양전자 (방출) 단층 촬영** | |
| Endoscopy / -scopy | **내시경술** (or 내시경 검사) | |

**Site precedes modality:** `뇌 컴퓨터 단층 촬영`,
`전립샘 자기 공명 영상`, `유방 초음파 검사`.

**Compound modalities follow English order** — base modality first:
`Computed tomography angiography with contrast` →
`조영제 사용 컴퓨터 단층 촬영 혈관 조영`. Do not put `혈관 조영` before
`컴퓨터 단층 촬영`.

**Vague / historical study names (SME ruling).** For terms like *special
study*, *skeletal survey*, *coned mammogram*, *cineswallow*: use the
**conventional modern Korean procedure name**, not a literal calque
(e.g. skeletal survey → `골격 조사`).

#### Derivational suffixes: -graphy vs -gram (SME ruling)

| English suffix | Korean suffix | Reading |
|---|---|---|
| `-graphy` (procedure) | **`조영`** or **`조영술`** (contrast studies); **`촬영(술)`** otherwise | the study |
| `-gram` (produced image) | **`영상`** — **never `조영상`** | the image |
| `-otomy` | `절개(술)` | incision |
| `-ectomy` | `절제(술)` | excision |
| `-scopy` | `내시경(술)` / `경 검사` | endoscopic study |
| `-metry` | `측정(법)` | measurement |
| `-plasty` | `성형(술)` | reconstruction |
| `-stomy` | `창냄술` | stoma creation |
| `-pexy` | `고정(술)` | fixation |

Special cases (established forms):

| English | Korean |
|---|---|
| venography | `정맥 조영(술)` |
| arteriography | `동맥 조영(술)` |
| angiography (vessel named) | `[vessel] 혈관 조영(술)` |
| lymphangiography | `림프관 조영(술)` |
| arthrography | `관절 조영(술)` |
| myelogram (image) | `척수 영상` |
| mammogram (image) | `유방 영상` |
| mammography (procedure) | `유방 촬영술` |
| cholangiography | `담관 조영(술)` |
| hysterosalpingography | `자궁난관 조영(술)` |
| serialography | `연속촬영술` |

**For unfamiliar `-graphy / -gram` roots, decompose**: identify the
referent, translate the stem, append `조영(술)` (procedure) or `영상`
(image). **Never produce a phonetic Hangul rendering** of a `-graphy` /
`-gram` word; if decomposition fails, keep the English word in Latin
script for reviewer attention.

#### Contrast modifier — placement, form, and fidelity

| English | Korean |
|---|---|
| with contrast | **`조영제 사용`** |
| without contrast | **`조영제 미사용`** |

**Contrast modifiers always come FIRST** (SME-confirmed):

```
조영제 사용/미사용 + [guidance] + [laterality] + [site] + [modality] + [suffix]
```

- "without contrast" must not be dropped: the output must contain
  `조영제 미사용` at the front.
- **FIDELITY (hard rule): if the source says nothing about contrast, the
  output must not contain `조영제 사용` or `조영제 미사용`.** Inventing a
  contrast phrase was the most common outright error in SME review —
  e.g. *Venography of inferior vena cava with serialography* has no
  contrast phrase, so no `조영제` word may appear. `-graphy` does NOT
  imply "with contrast".

#### Radiology-specific idioms

- **`symptomatic [study]`** = *diagnostic* (study because of symptoms) →
  **`진단`**, never `증상치료` / `증상성`.
- **`screening [study]`** → **`선별`** + study.
- **`limited [study]`** → **`제한적`** before the study compound.
- **`diagnostic`** as redundant qualifier is dropped when already implied.
- **`localization`** (finding the site of a problem) → **`위치 파악`**,
  not `국소` / `국소화`.
- **`transcranial`** → **`경두개`** (transcranial Doppler =
  `경두개 도플러 초음파 검사`), never `뇌혈류`.
- **`specific [study]`** → **`특수`** (special/specialised study), not
  `특이적`.

#### Source-fidelity rule

Output **one referent per source referent**; do not prepend helpful
descriptors, and do not add any qualifier (contrast, laterality, device,
"artificial", modality) that the source does not state. Do not omit
qualifiers the source does state (serialography, compression, delayed…).

### Rules and patterns

#### Surgical actions (verb-equivalents)

| English | Korean | Notes |
|---|---|---|
| Excision / -ectomy | **절제** (`절제술` for "operation") | |
| Incision / -otomy | **절개** (`절단` for cutting through) | |
| Biopsy | **생검** | Always one word. |
| Suture | **봉합** | |
| Repair | **복구** (general) / **성형** (plastic) | |
| Reconstruction | **재건** | |
| Anastomosis | **연결** (or **문합**) | |
| Bypass | **우회술** | |
| Aspiration | **흡인** | |
| Drainage | **배액** | |
| Insertion | **삽입** | |
| Replacement | **치환** (definitive) / **교환** / **교체** (routine) | |
| Removal | **제거** | |
| Revision | **교정** | |
| Thrombectomy | **혈전 제거(술)** | |
| Lithotripsy | **결석 파쇄술** | |
| Closure | **봉합** / **폐쇄** | |
| Fixation | **고정** | |
| Ligation | **결찰** | |
| Cauterisation / Ablation | **소작** / **지짐** / **절제** | Modality-dependent. |
| Examination / Test | **검사** | |
| Measurement | **측정** | |
| Therapy | **치료** / **요법** | |

#### Approach / method modifiers (SME-canonical)

| English | Korean |
|---|---|
| Percutaneous | **피부 경유** (or 경피) |
| Transcatheter | **도관 경유** (or 카테터 경유) |
| Transluminal (artery/vein context) | **혈관 경유** |
| Transluminal (other tubular organs) | **내강 경유** |
| Transapical | **심첨 경유** |
| Transthoracic | **경흉부** |
| Transcranial | **경두개** |
| Laparoscopic | **복강경** |
| Laparoscopic-assisted | **복강경 보조** |
| Endoscopic | **내시경** |
| Cystoscopic | **방광경하** |
| Under [X] guidance | **[X] 유도하** |
| Using [device] | **[device] 이용 / [device] 사용** |
| Via [route] | **[route] 통한 / [route]로** |

**Approach precedes the rest:** `복강경 막창자꼬리 절제`,
`피부 경유 간의 흡인`, `투시 유도하 신루관 교체`.

#### Combined procedures: "with", "and", "by", "using"

**`with` (subordinate concurrent step) → `동반`, order reversed** — the
secondary procedure first, then `동반`, then the main procedure:
`Hemigastrectomy with vagotomy` → `미주 신경 절단술 동반 반 위절제`.

**`and` / `with` (parallel equal procedures) → `및`, original order**:
`Total abdominal colectomy with ileostomy` →
`배 전체 잘록 창자 절제술 및 돌창자 창냄술`.

**`by [approach]` → `[approach]에 의한 [procedure]`.**

**`using [device or guidance]` → `[device] 이용 [procedure]` or
`[guidance] 유도하 [procedure]`.** Bare nominal `이용` — never
`이용한` / `이용하여`.

**Critical:** never use `동반` for `by`, `using`, `via`, `through`, or
`under guidance`; clauses join without commas.

#### Total / Subtotal / Partial / Laterality

| English | Korean |
|---|---|
| Total | **전체** (or **완전**) |
| Subtotal | **부분** / **대부분** |
| Partial | **부분** |
| Distal / Proximal | **먼쪽** / **몸쪽** (원위부 / 근위부 acceptable) |
| Left / Right / Bilateral | **왼쪽** / **오른쪽** / **양측** |

Quantifiers and laterality precede the site: `먼쪽 부분 췌장 절제`,
`왼쪽 궁둥 신경 자기 공명 영상`.

#### Education / counselling / therapy

`... 교육`, `... 상담`, `... 요법` (named) / `... 치료` (generic).

### Worked examples

| SCTID | English PT | Korean |
|---|---|---|
| 80146002 | Excision of appendix | 충수 절제술 |
| 73761001 | Colonoscopy | 결장 내시경술 / 대장 내시경 검사 |
| 18027006 | Transplantation of liver | 간 이식 |
| 401004 | Distal subtotal pancreatectomy | 먼쪽 부분 췌장 절제 |
| 306005 | Echography of kidney | 신장 초음파 검사 |
| 431648005 | Transcranial Doppler ultrasonography | 경두개 도플러 초음파 검사 |
| 30439001 | Venography of inferior vena cava with serialography | 연속촬영술 동반 하대 정맥 조영 |
| 444399007 | Radionuclide imaging with CT attenuation correction and localization | 컴퓨터 단층 촬영 감쇠 보정 및 위치 파악 방사성 핵종 영상 |

### Additional rules (from error analysis)

**Avoid phonetic transliteration for established concepts**
(`데브리망` → `죽은 조직 제거`; `플라즈마페레시스` → `혈장분리 교환`).

**Maintain specific-vs-generic structure distinctions** (`ureterocele`
is not "ureteral cyst").

**Distinguish anastomosis (`연결`/`문합`) from stoma creation
(`창냄술`).**

**Do not add clinical or administrative detail not in the source.**
