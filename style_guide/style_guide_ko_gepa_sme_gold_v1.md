# Task: Translate English SNOMED CT clinical terms into Korean

## Input Format
You will receive:
- `english_term`: A single English SNOMED CT term (procedure, finding, or body structure)
- `exemplars`: A table of English→Korean reference translations. Use as guidance but filter critically — ignore garbled entries, NA markers, EMR billing codes with commas, or obvious noise. Trust exemplar renderings for site-specific vocabulary and established procedure names.
- `hard_rules`: NON-NEGOTIABLE constraints that override everything else.

## Output Format
Output ONLY the Korean translation string. No quotation marks, no trailing punctuation, no preamble, no explanation.

## Hard Rules (always apply)
1. No trailing punctuation on Korean SNOMED terms.
2. Never wrap output in quotation marks.
3. Produced images end in `영상`, NEVER `조영상`. Procedures end in `조영` or `조영술`.
4. Fluoroscopy AS GUIDANCE = `투시 유도하` (or `형광 투시 유도하`). Standalone fluoroscopy exam = `투시 검사` / `투시술`. But **`Fluoroscopic [modality]` is a MODALITY QUALIFIER, not guidance** — translate as bare `투시` placed immediately before the modality (e.g. `Fluoroscopic angiography` → `투시 혈관 조영`, NOT `투시 유도하 ... 혈관 조영`).
5. Never introduce contrast phrases (`조영제 사용` / `조영제 미사용`) not stated in the source. `-graphy` alone does NOT imply contrast.

## Canonical Assembly Order
`[contrast] [approach/guidance] [laterality] [quantifier] [site] [modality-qualifier] [modality/action]`

## Core Style Guide

### General
- Head-final SOV; modality/action goes LAST.
- Space-separated word units; no spaces inside fixed compounds ending in `-술`, `-법`, `-검`, `-증`, `-염`.
- Arabic numerals; UTF-8; preserve Latin case for foreign symbols.
- **Prefer BARE NOMINAL forms** (`절제`, `생검`, `배액`, `조영`) over `-술`. Use `-술` only for fixed forms: `내시경술`, `우회술`, `절단술`, `창냄술`, `조성술`, `형성술`.
- Don't add `검사`, `시술`, or generic action nouns not in the source — EXCEPT when the modality is `ultrasonography` / `내시경 초음파` / other `-graphy`-style examinations where the reference convention appends `검사`. See "Ultrasonography-specific" below.
- Default: no `의` between site and action.

### Percutaneous — style choice
- `Percutaneous` may render as either `피부 경유` OR `경피적`.
- **When the phrase pattern is `Percutaneous drainage of [site]` (with no explicit imaging-guidance qualifier), prefer `경피적`.**
- When paired with `using imaging guidance`, both `피부 경유` and `경피적` are acceptable but exemplars for the joint/shoulder case use `피부 경유`; follow the specific exemplar match if present.
- Examples:
  - `Radiologic guidance for percutaneous drainage of abscess` → `영상 유도하 경피적 농양 배액`
  - `Percutaneous drainage of joint of shoulder using imaging guidance` → `영상 유도하 피부 경유 어깨 관절 배액`

### Body Structure Register (nuanced — follow exemplars carefully)
- General rule: native Korean anatomy (`빗장뼈`, `세로칸`, `엉덩뼈`, `팔`, `다리`, `넓적다리`, `종아리`, `손목`, `발목`).
- **Prefer NATIVE Korean forms even for arteries/muscles when they exist**:
  - `subclavian artery` → **`빗장 밑 동맥`** (preferred over `쇄골하 동맥`)
  - `extremity` (in procedures) → often **`사지`** works, but SME may accept `팔다리`; check exemplars
- BUT accept Sino-Korean where it's the dominant clinical convention:
  - `thoracic cage` → `흉곽` (not `가슴우리`)
  - `appendix` → `충수`; `prostate` → `전립샘`; `kidney` → `신장`
  - `retroperitoneum` → `후복막`
  - `peritoneum` → `복막`
  - `shoulder joint` → `어깨 관절`
- If exemplars show a specific Korean form for a body structure, USE THAT FORM.
- "structure of" ontology scaffold is not translated.

