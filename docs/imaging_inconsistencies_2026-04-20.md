# KR SNOMED imaging — internal inconsistency report (2026-04-20)

## Scope

774 imaging-procedure concepts (descendants of `363679005 |Imaging (procedure)|`) that have an active Korean preferred synonym in the KR SNOMED release (`KR1000267_20251215`). This is the **complete KR-covered imaging set** for this release.

## Why this report exists

Our imaging-resources ablation (see `imaging_resources_ablation_findings_2026-04-20.md`) showed that even a body-site dictionary extracted from the KR release itself cannot beat pure exemplar retrieval. The diagnosis was that the KR release is **internally inconsistent**: the same anatomical site or imaging modality is rendered differently across procedures. This report enumerates those inconsistencies so they can feed back into style-guide v4 and into KR release curation.

## Axis 1 — Body-site rendering

Procedures sharing the same body-site attribute target were grouped and checked for whether they use the body-structure concept's preferred Korean form, an acceptable synonym, or neither. 11 body sites show **≥2 distinct renderings** across their procedures. Top clusters by procedure count:

| Body site | Procedures | Forms used (count) |
|---|---|---|
| Heart structure | 11 | `심장` (7), `심` (4) |
| Thyroid structure | 10 | `갑상샘` (8), `갑상선` (1), _no site form detected_ (1) |
| Kidney structure | 8 | `신장` (6), `콩팥` (1), _no site form detected_ (1) |
| Thoracic structure | 7 | `흉부` (5), `가슴` (2) |
| Pancreatic structure | 6 | `췌장` (4), `이자` (1), _no site form detected_ (1) |
| Lower limb structure | 4 | `다리` (3), `하지` (1) |
| Upper limb structure | 4 | `상지` (2), `팔` (2) |
| Carotid artery structure | 2 | `경동맥` (1), `목동맥` (1) |
| Base of skull structure | 2 | `두개저` (1), `머리뼈 바닥` (1) |
| Structure of cavity of true pelvis | 2 | `골반강` (1), `골반안` (1) |
| Mediastinal structure | 2 | `종격` (1), `세로칸` (1) |

### Example clusters with LLM verdicts

**Heart structure** — KR preferred: `심`; synonyms: 심장

| SCTID | English | Korean |
|---|---|---|
| 241547009 | Computed tomography of heart | 심장 컴퓨터 단층 촬영 |
| 241620005 | Magnetic resonance imaging of heart | 심장 자기 공명 영상 |
| 35621002 | Cardiac blood pool imaging | 심장 혈류 저류 영상 |
| 40701008 | Echocardiography | 심장 초음파 검사 |
| 419535008 | Magnetic resonance imaging perfusion study of heart | 심장 자기공명영상 관류 검사 |
| 431852008 | Pediatric echocardiography | 소아 심초음파 검사 |
| 433231002 | Contrast echocardiography | 조영 심초음파검사 |
| 433236007 | Transthoracic echocardiography | 가슴 경유 심장 초음파 검사 |

**Verdict (INTENTIONAL)** — recommended canonical: `심장`. _The form '심장' is used for full anatomical descriptions (e.g., CT/MRI of the heart), while '심' is used as a prefix in compound medical terms like '심초음파' (echocardiography). '심장' is the standard anatomical term._

**Thyroid structure** — KR preferred: `갑상샘`; synonyms: 갑상선

| SCTID | English | Korean |
|---|---|---|
| 241455000 | Ultrasound scan of thyroid | 갑상샘 초음파 스캔 |
| 241537006 | Computed tomography of thyroid | 갑상샘 컴퓨터 단층 촬영 |
| 241613003 | Magnetic resonance imaging of thyroid | 갑상샘 자기 공명 영상 |
| 385443001 | Radionuclide imaging of thyroid | 갑상샘의 방사성 핵종 영상 검사 |
| 39500001 | Thyroid imaging | 갑상샘 영상 검사 |
| 442865000 | Fine needle aspiration biopsy of thyroid using ultrasound guidance | 초음파 유도하 갑상샘의 가는 바늘 흡인 생검 |
| 763937008 | Radionuclide imaging of thyroid using iodine-131 | 아이오딘-131 이용 갑상샘 방사성 핵종 영상 |
| 763940008 | Radionuclide imaging of thyroid using iodine radioisotope | 방사성 아이오딘 섭취율 |

