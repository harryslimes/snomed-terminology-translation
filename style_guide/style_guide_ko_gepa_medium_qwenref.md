# Korean SNOMED CT Translation Style Guide (v5.4)

> **Update Note (v5.4):** Incorporates critical corrections from v5.3 QA feedback regarding laterality terminology preferences, fixed compound spacing enforcement for lymphography, and marker terminology standardization.
> 1.  **Laterality Preference Hierarchy:** While both `오른쪽/왼쪽` and `우측/좌측` are linguistically valid, **`우측/좌측` is the PREFERRED standard** for internal anatomical structures in SNOMED CT KR extension when no specific exemplar dictates otherwise. Use `오른쪽/왼쪽` primarily for surface anatomy or when explicitly matched to an accepted reference.
>     *   `Right hip` → **우측 고관절** (Preferred over 오른쪽 고관절)
>     *   `Left foot` → **왼쪽 발** (Surface anatomy; Pure Korean preferred)
> 2.  **Lymphogram Compound Enforcement:** `림프조영상` is a **FIXED COMPOUND**. Write as one word with NO spaces. Do NOT write `림프 조영상`. This aligns with the `-조영상` suffix discipline where the body part/modifier attaches directly to the suffix.
> 3.  **"Marker" Terminology Standardization:** Translate `Marker` in diagnostic/imaging contexts as **표시자**, NOT `표지자`. `표지자` is reserved for biological markers (e.g., tumor markers). In imaging/radiology contexts involving tracers or localization, `표시자` is the standardized term.
> 4.  **Exemplar Matching Priority:** When exemplars are provided, they take precedence over general style guide rules. If an exemplar shows `초음파 검사` (spaced) but the guide says `초음파검사` (fixed), follow the EXEMPLAR. The style guide applies only when no conflicting exemplar exists.

---

# General Principles

**Term Length.** Maximum 255 characters.

**Script and Case.** Korean terms are written in Hangul. Latin characters (gene symbols, drug names, eponyms) preserve source case.

**Spacing (띄어쓰기).**
*   **Default:** Space-separated by word unit (`컴퓨터 단층 촬영`, `자기 공명 영상`, `부분 위 절제`).
*   **Fixed Compounds (NO SPACES):** `절제술`, `내시경술`, `생검`, `측정`, `복강경`, `흡인`, `봉합`, `연결`, `초음파검사`, `림프조영상`.
*   **CRITICAL EXCEPTIONS:**
    *   `초음파검사` → FIXED. Write `초음파검사`, NEVER `초음파 검사` (unless exemplar dictates otherwise).
    *   `림프조영상` → FIXED. Write `림프조영상`, NEVER `림프 조영상`.
    *   `컴퓨터 단층 촬영` → SPACED. Write `컴퓨터 단층 촬영` (3 words). Do NOT write `컴퓨터단층촬영`.
*   **Rule of Thumb:** Default to spaces, but strictly adhere to the fixed compound list above. Do not insert spaces inside nominalisations ending in `-술`, `-법`, `-검`, `-증`, `-염`, `-조영상`.

**Punctuation.** UTF-8. No terminal punctuation. Hyphens preserved in foreign names (`Lloyd-Davies`, `M-mode`).

**Numbers.** Arabic numerals.

**Abbreviations & Latin Loan Words.**
*   **Eponyms:** Surgeon name in Latin *after* procedure (`복회음 절제 Lloyd-Davies 수술`).
*   **Genes/Markers:** Verbatim (`HER2`, `AFB`).
*   **Chemicals/Isotopes:** Latin if no established Korean equivalent (`Iobenguane (123-I)`).
*   **Hepatitis/Vitamins:** Latin letters kept (`B형 간염`, `비타민 B12`).
*   **Biochemical Analytes:** Use established Korean phonetic transliteration (`카복시헤모글로빈`, `페리틴`). Do not back-translate to descriptive compounds unless the descriptive form is the standard clinical term (`중성 지방` for Triglycerides).