### Imaging Modality Canonical Forms
| English | Korean |
|---|---|
| X-ray (plain radiography) | `단순 촬영` |
| Radiographic imaging | `방사선 촬영` |
| CT | `컴퓨터 단층 촬영` |
| MRI | `자기 공명 영상` |
| Ultrasound (modality) | `초음파` |
| Ultrasonography | `초음파 검사` (append `검사`) |
| Endoscopic ultrasonography | `내시경 초음파 검사` |
| Fluoroscopy (standalone exam) | `투시 검사` / `투시술` |
| Fluoroscopy guidance | `투시 유도하` |
| Fluoroscopic [modality qualifier] | bare `투시` before modality |
| Angiography (vessel named) | `[vessel] 혈관 조영` — but may drop `혈관` when combined with other modality qualifiers; check reference patterns |
| Angiography (no vessel) | `동맥 조영` |
| Venography | `정맥 조영` |
| Arteriography | `동맥 조영(술)` |
| PET | `양전자 (방출) 단층 촬영` |
| Radionuclide imaging | `방사성 핵종 영상` |
| Endoscopy | `내시경술` / `내시경 검사` |

Site precedes modality: `뇌 컴퓨터 단층 촬영`.

### Ultrasonography-specific (IMPORTANT)
- `Ultrasonography of X` and `Endoscopic ultrasonography of X` should end with `검사`.
- Even though the general rule says "don't add `검사`", the reference convention for `-graphy` examinations uses `검사`.
- `Upper endoscopic ultrasonography of retroperitoneum` → `후복막 상부 내시경 초음파 검사`
- `Ultrasonography of X` → `X 초음파 검사`
- The word "upper" (in `Upper endoscopic ultrasonography`) modifies `endoscopic` and renders as `상부`, placed AFTER site: `[site] 상부 내시경 초음파 검사`.

### -graphy vs -gram
- `-graphy` (procedure) → `조영` (preferred bare) or `조영술`; `촬영(술)` for non-contrast studies.
- `-gram` (image) → `영상` (NEVER `조영상`).
- `Ventriculography of brain` → `뇌실 조영`.
- `Myelogram` → `척수 영상`; `Mammogram` → `유방 영상`; `Mammography` → `유방 촬영술`.

### Contrast (strict fidelity)
- `with contrast` → `조영제 사용` (FIRST position)
- `without contrast` → `조영제 미사용` (FIRST position; must not be dropped)
- No source contrast phrase → NO `조영제` in output.

### Approaches / Modifiers
| English | Korean |
|---|---|
| Percutaneous | `경피적` (preferred when no imaging-guidance modifier) / `피부 경유` |
| Transcatheter | `도관 경유` / `카테터 경유` |
| Transluminal (vessel) | `혈관 경유` |
| Transluminal (other tubes) | `내강 경유` |
| Transcranial | `경두개` |
| Laparoscopic | `복강경` |
| Endoscopic | `내시경` |
| Under [X] guidance | `[X] 유도하` |
| Radiologic guidance / imaging guidance | `영상 유도하` |
| Using [device] | `[device] 이용` (bare nominal, never `이용한`) |

### Surgical / Interventional Actions
| English | Korean |
|---|---|
| Excision / -ectomy | `절제` (`절제술` for "operation") |
| Incision / -otomy | `절개` |
| Biopsy | `생검` |
| Anastomosis | `연결` / `문합` |
| Bypass | `우회술` |
| Aspiration | `흡인` |
| Drainage | `배액` |
| **Injection (of marker/agent into site)** | **`주입`** (preferred over `주사` for procedural injection into a body site) |
| Insertion | `삽입` |
| Replacement (definitive) | `치환` |
| Replacement (routine, e.g. tube exchange) | `교환` / `교체` |
| Removal | `제거` |
| Thrombectomy | `혈전 제거(술)` |
| Fixation | `고정` |
| Marker | `표지자` |

### Combinations — IMPORTANT nuance for "with"
- `with [subordinate concurrent modality/step]` (e.g. `with serialography`): **preferred style is to prefix the subordinate step BARE (no `동반`)** placed before the main procedure. Only use `[secondary] 동반 [main]` when exemplars clearly support it.
  - `Angiography of artery of extremity with serialography` → `연속촬영 사지 동맥 조영` (bare prefix; `혈관` may be dropped when another qualifier is present)
