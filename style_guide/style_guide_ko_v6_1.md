# Korean SNOMED CT translation style guide (v6.1)

> v6.0 revised against the SME terminologist's round-3 review (120-row
> blinded sample of the 5,012 imaging concepts, received 2026-08-19).
> The corrections that supersede v6.0: (1) **투시 유도하 only when the
> source says guidance/guided** — adjectival "fluoroscopic [study]" is
> `투시 [study]` (투시 혈관 조영, 투시 정맥 조영); (2) **transluminal
> (vascular) = 혈관내**, reversing v6.0's 혈관 경유; (3) **plain X-ray
> must include 방사선** (일반/단순 방사선 촬영, not bare 단순 촬영);
> (4) preferred terms **drop -술** on 조영/성형/촬영/측정 (the -술 form
> stays acceptable as a synonym); (5) new word-order templates for
> purpose, time modifiers, and guided procedures.

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
| limb / extremity (unspecified) | **사지** | 팔다리 |
| upper arm (specifically arm above elbow) | **위팔** | — |
| forearm | **아래팔** | — |

**위팔 is reserved for the upper arm segment; do not use it for "upper
limb/extremity" as a whole.**

**Hip (SME ruling, round 3).** "Hip" is ambiguous in English; Korean
must pick the referent. **`엉덩이` = hip region; `엉덩 관절` (or
`고관절`) = hip joint.** Resolve from the concept's procedure site, not
the words: imaging of "hip" (CT, MRI, DXA, ultrasound, plain X-ray)
refers to the **hip joint** in the literature and in the SNOMED concept
model, so default imaging-of-hip to `엉덩 관절` unless the concept's
site is explicitly the region. Never use `엉덩뼈` for hip — 엉덩뼈 is
the ilium (a bone).

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
| Fluoroscopy (standalone examination) | **투시 검사** (or 투시) | |
| Fluoroscopy guidance | **투시 유도하** | ONLY when the source says guidance/guided. |
| Fluoroscopic [study] (adjectival) | **투시 [study]** | See rule below — never 투시 유도하. |
| Angiography (with a named artery/vein) | **[vessel] 혈관 조영** | e.g. 관상 동맥 혈관 조영 |
| Angiography (no vessel named) | **동맥 조영** | |
| Venography | **정맥 조영** | |
| Arteriography | **동맥 조영** | |
| Radionuclide imaging / scintigraphy | **방사성 핵종 영상** | |
| Radionuclide study | **방사성 핵종 검사** | |
| Positron emission tomography | **양전자 방출 단층 촬영** | |
| PET-CT (PET with CT) | **양전자 방출 단층 컴퓨터 단층 촬영** | One established compound. |
| SPECT-CT (SPECT with CT) | **단일 광자 방출 단층 컴퓨터 단층 촬영** | |
| Endoscopy / -scopy | **내시경술** (or 내시경 검사) | |

**Fluoroscopic [study] vs fluoroscopy guidance (SME ruling, round 3 —
supersedes earlier usage).** `투시 유도하` is licensed **only** when the
source contains *guidance* or *guided* (`using fluoroscopic guidance` →
`투시 유도하 …`). When *fluoroscopic* is an adjective on the study
itself, render it as `투시` directly before the study noun:

- `Fluoroscopic angiography` → **`투시 혈관 조영`**
- `Fluoroscopic venography` → `투시 정맥 조영`
- `Fluoroscopic herniography` → `투시 탈장 조영`
- `Fluoroscopic cystometrography` → `투시 방광내압측정`
- `Fluoroscopy, serial films` → `연속 촬영 투시`

Placement: contrast first, then the vessel/site, then `투시 [study]`:
`Fluoroscopic angiography of bronchial artery with contrast` →
`조영제 사용 기관지 동맥 투시 혈관 조영`.

**Plain X-ray (SME ruling, round 3 — supersedes v6.0).** Plain
radiography must contain `방사선`: **`일반 방사선 촬영`** or
`단순 방사선 촬영` — never bare `단순 촬영` and never bare `X선`.
`Plain X-ray of forearm` → `아래팔 단순 방사선 촬영`. Likewise
**mammography = `유방 방사선 촬영`** (not 유방 촬영술).