**Verdict (ARBITRARY)** — recommended canonical: `갑상샘`. _The term '갑상샘' is the preferred medical term in Korean, while '갑상선' is a common synonym. The variation in the sample is inconsistent, and the preferred term should be used for all concepts._

**Kidney structure** — KR preferred: `신장`; synonyms: 콩팥

| SCTID | English | Korean |
|---|---|---|
| 241354002 | Renal isotope studies | 신장 동위원소 검사 |
| 241624001 | Magnetic resonance imaging of kidneys | 신장 자기 공명 영상 |
| 28686001 | Nephrotomogram | 신장 단층 촬영 |
| 306005 | Echography of kidney | 신장 초음파 검사 |
| 418354002 | Doppler ultrasonography of kidney | 신장 도플러 초음파 검사 |
| 429931008 | Computed tomography of kidney with contrast | 조영제 사용 신장 컴퓨터 단층 촬영 |
| 432075000 | Replacement of nephrostomy tube using fluoroscopic guidance | 투시 유도하 신루관 교체 |
| 55501000 | Computed tomography of kidney | 콩팥 컴퓨터 단층 촬영 |

**Verdict (ARBITRARY)** — recommended canonical: `신장`. _The term '신장' is the standard medical term used in the vast majority of the provided examples, while '콩팥' is a colloquial synonym used inconsistently in only one instance._

**Thoracic structure** — KR preferred: `흉부`; synonyms: 가슴

| SCTID | English | Korean |
|---|---|---|
| 16551191000119104 | Percutaneous fine needle aspiration biopsy of chest using computed tomography guidance | 컴퓨터 단층 촬영 유도하 피부 경유 흉부의 가는 바늘 흡인 생검 |
| 25850001 | Ultrasonography of thorax | 가슴 초음파 검사 |
| 383501000119107 | Plain x-ray of chest apical and lordotic views | 흉부 첨단 및 전만상 일반 X선 촬영 |
| 399208008 | Plain chest X-ray | 흉부의 일반 X선 촬영 |
| 42869005 | Diagnostic radiography of chest, combined posteroanterior and lateral | 가슴 뒤앞 및 옆 진단적 방사선 영상 촬영 |
| 440491000 | Biopsy of thorax using computed tomography guidance | 컴퓨터 단층 촬영 유도하 흉부 생검 |
| 486261000119109 | Plain x-ray of chest posteroanterior view | 흉부 뒤앞 일반 X선 촬영 |

**Verdict (INTENTIONAL)** — recommended canonical: `흉부`. _The term '흉부' is the formal medical term used in most clinical descriptions, while '가슴' is a common synonym used in simpler or more colloquial contexts. '흉부' is more consistent with standard medical terminology for diagnostic procedures._

**Pancreatic structure** — KR preferred: `췌장`; synonyms: 이자

| SCTID | English | Korean |
|---|---|---|
| 241551006 | Computed tomography of pancreas | 췌장 컴퓨터 단층 촬영 |
| 241625000 | Magnetic resonance imaging of pancreas | 이자 자기 공명 영상 |
| 277668001 | Ultrasound scan of pancreas | 췌장 초음파 스캔 |
| 303761006 | Pancreatic contrast procedure | 췌관조영 |
| 429873004 | Computed tomography of pancreas with contrast | 조영제 사용 췌장 컴퓨터 단층 촬영 |
| 442887009 | Percutaneous needle biopsy of pancreas using ultrasound guidance | 초음파 유도하 피부 경유 췌장 바늘 생검 |

**Verdict (ARBITRARY)** — recommended canonical: `췌장`. _The terms '췌장' and '이자' are synonyms for the same anatomical structure, but '췌장' is the standard medical term used in the majority of the provided examples. The use of '이자' appears inconsistent with the clinical preference for '췌장'._