- `and` / `with` (parallel equal procedures) → `및` (original order).
- `by [approach]` → `[approach]에 의한 [procedure]`.
- Never use `동반` for `by`, `using`, `via`, `under guidance`.

### Serialography specifically
- `serialography` → `연속촬영` (bare, no `-술`, no `동반`) placed as a prefix modality qualifier.

### Fluoroscopic-as-qualifier specifically
- `Fluoroscopic angiography of X` → `[contrast] [laterality] X 투시 혈관 조영` (or `X 투시 조영` if `혈관` is redundant with vessel-name).
- Do NOT convert modality-qualifier "fluoroscopic" into `투시 유도하` — reserve that for explicit "under fluoroscopic guidance".

### Quantifiers / Laterality (precede site)
`전체`, `부분`, `대부분`, `먼쪽`, `몸쪽`, `왼쪽`, `오른쪽`, `양측`.

### Radiology idioms
- `symptomatic study` → `진단`
- `screening` → `선별`
- `limited` → `제한적`
- `localization` → `위치 파악` (also acceptable: `위치 결정`)
- `transcranial` → `경두개`
- `specific` → `특수`
- `upper` (endoscopy/GI context) → `상부`

## Key Domain-Specific Vocabulary
- `biliary` (as drain/tube modifier) → **`담즙`** (`biliary drain` → `담즙 배액관`). Use `담관` only for the bile duct itself as anatomy.
- `Replacement of biliary drain using fluoroscopic guidance` → `투시 유도하 담즙 배액관 교체`
- `Ventriculography of brain` → `뇌실 조영`
- `Thoracic cage X-ray` → `흉곽 단순 촬영`
- `Replacement of nephrostomy tube using fluoroscopic guidance` → `투시 유도하 신루관 교체`
- `subclavian artery` → `빗장 밑 동맥` (native Korean preferred)
- `axilla` → `겨드랑이`
- `retroperitoneum` → `후복막`
- `peritoneum` → `복막`
- `abscess` → `농양`
- `Injection of marker into [site] using ultrasonographic guidance` → `초음파 유도하 [site] 표지자 주입`
- `Percutaneous drainage of X using imaging guidance` → `영상 유도하 피부 경유 X 배액` (exemplar-preferred form for joint/shoulder cases)
- `Radiologic guidance for percutaneous drainage of abscess` → `영상 유도하 경피적 농양 배액`
- `Percutaneous drainage of peritoneum using imaging guidance` → `영상 유도하 피부 경유 복막 배액` OR `영상 유도하 경피적 복막 배액` (both accepted)
- `Upper endoscopic ultrasonography of retroperitoneum` → `후복막 상부 내시경 초음파 검사`

## Strategy
1. Parse the English term: identify contrast, approach/guidance, laterality, quantifier, site, modality-qualifier (e.g. Fluoroscopic-, CT-), main modality/action, and any `with [subordinate procedure]`.
2. Distinguish "Fluoroscopic X" (modality qualifier → bare `투시`) from "under fluoroscopic guidance" (→ `투시 유도하`).
3. Consult exemplars for anatomy names and procedure conventions; prefer native Korean anatomy forms (e.g. `빗장 밑` for subclavian) when they exist.
4. For `with [subordinate]` combinations, prefer BARE PREFIX (`연속촬영 …`) over `[X] 동반 [Y]` unless exemplars clearly support 동반.
5. Assemble in canonical order; prefer bare nominal forms (`조영`, `주입`, `절제`).
6. Use `주입` (not `주사`) for injection of markers/agents into a body site.
7. For `ultrasonography` / `endoscopic ultrasonography`, ALWAYS append `검사` — this is a reference-convention exception to the "don't add 검사" rule.
8. For `percutaneous drainage` WITHOUT an imaging-guidance modifier, prefer `경피적`. With an imaging-guidance modifier, `피부 경유` is often the exemplar match.
9. Do NOT invent contrast, do NOT translate "structure of" scaffold, do NOT transliterate procedures with Korean equivalents.
10. Output ONLY the Korean string — no quotes, no punctuation terminator.