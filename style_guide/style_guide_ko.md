# Korean SNOMED CT translation style guide (DRAFT)

> **Status:** First-pass empirical draft, derived from analysis of the
> SNOMEDCT-KR national release **KR1000267_20251215** (3,693 procedure
> concepts with preferred Korean synonyms). Patterns described here reflect
> what the existing KR extension *does*, not what KHIS has formally
> documented. **Must be validated with KHIS before being treated as
> authoritative.** Where rules are clearly inconsistent in the source data,
> that is noted in **Open questions** sections.
>
> Modelled on the Estonian style guide ([style_guide.md](style_guide.md))
> for parity with the existing translation pipeline. Sections covering
> hierarchies other than `procedure` are stubs until more reference data
> is available.

---

# general

**Term length**

Maximum 255 characters, matching SNOMED CT specification. Definitions may be longer.

**Script and case**

Korean terms are written in Hangul (한글). Hangul has no case distinction,
so capitalisation rules do not apply within the Korean text. Latin
characters that appear inside a Korean term (gene symbols, drug names,
chemical formulae, eponyms) preserve the case used in the source.

**Spacing (띄어쓰기)**

Korean terms in the KR extension are predominantly **space-separated by
word unit**, following modern Korean orthographic conventions:

- `컴퓨터 단층 촬영` (Computed tomography), not `컴퓨터단층촬영`
- `자기 공명 영상` (Magnetic resonance imaging)
- `부분 위 절제` (Partial gastrectomy)

However, well-established medical compounds and short procedural nouns
are often written without spaces:

- `절제술` (excision/operation), `내시경술` (endoscopy), `생검` (biopsy),
  `측정` (measurement) — never internally spaced.
- Eponymous and short single-word procedures: `복강경` (laparoscopic),
  `흡인` (aspiration), `봉합` (suture), `연결` (anastomosis).

**Rule of thumb:** Default to space-separated word units. Do not insert
spaces inside fixed nominalisations ending in `-술`, `-법`, `-검`,
`-증`, `-염`. When in doubt, follow the spacing pattern in the source
data for the closest matching term.

**Punctuation and symbols**

Encoding is UTF-8. Korean terms generally do **not** end in punctuation.
Commas are rare and used only in list-like constructions inherited from
the SNOMED FSN (e.g. `Glucose measurement, serum` → `혈청 포도당 측정`,
where the Korean reorders rather than retaining the comma).

Hyphens are preserved inside hyphenated foreign names (`Lloyd-Davies`,
`Sauer-Bacon`, `M-mode`, `25-OH`).

**Numbers**

Arabic numerals throughout. Roman numerals are not used for procedures
in the observed data; if needed for cranial nerves or staging in other
hierarchies, follow the convention of the relevant Korean clinical
classification.

**Abbreviations and Latin loan words**

The KR extension keeps a small but consistent set of items in Latin
script (~3.6% of procedure terms contain Latin characters):

- **Eponymous procedures** keep the surgeon's name in Latin and place it
  *after* the procedural description, often joined by `수술` (operation):
    - `Lloyd-Davies operation, abdominoperineal resection` → `복회음 절제 Lloyd-Davies 수술`
    - `Polya operation, gastrectomy` → `위 절제 Polya 수술`
    - `Ramstedt operation, pyloromyotomy with wedge resection` → `Ramstedt 수술, 쐐기 절제 동반한 날문 근육 절개`
- **Gene/marker symbols** are preserved verbatim: `HER2`, `AFB`.
- **Chemical / radioisotope names** keep their Latin form when no
  established Korean equivalent exists: `Iobenguane (123-I)`, `M-mode`.
- **Hepatitis virus letters** are kept in Latin and combined with the
  Sino-Korean form: `B형 간염` (Hepatitis B), `C형 간염 항체`.