**Lower limb structure** — KR preferred: `하지`; synonyms: 다리; 종아리; 하퇴

| SCTID | English | Korean |
|---|---|---|
| 113109007 | Magnetic resonance imaging of lower extremity | 하지 자기 공명 영상 |
| 384521000119100 | Computed tomography of lower limb without contrast | 조영제 미사용 다리 컴퓨터 단층 촬영 |
| 449922004 | Ultrasonography of lower limb | 다리 초음파 검사 |
| 702502001 | Computed tomography of lower limb with contrast | 조영제 사용 다리 컴퓨터 단층 촬영 |

**Verdict (INTENTIONAL)** — recommended canonical: `하지`. _The term '하지' is the standard medical/anatomical term used in formal clinical settings, while '다리' is a common, more colloquial synonym. Both are clinically acceptable, but '하지' is preferred for formal imaging reports._

**Upper limb structure** — KR preferred: `상지`; synonyms: 팔

| SCTID | English | Korean |
|---|---|---|
| 241632009 | Magnetic resonance imaging of upper limb | 상지 자기 공명 영상 |
| 26946001 | Computed tomography of upper extremity with contrast | 조영제 사용 팔 컴퓨터 단층 촬영 |
| 394491000119101 | Computed tomography of upper limb without contrast | 조영제 미사용 상지 컴퓨터 단층 촬영 |
| 449921006 | Ultrasonography of upper limb | 팔 초음파 검사 |

**Verdict (ARBITRARY)** — recommended canonical: `상지`. _The term '상지' is the standard medical terminology for 'upper limb', whereas '팔' is a more colloquial term. The variation appears to be due to inconsistent translation choices for the same anatomical concept._

**Carotid artery structure** — KR preferred: `목동맥`; synonyms: 경동맥

| SCTID | English | Korean |
|---|---|---|
| 276021004 | Ultrasonography of carotid artery | 경동맥 초음파 |
| 58920005 | Angiography of carotid artery | 목동맥 혈관 조영 |

**Verdict (INTENTIONAL)** — recommended canonical: `경동맥`. _In clinical practice, '경동맥' is the standard medical term for the carotid artery, while '목동맥' is a more colloquial or descriptive term. The variation is acceptable as '경동맥' is preferred for formal diagnostic procedures like ultrasonography._

## Axis 2 — Modality rendering

Grouped by the SNOMED `Method` attribute. For each modality with ≥2 observed Korean renderings, counts are shown below. Total methods with variance: 2.

| Modality | Procedures | Variants (count) | Unmatched |
|---|---|---|---|
| Magnetic resonance imaging | 199 | `자기 공명 영상` (188), `자기공명영상` (2) | 9 |
| Ultrasound imaging | 166 | `초음파 검사` (107), `초음파` (52), `초음파 촬영` (2), `초음파검사` (2) | 3 |

### Per-modality LLM verdicts

- **Magnetic resonance imaging** — ARBITRARY; canonical: `자기 공명 영상`. _The variation is due to inconsistent spacing between '자기', '공명', and '영상'. '자기 공명 영상' is the more standard and frequent representation in the provided data._
- **Ultrasound imaging** — INTENTIONAL; canonical: `초음파 검사`. _The variations reflect different clinical usages: '초음파 검사' is the standard term for the procedure, '초음파' is used as a prefix for ultrasound-guided interventions (e.g., ultrasound-guided drainage), and '초음파 촬영' is used for specific imaging studies. '초음파 검사' is the most frequent and clinically appropriate canonical form for the method itself._

## Axis 3 — Action-suffix discipline

Terminal action tokens (`촬영 / 영상 / 검사 / 조영(술/상) / 측정 / 스캔 / 술 / …`) within each method group. Methods with mixed terminals: 10.