**Singular/Plural.** Use bare noun form.

**Parentheses.** Avoid unless present in source FSN and essential.

---

# Body Structure

**Practical Rule:** Sino-Korean (한자어) default for internal organs/viscera. Pure Korean for bones/surface anatomy.

**Laterality Terminology Selection:**
| Context | Preferred Term | Alternative (Acceptable if Exemplar Matches) |
| :--- | :--- | :--- |
| Internal organs/joints (hip, liver, kidney) | **우측 / 좌측** | 오른쪽 / 왼쪽 |
| Surface anatomy (foot, hand, thigh, arm) | **오른쪽 / 왼쪽** | 우측 / 좌측 |
| Bilateral | **양쪽** | 양측 (only if exemplar requires) |

**Critical Anatomical Synonyms (Reference Data Alignment):**
When translating specific anatomical structures, you must use the term established in the KR reference data, even if other literal translations exist.

| English | Preferred Korean | Rejected / Non-Preferred Variants |
| :--- | :--- | :--- |
| Optic foramen | **시신경공** OR **시신경 구멍** | ~~시각신경공~~ (Non-standard synonym) |
| Omphalomesenteric duct | **배꼽 장관막관** OR **배꼽 창자간막관** | ~~배꼽융통관~~ (Low match rate) |
| Appendix | **충수** | ~~막창자꼬리~~ |
| Cecum | **맹장** | ~~막창자~~ |
| Mesentery | **장간막** | ~~창자간막~~ |
| Axilla | **겨드랑이** | (Pure Korean is standard) |
| Kidney | **신장** | `콩팥` is acceptable but `신장` is higher frequency |
| Prostate | **전립샘** | (Partially-pure form is reference) |
| Mediastinum | **세로칸** | (Pure Korean is reference) |
| Clavicle/Sternum/Tibia/Incus | **빗장뼈 / 복장뼈 / 정강뼈 / 모루뼈** | (Pure Korean forms required) |
| Thigh / Lower Leg | **넓적다리 / 종아리** | (Surface anatomy = Pure Korean) |
| Upper Arm / Forearm | **위팔 / 아래팔** | (Surface anatomy = Pure Korean) |
| Hip joint | **고관절** | ~~엉덩관절~~ (Lower frequency; use only if exemplar matches) |

---

# Procedure

### Syntax & Word Order
Korean is head-final SOV.
*   **Order:** [Contrast Modifier] + [Laterality] + [Site] + [Modality/Approach] + [Action/Suffix]
*   **Particles:** Omit genitive `의` between site and action (`간 배액`, NOT `간의 배액`). Only use if parsing is ambiguous.
*   **Nominalisation:** Use `-술`, `-검`, `-법` forms. Avoid verbal endings.

### `-술` Suffix Discipline
Default to **bare nominal** (`절제`, `절개`, `생검`, `배액`) without `-술`.
**Only append `-술` for these fixed compounds:**
*   `내시경술`, `우회술`, `절단술`
*   `창냄술` (ALWAYS for ostomy/stomy creation: `장 창냄술`, `결장 창냄술`)
*   `조성술`, `형성술` (creation/formation)
*   `이식술`, `치환술`, `교환술` (optional; bare forms also common)
*   *Note:* `검사` is never suffixed with `-술`.

### Radiology Specifics

#### Contrast Modifiers (Front-Loaded)
*   With contrast → **조영제 사용**
*   Without contrast → **조영제 미사용**
*   **Placement:** ALWAYS at the very front of the term.
    *   `조영제 미사용 경추 컴퓨터 단층 촬영` (Correct)
    *   `경추 컴퓨터 단층 촬영 조영제 미사용` (Incorrect)
*   Never drop "without contrast". Silence is not a valid translation.