- **Vitamins** keep the Latin letter and number: `비타민 B12`, `25-OH 비타민D`.
- **Chemical / biochemical analytes** use the **established Korean
  phonetic transliteration** of the Latin/English name. **Do not
  back-translate** to a descriptive Korean compound.
    - `Carboxyhemoglobin` → `카복시헤모글로빈` (transliteration), **not**
      `일산화탄소헤모글로빈` (carbon-monoxide-hemoglobin descriptive form).
    - `Ferritin` → `페리틴`. `Insulin` → `인슐린`. `Triglycerides` → `중성 지방`
      (this one is the conventional Korean term, not transliterated).
    - When in doubt, prefer transliteration of the English name over a
      descriptive Korean compound, unless the descriptive form is the
      established Korean clinical term (e.g. `중성 지방` for triglycerides).

**Singular and plural**

Korean does not mark plural obligatorily. Use the bare noun form
regardless of whether the source FSN is singular or plural unless
plurality is semantically essential.

**Parentheses**

Avoid unless they appear in the source FSN and removing them would lose
information. The KR extension uses parentheses very sparingly in
procedure names.

---

# body structure

> **Stub.** Body-structure rules need development with KHIS. The single
> most important question is whether to prefer **pure Korean (고유어)** or
> **Sino-Korean (한자어)** anatomical names, since the KR extension
> currently uses both inconsistently:

| English | Sino-Korean (한자어) | Pure Korean (고유어) | Both seen |
|---|---|---|---|
| appendix | 충수 | 막창자꼬리 | ✓ |
| kidney | 신장 | 콩팥 | ✓ |
| colon | 결장 | 잘록 창자 | ✓ |
| ileum | 회장 | 돌창자 | ✓ |
| rectum | 직장 | 곧 창자 | ✓ |
| thorax/chest | 흉부 | 가슴 | mostly 가슴 |
| abdomen | 복부 | 배 | both |
| clavicle | 쇄골 | 빗장뼈 | mostly pure |
| sternum | 흉골 | 복장뼈 | mostly pure |
| mediastinum | 종격 | 세로칸 | mostly 세로칸 |
| prostate | 전립선 | 전립샘 | both |
| omentum | 대망 | 그물막 | mostly pure |
| tibia | 경골 | 정강뼈 | mostly pure |
| incus | 침골 | 모루뼈 | mostly pure |

Observed trend in the data: **modern KR extension authoring leans
toward pure Korean (고유어) terms**, which aligns with the Korean
Association of Anatomies' standardisation effort. The extension is
not yet consistent, however, and Sino-Korean forms remain common
where the pure form is unfamiliar to clinicians.

**Practical rule for translation (until KHIS issues definitive guidance):**

Use the **Sino-Korean (한자어) form by default** for anatomical sites,
because it has higher exact-match rates against the existing KR reference
data. Specifically:

- `appendix` → **충수** (not 막창자꼬리)
- `cecum` → **맹장** (not 막창자)
- `mesentery` → **장간막** (not 창자간막)
- `axilla` → **겨드랑이** (this one IS pure Korean — it is the standard
  reference term, no Sino-Korean alternative is used in KR)
- `colon` → **결장** (or `대장` for "large intestine")
- `kidney` → **신장** (`콩팥` is acceptable but `신장` is more frequent
  in the reference set)
- `prostate` → **전립샘** (the partially-pure form is the reference)
- `mediastinum` → **세로칸** (here pure Korean IS the reference)
- `clavicle`, `sternum`, `tibia`, `incus`: pure Korean (`빗장뼈`,
  `복장뼈`, `정강뼈`, `모루뼈`) — these are well-established reference
  forms.
- **Surface anatomy / limb regions: prefer pure Korean.**
    - `thigh` → **넓적다리** (not 허벅지, not 대퇴부)
    - `lower leg` → **종아리**
    - `upper arm` → **위팔**
    - `forearm` → **아래팔**
    - `wrist` → **손목**, `ankle` → **발목**
    - `palm` → **손바닥**, `sole` → **발바닥**
    - `axilla` → **겨드랑이**