| Modality | Procedures | Terminal tokens (count) |
|---|---|---|
| Magnetic resonance imaging | 199 | `영상` (181), `조영` (8), `(other: 생검)` (4), `검사` (3), `조영술` (2), `(other: 분광)` (1) |
| Ultrasound imaging | 166 | `검사` (108), `스캔` (25), `(other: 흡인)` (8), `조영` (6), `(other: 초음파)` (5), `(other: 생검)` (4), `(other: 배액)` (2), `촬영` (2), `(other: 예약)` (1), `측정` (1), `술` (1), `(other: 완료)` (1), `(other: 유도)` (1), `(other: 결정)` (1) |
| Computed tomography | 139 | `촬영` (103), `조영` (13), `(other: 생검)` (10), `조영상` (5), `검사` (3), `스캔` (1), `(other: 지짐)` (1), `(other: 설정)` (1), `측정` (1), `술` (1) |
| Imaging - action (qualifier value) | 79 | `조영` (56), `술` (4), `조영상` (4), `검사` (4), `조영술` (3), `(other: 배액)` (2), `촬영` (1), `측정` (1), `(other: 검사명)` (1), `스캔` (1), `(other: 요법)` (1), `(other: 삽입)` (1) |
| Radiographic imaging - action (qualifier value) | 58 | `촬영` (31), `검사` (5), `조영` (5), `(other: 관장)` (4), `조영술` (4), `측정` (4), `조영상` (2), `(other: 쵤영)` (1), `(other: 흡인)` (1), `촬영술` (1) |
| Radionuclide imaging - action (qualifier value) | 29 | `검사` (11), `영상` (7), `스캔` (5), `조영` (4), `조영상` (1), `(other: 섭취율)` (1) |
| Doppler ultrasound imaging - action (qualifier value) | 18 | `검사` (15), `촬영` (3) |
| Plain X-ray imaging - action (qualifier value) | 16 | `촬영` (13), `술` (1), `(other: 쵤영)` (1), `검사` (1) |
| Fluoroscopic imaging - action (qualifier value) | 11 | `투시술` (2), `(other: 용해)` (2), `촬영` (1), `(other: 성형)` (1), `(other: 주사)` (1), `(other: 생검)` (1), `검사` (1), `조영` (1), `(other: 확장)` (1) |
| Injection - action (qualifier value) | 2 | `(other: 주사)` (1), `(other: 차단)` (1) |

### Per-modality suffix LLM verdicts

- **Magnetic resonance imaging** — INTENTIONAL; canonical: `영상`. _The variations reflect different clinical contexts: '영상' is the standard term for the imaging itself, '조영/조영술' refers to contrast-enhanced procedures, and '검사' is used for functional assessments like perfusion studies._
- **Ultrasound imaging** — INTENTIONAL; canonical: `검사`. _The variations reflect specific clinical procedures (e.g., aspiration, biopsy, drainage, scanning) performed using ultrasound guidance, rather than inconsistent naming of the modality itself. '검사' is the most frequent and general term for a diagnostic ultrasound examination._
- **Computed tomography** — INTENTIONAL; canonical: `촬영`. _The variations reflect different clinical actions or procedures performed using CT, such as '촬영' (imaging/scanning), '조영' (contrast enhancement), '생검' (biopsy), and '측정' (measurement). '촬영' is the most frequent and appropriate term for the imaging modality itself._
- **Imaging - action (qualifier value)** — INTENTIONAL; canonical: `조영`. _The variations represent different linguistic functions: '조영' acts as a noun/modifier for the process, '조영술' refers to the specific procedure/technique, and '조영상' refers to the resulting image. Other terms like '촬영', '검사', or '배액' describe distinct clinical actions (imaging, examination, drainage) that cannot be unified under a single term._
- **Radiographic imaging - action (qualifier value)** — INTENTIONAL; canonical: `촬영`. _The variations reflect specific clinical actions: '촬영' (imaging/photography), '검사' (examination), '조영/조영술' (contrast study), and '측정' (measurement/densitometry) are distinct medical procedures. '조영상' is a noun form describing the result, and '쵤영' is a typo._
- **Radionuclide imaging - action (qualifier value)** — INTENTIONAL; canonical: `검사`. _The variations reflect specific clinical nuances: '스캔' (scan) refers to the acquisition process, '조영' (angiography) refers to vascular imaging, '영상' (imaging) refers to the resulting image, and '섭취율' (uptake rate) refers to a specific quantitative measurement. '검사' (examination/test) is the most versatile and appropriate general term for the modality._
- **Doppler ultrasound imaging - action (qualifier value)** — INTENTIONAL; canonical: `검사`. _In Korean medical terminology, '검사' (examination/test) is a general term for diagnostic procedures, while '촬영' (imaging/photography) specifically refers to the act of capturing images. Both are clinically appropriate depending on whether the focus is on the diagnostic process or the imaging procedure itself._
- **Plain X-ray imaging - action (qualifier value)** — ARBITRARY; canonical: `촬영`. _The variation is primarily due to a typo ('쵤영') and inconsistent use of '검사' or '술' for a simple X-ray procedure. '촬영' is the most frequent and clinically appropriate term for imaging procedures._
- **Fluoroscopic imaging - action (qualifier value)** — INTENTIONAL; canonical: `투시`. _The variations represent different clinical actions (e.g., biopsy, injection, lysis, dilation) performed under fluoroscopic guidance. '투시' (fluoroscopy) serves as the base modality, while the other terms describe the specific procedure being performed._
- **Injection - action (qualifier value)** — INTENTIONAL; canonical: `주사`. _The terms represent different clinical actions: '주사' (injection) refers to the administration of a substance, while '차단' (block) refers to a nerve block procedure. They are not interchangeable in a clinical context._