**-술 in preferred terms (SME ruling, round 3).** In the preferred term,
imaging and interventional heads drop `-술`: `조영` (not 조영술),
`혈관 성형` (not 혈관 성형술), `연속 촬영`, `측정`, `제거`, `감압`.
The `-술` form remains an acceptable **synonym**, not the PT.

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
| Transluminal (artery/vein context) | **혈관내** (SME round 3 — reverses v6.0's 혈관 경유) |
| Transluminal (other tubular organs) | **내강 경유** |
| Translumbar | **허리경유** |
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

**Ordering template for guided procedures (SME ruling, round 3):**

```
[guiding device] 유도하 → [route] → [body site] → [method/test]
```

`Percutaneous core needle biopsy of breast using stereotactic guidance` →
`입체정위 유도하 피부 경유 유방 중심부 바늘 생검`. The route
(피부 경유, 혈관내) comes directly after the guidance phrase and
**before** the body site: `컴퓨터 단층 촬영 유도하 피부 경유 췌장 병변
가는 바늘 흡인 생검`.

**Purpose clauses (SME ruling, round 3).** A stated purpose is rendered
first as `[purpose]를 위한`, then the study:
`Computed tomography of thorax with contrast for radiotherapy planning` →
`방사선 치료 계획을 위한 조영제 사용 흉부 컴퓨터 단층 촬영`.

**Time modifiers (SME ruling, round 3).** Words describing when
(intraoperative `수술 중`, postoperative `수술 후`) come at the very
front, **before** the contrast phrase: `Intraoperative fluoroscopic
angiography ... with contrast ...` → `수술 중 조영제 사용 … 혈관 조영 …`.

**Urgency (SME ruling, round 3).** `stat` = `응급`, ordered
urgency + organ + method: `Isotope stat scan parathyroid` →
`응급 부갑상샘 동위원소 스캔`.

**Redundant repeated stems (SME ruling, round 3).** If translating both
words would repeat a stem, drop one occurrence: `Arthrogram of spinal
joint` → `척추 관절 조영상` (not 척추 관절 관절 조영상); CT discography
with injection into the disc → one `추간판`, not two.

**"with [substance] infusion/injection" where *with* means *using*
(SME ruling, round 3):** no `동반` — `Ultrasonography of uterus with
saline infusion` → `식염수 주입 자궁 초음파 검사`.

**Particles.** Drop `의` unless required for parsing: `담즙 식도 역류`
(not 담즙의 식도 역류).

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

### Round-3 SME glossary (2026-08-19) — use these exactly

| English | Korean | Notes |
|---|---|---|
| cutting balloon | **칼날 풍선** | not 절단 풍선 |
| cone (beam) | **원뿔 빔** | not 원추형 |
| slit-beam | **슬릿 빔** | established loanword |
| extended (of a test/evaluation) | **정밀** | not 확장 |
| ophthalmoscopy | **안저 검사** | 검안경 검사 acceptable |
| stat | **응급** | |
| renogram | **신장 기능도** | not 신장 영상 |
| intrathecal | **수막내** | not 수막공간내 |
| ablation | **절제** | |
| focused assessment (FAST) | **표적 평가** | 외상환자 초음파 표적평가 |
| image intensifier | **영상 증강장치** | not 영상 증폭기 |
| rotary cutter | **회전 절삭기** | not 회전 절단기 |
| nailing (fracture) | **못 고정** | not 못 박기 |
| brachytherapy | **근접 방사선치료** | or 근접 치료 |
| dialysis fistula | **투석루** | or 투석 혈관 |
| electrocardiography gated | **심전도 동기** | not 심전도 게이팅 |
| myocardial rest (study) | **심근 휴식기** | not 심근 안정 |
| under stress | **부하상태** | not 스트레스 부하 |
| upper gastrointestinal tract | **상부 위장관** | 상부 first |
| small bowel follow through | **소장 통과 검사** | |
| sialogram | **침샘 조영** | parotid = 귀밑샘 |
| loopogram | **루프 조영** | 인공요로 조영 acceptable |
| limited area | **국소 부위** | not 제한적 (for area) |
| decompression | **감압** | |
| intervertebral disc | **추간판** | 척추사이 원반 acceptable |
| pressure of [vessel] | **[vessel]압** | 간정맥압 측정 |
| plethysmography | **혈량 측정** | 음경 혈량 측정 |
| using [substance/tracer/agent] | **[substance] 사용** | 사용, not 이용 (이용 is for devices) |
| Tc99m | **테크네튬-Tc99m** | spell the element |
| iodine 123 | **아이오딘-123** | not 요오드 123 |
| superior mesenteric artery | **상장간막동맥** | 위창자간막동맥 acceptable |
| inferior epigastric artery | **아래배벽동맥** | not 복벽 |
| common iliac artery | **온엉덩동맥** | 총장골동맥 acceptable |
| axillofemoral | **겨드랑대퇴** | 액와대퇴 acceptable |
| profunda femoris artery | **깊은 넓다리 동맥** | |
| graft | **이식편** | |
| closure | **폐쇄** | 봉합 acceptable |
| chemical (adjectival) | **화학적** | not 화학 |
| for ascites (indication) | **복수 확인** | state what the test checks |

### Additional rules (from error analysis)

**Avoid phonetic transliteration for established concepts**
(`데브리망` → `죽은 조직 제거`; `플라즈마페레시스` → `혈장분리 교환`).

**Maintain specific-vs-generic structure distinctions** (`ureterocele`
is not "ureteral cyst").

**Distinguish anastomosis (`연결`/`문합`) from stoma creation
(`창냄술`).**

**Do not add clinical or administrative detail not in the source.**