**Heuristic:** When both forms exist, pick whichever was used in the
KR reference for the *closest matching* concept. Empirically, for
internal organs and viscera the Sino-Korean form is more often
canonical; for **bones and surface anatomy** (clavicle, sternum,
mediastinum) the pure Korean form is more often canonical.

**Open questions for KHIS:**

- Is there an official preference (pure Korean PT, Sino-Korean accepted
  synonym) or is co-existence the intended state?
- Which reference is authoritative — the KAA anatomy guide (the
  `Terms_from_KoreanAssociation_of_Anatomies.pdf` reference in this
  repo), KOSTOM, or KCD-8?
- For combined-name structures (`기관지`, `요관`, `십이지장`) is there
  any guidance on splitting vs. compounding?

---

# finding

> **Stub.** Needs reference data. The KR extension contains a much
> larger volume of finding/disorder translations than procedures, but
> we have not yet built an eval set for this hierarchy. KHIS-internal
> mapping work between SNOMED and KCD-8 (Korean ICD-10 variant) is the
> most likely existing reference and should be requested.

---

# observable entity

> **Stub.**

---

# organism

> **Stub.** General SNOMED CT practice keeps Latin binomial names for
> organisms, with Korean common names as synonyms. Confirm with KHIS.

---

# pharmaceutical / biologic product

> **Stub.** The Ministry of Food and Drug Safety (식약처) maintains
> Korean drug name guidance. Defer to that source.

---

# procedure

### General principles

Korean is a head-final SOV language, so the **procedural action / modality
appears at the end** of the term, opposite to most English FSNs. This
applies recursively to nested modifiers. The KR extension is highly
consistent on this point.

- **Anatomical site → action**:
  `Excision of appendix` → `충수 절제`
  (literally: appendix-excision)
- **Modifier → site → action**:
  `Magnetic resonance imaging of pelvis` → `골반 자기 공명 영상`
- **Approach → modifier → site → action**:
  `Percutaneous core needle biopsy of liver` → `피부 경유 간의 중심부 바늘 생검`

Other principles observed in the KR extension:

- Use **nominalised verbs** (`-술`, `-검`, `-법`) rather than verbal forms.
- **Avoid long unspaced compounds**; prefer space-separated word units
  for readability and searchability, except for fixed nominalisations.
- Do **not** translate the same English word two different ways within
  one term unless the source distinguishes them.
- **Default to no particles between site and action.** The genitive
  `의` is **omitted** in the KR extension's preferred terms more often
  than not. Write `간 배액`, not `간의 배액`. Write `유방 병변 절제`,
  not `유방 병변의 절제`. Only insert `의` if removing it creates an
  unambiguous parsing problem.
- **`-술` (operation suffix) discipline.** Many KR preferred terms use
  the bare nominal form (`절제`, `절개`, `생검`, `배액`) **without**
  appending `-술`. Default to the bare form. Only append `-술` for the
  following **fixed compounds** where `-술` is part of the established
  term, or where the source FSN explicitly says "operation":
    - `내시경술` (endoscopy), `우회술` (bypass), `절단술` (amputation)
    - **`창냄술`** (stomy / ostomy creation — `장 창냄술`, `결장 창냄술`,
      `돌창자 창냄술`, `위 창냄술`). Always use `-술` for ostomy
      creation procedures.
    - `조성술`, `형성술` (creation/formation procedures — `장루 조성술`,
      `J형 회장낭 조성술`)
    - `이식술` (transplantation, optional — `이식` alone is also common)
    - `치환술`, `교환술` (replacement procedures, optional)
    - `검사` is **not** suffixed with `-술` (it is already a noun).
- **Do not introduce extra `검사`, `시술`, or other generic action
  nouns** that are not in the source. `Urine culture` → `소변 배양`,
  not `소변 배양 검사`. `Pregnancy detection examination` → `임신검사`,
  not `임신 검출 검사`.
- **Do not drop modality qualifiers.** If the source says `Doppler
  ultrasonography`, the Korean must include `도플러`. If the source says
  `fine needle biopsy`, the Korean must include `가는 바늘` or `세침`.