## Axis 4 — Contrast word-order

For procedures whose English FSN contains `with contrast` or `without contrast`, we check whether the Korean puts the contrast phrase first or the body site first.

- Total contrast procedures: **69**
- Contrast-first (`조영제 … 부위 …`): **68**
- Site-first (`부위 … 조영제 …`): **1**

**Contrast-first examples:**
- 16335031000119103: High resolution computed tomography of chest without contrast → 조영제 미사용 흉부의 고해상도 컴퓨터 단층 촬영
- 16457501000119102: Computed tomography of abdomen and pelvis without contrast → 조영제 미사용 복부 및 골반 컴퓨터 단층 촬영
- 16462121000119108: Computed tomography angiography of thorax and abdomen and pelvis with contrast → 조영제 사용 가슴 및 복부 및 골반의 컴퓨터 단층 촬영 혈관 조영
- 17901000087101: Computed tomography angiography of left lower limb with contrast → 조영제 사용 왼쪽 하지 컴퓨터 단층 촬영 혈관 조영
- 2161000087104: Magnetic resonance imaging of left breast with contrast → 조영제 사용 왼쪽 유방 자기 공명 영상

**Site-first examples:**
- 709767008: Computed tomography of vascular structure of pelvis with contrast → 골반 혈관의 컴퓨터 단층 촬영

## Summary

- Clusters reviewed by LLM: **23**
  - classified ARBITRARY: 6
  - classified INTENTIONAL: 17
  - classified UNCLEAR / other: 0

### Implications

- Arbitrary clusters are candidates for KR release curation (canonicalise to the recommended form, add the other form as an acceptable synonym) or for explicit style-guide rules.
- Intentional clusters inform the style guide: document the contextual rule so translators can reproduce it.
- Unclear clusters need SME input from KHIS.

### Caveats

- LLM verdicts are directional, not authoritative. They reflect one model's reading; disagreements with KHIS's own policy should be resolved by KHIS.
- Axis 1 uses substring matching of body-structure-concept synonyms to detect the 'which rendering was used' signal. Procedures that re-phrase the body site without reusing the canonical terms will be counted as `(none detected)` — that column is itself a useful signal about free-form anatomical rendering.
- Axis 2's modality variant list is hand-curated. Unmatched rows may indicate either modality renderings we forgot or procedures that deviate in unexpected ways.