#### Derivational Suffix Mapping
| English | Korean | Spacing Rule | Notes |
| :--- | :--- | :--- | :--- |
| -graphy | **조영(술)** (contrast) / **촬영(술)** (non-contrast) | Spaced from modifier | Load-bearing suffix. Never transliterate as *-그래피*. |
| -gram | **조영상** (contrast) / **영상** (non-contrast) | **FIXED to modifier** | Never transliterate as *-그램*. Attach directly: `림프조영상`, `혈관조영상`. |
| -otomy | **절개(술)** | Spaced | Incision |
| -ectomy | **절제(술)** | Spaced | Excision |
| -scopy | **내시경(술)** / **경 검사** | Spaced | Endoscopy |
| -metry | **측정(법)** | Spaced | Measurement |
| -plasty | **성형(술)** | Spaced | Reconstruction |
| -stomy | **창냄술** | Fixed | Stoma creation |
| -pexy | **고정(술)** | Spaced | Fixation |

**Unfamiliar -graphy/-gram Roots:** Decompose into [Body Part] + [조영(술)/조영상]. NEVER produce phonetic Hangul (*-그램*, *-그래피*). If decomposition fails, retain English Latin script.

#### Radiology Idioms
*   `symptomatic [study]` → **진단** (NOT 증상치료/증상성). Means "diagnostic due to symptoms".
*   `screening [study]` → **선별** (e.g., `선별 유방 영상`). Distinct from `진단`.
*   `limited [study]` → **제한적** (placed BEFORE study compound).
*   `diagnostic [study]` → **진단적** (Retain when explicitly stated in source to distinguish from screening/therapeutic).
*   Redundant `diagnostic` qualifier → Drop ONLY if completely implied and not contrasting with another intent.

#### Imaging Modalities (Standardized Forms)
| English | Korean | Spacing Note |
| :--- | :--- | :--- |
| Computed tomography | **컴퓨터 단층 촬영** | Always 3 words (SPACED) |
| Magnetic resonance imaging | **자기 공명 영상** | Spaced preferred |
| Ultrasound / Echography | **초음파검사** | **FIXED COMPOUND. NO SPACE.** |
| Radiography / X-ray | **방사선 영상 촬영** | Use `진단적 방사선 영상 촬영` if source says "diagnostic" |
| Angiography | **혈관 조영** | Spaced |
| Lymphography | **림프조영상** | **FIXED COMPOUND. NO SPACE.** |
| Scintigraphy | **방사성 핵종 영상** | Spaced |
| Fluoroscopy | **투시** | |
| Endoscopy | **내시경술** / **내시경 검사** | |
| Positron emission tomography | **양전자 단층 촬영** | Shortened form preferred over `양전자 방출 단층 촬영` in combined terms |

**Combined Modalities (CRITICAL ORDERING):**
In hybrid/combined imaging studies, follow the KR-extension reference ordering which often places CT first regardless of English source order.
*   `PET with CT` / `Positron emission tomography with computed tomography` → **컴퓨터 단층 촬영 동반 양전자 단층 촬영**
    *   Pattern: `[CT Modality] 동반 [Functional Modality]`
    *   Do NOT translate as `양전자 ... 및 컴퓨터 ...`
*   `CT angiography` → `컴퓨터 단층 촬영 혈관 조영` (Base modality first)

### Approach & Method Modifiers
*   Laparoscopic → **복강경**
*   Percutaneous → **피부 경유**
*   Under [X] guidance → **[X] 유도하**
*   Using [device] → **[device] 이용** (Use bare nominal `이용`, NOT `이용한`/`이용하여`)
*   Via [route] → **[route] 통한** / **[route]로**

### Connectors ("with", "and", "by", "using")
*   **`with` (subordinate concurrent step / combined modality):** Reverse order + `동반`.
    *   `Hemigastrectomy with vagotomy` → `미주 신경 절단술 동반 반 위절제`
    *   `PET with CT` → `컴퓨터 단층 촬영 동반 양전자 단층 촬영`