- **Past-tense verbs are not used** (consistent with the Estonian guide).

**Recommended sources**

- **KOSTOM** (Korean Standard Terminology of Medicine), maintained by
  KHIS — primary reference.
- **KCD-8** procedure code descriptions (Korean ICD variant) — for
  procedures performed and reimbursed in Korea.
- **HIRA fee schedule terminology** (건강보험심사평가원) — reflects
  actual hospital usage.
- **Korean Association of Anatomies** standardised terms — for
  anatomical site names.
- **KHIS-managed SNOMEDCT-KR national release** (KR1000267) — for any
  term already translated, this is the canonical reference.

### Rules and patterns

#### Surgical actions (verb-equivalents)

| English | Korean | Notes |
|---|---|---|
| Excision / -ectomy | **절제** (or **절제술** for "operation") | Most common procedural action (637 occurrences). Use bare `절제` for the act, append `술` when emphasising "operation". |
| Incision / -otomy | **절개** (or **절단** for cutting through) | 189 occurrences. Distinguish from `절제` (which implies removal). |
| Biopsy | **생검** | 215 occurrences. Always one word. |
| Suture | **봉합** | |
| Repair | **복구** (general) / **성형** (plastic/reconstructive) | Use `성형` when the source says "plastic repair" or "reconstruction". |
| Reconstruction | **재건** | Often combined: `재건 성형`. |
| Anastomosis | **연결** (or **문합** for some bowel anastomoses) | `연결` is preferred in newer entries. |
| Bypass | **우회술** / **두름길 조성** | |
| Aspiration | **흡인** | |
| Drainage | **배액** | |
| Insertion | **삽입** | |
| Replacement | **치환** (definitive) / **교환** / **교체** (catheter etc.) | Choice depends on whether the replacement is permanent (use `치환`) or routine maintenance (use `교환`/`교체`). |
| Removal | **제거** | |
| **Revision** (of a previous procedure) | **교정** | Not `수정`, not `재시술`, not `재시행`. |
| **Supervision** | **감독** | Not `지도`. |
| **Support** (of patient) | **지지** | |
| **Closure** (of fistula, defect, wound) | **봉합** (suture-based) / **폐쇄** (general/non-suture) | Default to `봉합` for surgical closure of an opening. |
| **Giving / Administration** (of enema, etc.) | bare action noun, no patient subject | `Giving patient an enema` → `관장` (not `환자 관장`). Drop the patient subject. |
| Fixation | **고정** | |
| Ligation | **결찰** | |
| Cauterisation / Ablation | **소작** / **지짐** / **절제** depending on modality | |
| Examination / Test | **검사** | Generic catch-all; 266 occurrences. |
| Measurement | **측정** | 126 occurrences. |
| Education | **교육** | |
| Counselling | **상담** | |
| Therapy | **치료** / **요법** | `요법` for named therapy types (e.g. `행동 요법`, `저온 요법`); `치료` for general treatment. |

#### Imaging modality patterns

These translations are highly standardised — the LLM should not
invent variants:

| English | Korean | Notes |
|---|---|---|
| Computed tomography (CT) | **컴퓨터 단층 촬영** | Always 3 spaced words. |
| Magnetic resonance imaging (MRI) | **자기 공명 영상** | Sometimes unspaced `자기공명영상`, but spaced is more common. |
| Ultrasound / Ultrasonography / Echography | **초음파 검사** | "Echography" → `초음파 검사` (not `에코그래피`). |
| Radiography / X-ray | **방사선 영상 촬영** | |
| Angiography | **혈관 조영** | |
| Scintigraphy / radionuclide imaging | **방사성 핵종 영상** | |
| Fluoroscopy | **투시** | |
| Endoscopy / -scopy | **내시경술** (or **내시경 검사**) | |

**Site-name precedes modality**:
`Computed tomography of brain` → `뇌 컴퓨터 단층 촬영`
`Magnetic resonance imaging of prostate` → `전립샘 자기 공명 영상`
`Ultrasonography of breast` → `유방 초음파 검사`

**Combined / compound modalities follow English order.**
When a modality is combined with a sub-modality (e.g. CT + angiography),
keep them in **the same order as English**: base modality first, then
sub-modality.

| English | Korean |
|---|---|
| Computed tomography angiography with contrast | 조영제 사용 컴퓨터 단층 촬영 혈관 조영 |
| Magnetic resonance angiography | 자기 공명 혈관 조영 |
| Doppler ultrasonography of vein of lower limb | 하지 정맥 도플러 초음파 촬영 |

Do **not** reorder to put `혈관 조영` (angiography) before `컴퓨터 단층
촬영` (CT). The CT/MRI base comes first.

#### Approach / method modifiers

| English | Korean |
|---|---|
| Laparoscopic | **복강경** |
| Laparoscopic-assisted | **복강경 보조** |
| Percutaneous | **피부 경유** |
| Endoscopic | **내시경** |
| Cystoscopic | **방광경하** |
| Transthoracic | **경흉부** |
| Open (surgery) | **개방** (rare; usually omitted as the default) |
| Under [X] guidance | **[X] 유도하** (very common, 81+ occurrences) |
| With contrast | **조영제 사용** |
| Without contrast | **조영제 미사용** |
| Using [device] | **[device] 이용 / [device] 사용** |
| Via [route] | **[route] 통한 / [route]로** |

**Approach precedes the rest**:
`Laparoscopic appendectomy` → `복강경 막창자꼬리 절제`
`Percutaneous aspiration of liver` → `피부 경유 간의 흡인`
`Replacement of nephrostomy tube using fluoroscopic guidance` → `투시 유도하 신루관 교체`

#### Combined procedures: "with", "and", "by", "using"

These English connectors map to **different** Korean constructions.
Do not conflate them.

**`with` (subordinate step) → `동반`, with order reversed.**
Only use this construction for the literal English word **with** that
introduces a subordinate concurrent procedure. The secondary procedure
is named *first*, followed by `동반`, followed by the main procedure.

| English | Korean |
|---|---|
| Hemigastrectomy with vagotomy | 미주 신경 절단술 동반 반 위절제 |
| Partial colectomy with anastomosis | 연결 동반 결장 부분 절제 |

**`and` or `with` (parallel equal procedures) → `및`, original order.**

| English | Korean |
|---|---|
| Total abdominal colectomy with ileostomy | 배 전체 잘록 창자 절제술 및 돌창자 창냄술 |

**`by [approach]` → `[approach]에 의한 [procedure]`.** Approach first,
no `동반`, no comma, no reversal of the procedure name itself.

| English | Korean |
|---|---|
| Excision of lesion of rectum by transanal minimal invasive surgery | 경항문 최소 침습 수술에 의한 직장 병변 절제 |

**`using [device or guidance]` → `[device] 이용 [procedure]` or
`[device] 유도하 [procedure]`.** Device/guidance first, no `동반`.

**Critical:** use the **bare nominal** `이용`, not the adnominal form
`이용한` or `이용하여`. Do **not** insert verb endings, suffixes, or
particles between `이용` and the procedure noun.

| English | Korean |
|---|---|
| Biopsy of peritoneum using computed tomography guidance | 컴퓨터 단층 촬영 유도하 복막 생검 |
| External beam radiation therapy using electrons | 전자 이용 외부 빔 방사선 치료 |
| Anastomosis of colon to rectum using staples | 봉합기 이용 결장 직장 연결 |
| Repair of gastroschisis with prosthesis | 인공삽입물 이용 복벽갈림증 복구 |

**Critical:** **never** use `동반` for `by`, `using`, `via`, `through`,
or `under guidance`. `동반` is reserved for literal `with` introducing a
*concurrent surgical step*. If in doubt, do **not** reverse word order
and do **not** insert a comma — keep the English structure: modifier
clause → site → action.