*   **`and` / `with` (parallel equal procedures/sites):** Original order + `및`.
    *   `Colectomy with ileostomy` → `결장 절제술 및 돌창자 창냄술`
    *   `Abdomen and pelvis` → `복부 및 골반`
*   **`by [approach]`:** `[approach]에 의한 [procedure]`. NO `동반`.
*   **`using [device/guidance]`:** `[device] 이용/유도하 [procedure]`. NO `동반`.
*   **CRITICAL:** Never use commas to join clauses. One continuous noun phrase.

### Quantifiers & Laterality
| English | Korean | Notes |
| :--- | :--- | :--- |
| Total | **전체** / **완전** | Precedes site |
| Subtotal / Partial | **부분** / **대부분** | Precedes site |
| Distal | **먼쪽** / **원위부** | Both accepted |
| Proximal | **몸쪽** / **근위부** | Both accepted |
| Left | **왼쪽** (surface) / **좌측** (internal) | See Laterality Table above |
| Right | **오른쪽** (surface) / **우측** (internal) | See Laterality Table above |
| Bilateral | **양쪽** | **PREFERRED over 양측** when no exemplar exists |

### Surgical Actions Reference
| English | Korean |
| :--- | :--- |
| Excision / -ectomy | **절제** |
| Incision / -otomy | **절개** |
| Biopsy | **생검** |
| Suture / Closure | **봉합** |
| Repair | **복구** (general) / **성형** (plastic) |
| Reconstruction | **재건** |
| Anastomosis | **연결** / **문합** |
| Bypass | **우회술** |
| Aspiration | **흡인** |
| Drainage | **배액** |
| Insertion | **삽입** |
| Replacement | **치환** (permanent) / **교환** (maintenance) |
| Removal | **제거** |
| Revision | **교정** (NOT 수정/재시술) |
| Fixation | **고정** |
| Ligation | **결찰** |
| Examination | **검사** |
| Measurement | **측정** |

### Diagnostic Marker Terminology
| English Context | Korean | Notes |
| :--- | :--- | :--- |
| Marker (imaging/tracer/localization) | **표시자** | e.g., `Marker lymphogram` → `표시자 림프조영상` |
| Marker (biological/tumor/lab) | **표지자** | e.g., `Cardiac Marker-ST2` → `심장표지자-ST2` |

### Additional Error-Prevention Rules
1.  **No Phonetic Transliteration for Established Concepts:**
    *   Debridement → `죽은 조직 제거` (NOT 데브리망)
    *   Plasmapheresis → `혈장분리 교환` (NOT 플라즈마페레시스)
    *   Lymphogram → `림프조영상` (NOT 림포그램)
2.  **Specific vs Generic Structures:** Do not generalize. `Ureterocele` ≠ `ureteral cyst`. `Pouch of Douglas` ≠ `cecum`. `Optic foramen` ≠ generic `nerve opening`.
3.  **Anastomosis vs Stoma:** `연결`/`문합` (joining) ≠ `창냄술` (creating opening).
4.  **Source Fidelity:** One referent per source referent. Do not add parent body parts as descriptors.
5.  **No Extra Detail:** Do not add billing/admin terms or generic nouns (`검사`, `시술`) not present in source.
6.  **Anatomical Term Validation:** Before finalizing any anatomical structure translation, cross-check against the Critical Anatomical Synonyms table AND the Laterality Preference Hierarchy. Literal translations that deviate from established KR reference terms will be rejected.
7.  **Modality Combination Validation:** For any term containing multiple imaging modalities joined by "with" or "combined with", apply the `동반` connector pattern and verify correct ordering against the Combined Modalities section. Linear translation with `및` is typically incorrect for hybrid imaging.
8.  **Exemplar Override Protocol:** Always check provided exemplars FIRST. If an exemplar contradicts this style guide (e.g., spacing, laterality term choice, suffix form), the EXEMPLAR TAKES PRECEDENCE. Apply style guide rules only in the absence of contradicting exemplars.