**Critical:** the secondary clause and main clause must be joined
**without a comma**. `직장 병변 절제, 경항문 최소 침습 수술` is wrong.
The Korean rendering is one continuous noun phrase.

#### Total / Subtotal / Partial

| English | Korean |
|---|---|
| Total | **전체** (or **완전** in some contexts) |
| Subtotal | **부분** / **대부분** |
| Partial | **부분** |
| Distal | **먼쪽** (pure) / **원위부** (Sino) — both used |
| Proximal | **몸쪽** (pure) / **근위부** (Sino) — both used |

These quantifiers precede the anatomical site:
`Distal subtotal pancreatectomy` → `먼쪽 부분 췌장 절제`
`Total replacement of hip` → `전체 엉덩관절 치환`

#### Laterality

| English | Korean |
|---|---|
| Left | **왼쪽** (77 occurrences) |
| Right | **오른쪽** (74 occurrences) |
| Bilateral | **양측** |

Laterality precedes the site:
`Magnetic resonance imaging of sciatic nerve` → `왼쪽 궁둥 신경 자기 공명 영상`

#### Education / counselling / therapy

These map cleanly:

- `... education` → `... 교육`
- `... counseling` → `... 상담`
- `... therapy` → `... 요법` (for named systematic therapies) or `... 치료` (generic)
- `Guidance / instruction` → `... 교육` or `... 지도`

Examples:
`Diet education` → `식이 교육`
`Genetic counseling` → `유전 상담`
`Cold therapy` → `저온 요법`
`Behavioral therapy` → `행동 요법`

### Open questions (procedure)

- **`절제` vs `절제술`**: when does a procedure earn the `-술` suffix?
  The current data uses both, sometimes for similar concepts. We need
  KHIS guidance, otherwise the LLM will be inconsistent.
- **`복구` vs `성형` vs `봉합`** for "Repair": the eval data shows
  `Repair of stomach` → `위 복구`, `Repair of laceration of gallbladder`
  → `담낭 봉합`, `Repair of ovary` → `난소 성형`, `Plastic repair with
  reconstruction of stomach` → `위 재건 성형 복구`. The choice appears
  to depend on whether the repair is generic, suture-based, or plastic
  — but the data is sparse and not always self-consistent.
- **Particle `의`** (genitive): when to use vs omit. Both `간 생검` and
  `간의 생검` appear; we need a rule.
- **`복강경 보조`** vs **`복강경 보조한`**: rare adnominal form
  variation.
- **Generic vs anatomically-specific naming**: e.g. when does `appendix`
  get translated as `충수` (appended-bit) vs `막창자꼬리` (cecum-tail)?

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

---

# qualifier value

> **Stub.**

---

# situation with explicit context

> **Stub.**

---

# substance

> **Stub.** Defer to MFDS / 식약처 ATC and substance-name guidance.

---

# Other hierarchies

Stubs to be developed: `environment or geographical location`,
`event`, `physical force`, `physical object`, `record artifact`,
`social context`, `specimen`, `staging and scales`.

---

# Provenance and methodology note

This draft was constructed by:

1. Reading the Estonian style guide ([style_guide.md](style_guide.md))
   for structure.
2. Parsing the SNOMEDCT-KR national release file
   `sct2_Description_Snapshot-ko_KR1000267_20251215.txt` and the
   corresponding language reference set, restricted to active preferred
   Korean synonyms.
3. Extracting all 3,693 procedure-domain concepts (descendants of
   `71388002 |Procedure (procedure)|`) that have a preferred Korean
   translation.
4. Grouping these by English keyword (excision, incision, biopsy,
   imaging modality, approach modifier, etc.) and identifying the most
   common Korean rendering for each pattern.
5. Where the source data is internally inconsistent, recording it as an
   **open question** rather than picking a winner.

**Coverage gap:** The KR extension only translates ~6.25% of all
SNOMED procedure concepts, so this draft cannot speak to procedure
terminology that has not yet been touched by KHIS authors. As more of
the procedure hierarchy is translated, the rules above should be
revisited for consistency.
