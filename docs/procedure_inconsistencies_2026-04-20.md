# KR SNOMED procedure — internal inconsistency report (2026-04-20)

## Scope

3693 concepts in the `Procedure` hierarchy that have an active Korean preferred synonym in the KR SNOMED release (`KR1000267_20251215`). This is the **complete KR-covered set** under this root for this release.

## Why this report exists

Our imaging-resources ablation (see `imaging_resources_ablation_findings_2026-04-20.md`) showed that even a body-site dictionary extracted from the KR release itself cannot beat pure exemplar retrieval. The diagnosis was that the KR release is **internally inconsistent**: the same anatomical site or imaging modality is rendered differently across procedures. This report enumerates those inconsistencies so they can feed back into style-guide v4 and into KR release curation.

## Axis 1 — Body-site rendering

Procedures sharing the same body-site attribute target were grouped and checked for whether they use the body-structure concept's preferred Korean form, an acceptable synonym, or neither. 29 body sites show **≥2 distinct renderings** across their procedures. Top clusters by procedure count:

| Body site | Procedures | Forms used (count) |
|---|---|---|
| Colon structure | 67 | `결장` (50), `잘록 창자` (3), _no site form detected_ (14) |
| Duodenal structure | 30 | `십이지장` (28), `샘창자` (1), _no site form detected_ (1) |
| Heart structure | 26 | `심장` (16), `심` (8), _no site form detected_ (2) |
| Kidney structure | 25 | `신장` (16), `콩팥` (1), _no site form detected_ (8) |
| Thyroid structure | 23 | `갑상샘` (20), `갑상선` (1), _no site form detected_ (2) |
| Ileal structure | 23 | `회장` (18), `돌창자` (3), _no site form detected_ (2) |
| Bone structure | 21 | `뼈` (13), `골` (8) |
| Appendix structure | 15 | `충수` (8), `충수돌기` (6), `막창자꼬리` (1) |
| Structure of small intestine | 13 | `소장` (12), `작은 창자` (1) |
| Splenic structure | 11 | `비장` (10), `지라` (1) |
| Pancreatic structure | 11 | `췌장` (8), `이자` (1), _no site form detected_ (2) |
| Thoracic structure | 10 | `흉부` (5), `가슴` (4), _no site form detected_ (1) |
| Tendon structure | 9 | `힘줄` (8), `건` (1) |
| Right colon structure | 9 | `오른쪽 결장` (6), `우측 결장` (1), _no site form detected_ (2) |
| Fallopian tube structure | 8 | `자궁관` (4), `난관` (2), _no site form detected_ (2) |

### Example clusters with LLM verdicts

**Colon structure** — KR preferred: `결장`; synonyms: 잘록 창자

| SCTID | English | Korean |
|---|---|---|
| 10361000132103 | Endoscopic cauterization of polyp of colon | 결장 용종의 내시경 지짐 |
| 10371000132109 | Colonoscopic snare polypectomy of colon | 결장의 대장 내시경적 올가미 용종 절제 |
| 168836005 | Barium enema | 바륨 관장 |
| 174072006 | Extended right hemicolectomy and end-to-end anastomosis | 오른쪽 결장 확대 절제 및 단단 문합 |
| 174094003 | Left hemicolectomy and end-to-end anastomosis of colon to colon | 왼쪽 결장 절제 및 결장 결장 끝끝 연결 |
| 174101001 | Sigmoid colectomy and anastomosis of colon to rectum | 구불 결장 절제 및 결장 직장 연결 |
| 174121000 | Bypass of colon | 결장 우회술 |
| 174171002 | Fiberoptic endoscopic snare resection of lesion of colon | 결장 병변의 광섬유 내시경 올가미 제거 |

**Verdict (INTENTIONAL)** — recommended canonical: `결장`. _The term '결장' is the standard medical term for colon, while '대장' is frequently used in the context of '대장 내시경술' (colonoscopy), which is a conventional clinical term. The variation is clinically acceptable and follows standard Korean medical nomenclature._

**Duodenal structure** — KR preferred: `십이지장`; synonyms: 샘창자

| SCTID | English | Korean |
|---|---|---|
| 10107006 | Duodenoduodenostomy | 십이지장 십이지장 연결 |
| 116031009 | Pylorus-sparing Whipple operation | 날문 보존 휘플 수술 |
| 116241004 | Pancreaticoduodenectomy | 췌십이지장 절제 |
| 118833000 | Procedure on duodenum | 십이지장 처치 |
| 173856005 | Bypass of duodenum | 십이지장 우회술 |
| 173889005 | Closure of perforated duodenal ulcer | 십이지장 천공 궤양 봉합 |
| 1801001 | Endoscopic biopsy of duodenum | 십이지장 내시경 생검 |
| 195969003 | Choledochoduodenostomy | 총담관십이지장 연결 |

**Verdict (INTENTIONAL)** — recommended canonical: `십이지장`. _십이지장 is the standard medical term used in clinical practice, while 샘창자 is the pure Korean synonym. Both are clinically acceptable, but 십이지장 is more frequent in formal medical terminology._

**Heart structure** — KR preferred: `심`; synonyms: 심장

| SCTID | English | Korean |
|---|---|---|
| 116218007 | Fine needle biopsy of heart | 심장의 가는 바늘 생검 |
| 14769009 | Tilt test | 기립 경사 검사 |
| 15979006 | Endoscopy of heart | 심장 내시경술 |
| 197042001 | Biopsy of heart | 심장 생검 |
| 241547009 | Computed tomography of heart | 심장 컴퓨터 단층 촬영 |
| 241620005 | Magnetic resonance imaging of heart | 심장 자기 공명 영상 |
| 250980009 | Cardioversion | 심장율동 전환 |
| 2598006 | Open heart surgery | 개심 수술 |

**Verdict (INTENTIONAL)** — recommended canonical: `심장`. _The form '심장' is used for anatomical descriptions (e.g., biopsy of heart), while the prefix '심-' is used in established medical compounds (e.g., 심전도, 개심 수술). '심장' is the more standard anatomical term for general procedures._

**Kidney structure** — KR preferred: `신장`; synonyms: 콩팥

| SCTID | English | Korean |
|---|---|---|
| 15067008 | Nephropexy | 신장 고정 |
| 175907006 | Nephroureterectomy | 신요관 절제 |
| 175943000 | Anatrophic nephrolithotomy | 무손상 신장절개 결석제거 |
| 233581009 | Hemofiltration | 혈액여과 |
| 233586004 | Hemodiafiltration | 혈액 투석 여과 |
| 241354002 | Renal isotope studies | 신장 동위원소 검사 |
| 241624001 | Magnetic resonance imaging of kidneys | 신장 자기 공명 영상 |
| 2813008 | Nephroureterocystectomy | 신요관방광 절제 |

**Verdict (INTENTIONAL)** — recommended canonical: `신장`. _The term '신장' is the standard medical/anatomical term used in clinical procedures, while '콩팥' is a common synonym. The provided samples consistently use '신장' for anatomical references, making it the appropriate canonical form._

**Thyroid structure** — KR preferred: `갑상샘`; synonyms: 갑상선

| SCTID | English | Korean |
|---|---|---|
| 119945004 | Thyroid gland closure | 갑상샘 봉합 |
| 13619001 | Thyroidectomy | 갑상샘 절제 |
| 14864008 | Endoscopy of thyroid | 갑상샘 내시경술 |
| 171988007 | Excision of lesion of thyroid gland | 갑상샘 병변의 절제 |
| 241455000 | Ultrasound scan of thyroid | 갑상샘 초음파 스캔 |
| 241537006 | Computed tomography of thyroid | 갑상샘 컴퓨터 단층 촬영 |
| 241613003 | Magnetic resonance imaging of thyroid | 갑상샘 자기 공명 영상 |
| 260663006 | Laryngofissure | 후두 절개 |

**Verdict (ARBITRARY)** — recommended canonical: `갑상샘`. _The term '갑상샘' is the preferred medical term in Korean, and all provided samples consistently use '갑상샘' despite '갑상선' being listed as an acceptable synonym._

**Ileal structure** — KR preferred: `회장`; synonyms: 돌창자

| SCTID | English | Korean |
|---|---|---|
| 173977007 | Creation of ileostomy | 회장 창냄술 |
| 174073001 | Extended right hemicolectomy and anastomosis of ileum to colon | 우측 결장 확대 절제술 및 회장 결장 문합 |
| 174080004 | Right hemicolectomy and end to end anastomosis of ileum to colon | 우측 결장 반절제 및 회장과 결장 단단 문합술 |
| 174081000 | Right hemicolectomy and side-to-side anastomosis of ileum to transverse colon | 오른쪽 결장 절제 및 회장 횡행 결장 측측 문합 |
| 24883002 | Biliopancreatic bypass to ileum with partial gastrectomy | 돌창자로 담도 이자 우회술 동반한 부분 위 절제술 |
| 27041000 | Cholecystoileostomy | 담낭 회장 연결 |
| 276190007 | Ileocolic resection | 회결장 절제 |
| 299694009 | Biopsy of ileum | 회장 생검 |

**Verdict (ARBITRARY)** — recommended canonical: `회장`. _The term '회장' is the standard medical term used in the vast majority of clinical contexts, while '돌창자' is a more colloquial/native Korean synonym used inconsistently in only one instance._

**Bone structure** — KR preferred: `뼈`; synonyms: 골

| SCTID | English | Korean |
|---|---|---|
| 116014002 | Excisional biopsy of bone | 뼈 절제 생검 |
| 116371009 | Autogenous bone graft | 자가 뼈이식 |
| 118470002 | Internal skeletal fixation | 골접합 |
| 13861005 | Biopsy of bone | 뼈 생검 |
| 150062003 | Osteotomy | 절골 |
| 239329001 | Excision of bone | 골절제 |
| 241405008 | Radionuclide three-phase bone study | 방사성 핵종 삼상 뼈 검사 |
| 257838009 | External fixation of bone | 외골격 고정 |

**Verdict (INTENTIONAL)** — recommended canonical: `뼈`. _The variation follows standard Korean medical linguistic patterns where '뼈' is used as a noun for the body part (e.g., 뼈 생검), while '골' is used as a prefix or root in technical medical terms (e.g., 절골, 골성형)._

**Appendix structure** — KR preferred: `충수`; synonyms: 충수돌기; 막창자꼬리; 곁자취; 부속물

| SCTID | English | Korean |
|---|---|---|
| 1299000 | Excision of appendiceal stump | 충수돌기 말단부 절제 |
| 174036004 | Emergency appendectomy | 응급 충수돌기 절제 |
| 174039006 | Emergency excision of normal appendix | 정상 충수의 응급 절제 |
| 174041007 | Laparoscopic emergency appendectomy | 복강경 응급 충수돌기 절제 |
| 174045003 | Interval appendectomy | 간격 충수돌기 절제 |
| 235313004 | Non-emergency appendectomy | 비응급 충수 절제 |
| 307581005 | Laparoscopic interval appendectomy | 복강경 간격 충수 절제 |
| 42332004 | Fistulization of appendix | 충수 창냄술 |

**Verdict (INTENTIONAL)** — recommended canonical: `충수돌기`. _The variations reflect different linguistic usages: '충수돌기' is the formal anatomical term used in most surgical procedures, '충수' is a common clinical shorthand, and '막창자꼬리' is the pure Korean anatomical term. '충수돌기' is the most consistent and professional choice for SNOMED CT._

## Axis 2 — Modality rendering

Grouped by the SNOMED `Method` attribute. For each modality with ≥2 observed Korean renderings, counts are shown below. Total methods with variance: 2.

| Modality | Procedures | Variants (count) | Unmatched |
|---|---|---|---|
| Magnetic resonance imaging | 199 | `자기 공명 영상` (188), `자기공명영상` (2) | 9 |
| Ultrasound imaging | 166 | `초음파 검사` (107), `초음파` (52), `초음파 촬영` (2), `초음파검사` (2) | 3 |

### Per-modality LLM verdicts

- **Magnetic resonance imaging** — ARBITRARY; canonical: `자기 공명 영상`. _The variation is due to inconsistent spacing between '자기', '공명', and '영상'. '자기 공명 영상' is the more frequent and standard orthography in medical documentation._
- **Ultrasound imaging** — INTENTIONAL; canonical: `초음파 검사`. _The variations reflect different clinical usages: '초음파 검사' is the standard term for the procedure, '초음파' is used as a prefix for ultrasound-guided interventions (e.g., ultrasound-guided aspiration), and '초음파 촬영' is used for specific imaging studies like scrotal ultrasound._

## Axis 3 — Action-suffix discipline

Terminal action tokens (`촬영 / 영상 / 검사 / 조영(술/상) / 측정 / 스캔 / 술 / …`) within each method group. Methods with mixed terminals: 104.

| Modality | Procedures | Terminal tokens (count) |
|---|---|---|
| Excision - action (qualifier value) | 604 | `절제` (525), `술` (17), `연결` (14), `제거` (12), `창냄술` (12), `(other: 변형)` (6), `절제술` (5), `(other: 전위)` (2), `절개` (2), `(other: 형성)` (2), `(other: 박리)` (2), `문합` (1), `(other: 누공)` (1), `(other: 완료)` (1), `(other: 고정)` (1), `(other: 단계)` (1) |
| Magnetic resonance imaging | 199 | `영상` (181), `조영` (8), `생검` (4), `검사` (3), `조영술` (2), `(other: 분광)` (1) |
| Ultrasound imaging | 166 | `검사` (108), `스캔` (25), `흡인` (8), `조영` (6), `(other: 초음파)` (5), `생검` (4), `배액` (2), `촬영` (2), `(other: 예약)` (1), `측정` (1), `술` (1), `(other: 완료)` (1), `(other: 유도)` (1), `(other: 결정)` (1) |
| Evaluation - action (qualifier value) | 157 | `검사` (86), `측정` (18), `(other: 배양)` (6), `(other: 평가)` (4), `법` (3), `(other: 표현형)` (2), `(other: 용적)` (2), `(other: 심전도)` (2), `(other: 응고시간)` (2), `(other: 시간)` (2), `(other: D)` (1), `(other: 영양화)` (1), `(other: 삼투취약성)` (1), `(other: 집락수)` (1), `(other: 예후)` (1), `(other: 환경평가)` (1), `(other: 분류)` (1), `(other: 뇌파도)` (1), `(other: 농도차)` (1), `(other: 지수)` (1), `(other: 면역고정)` (1), `(other: 아이오딘화)` (1), `(other: 배양반응)` (1), `(other: 검사명)` (1), `(other: 지도화)` (1), `(other: 팽창)` (1), `(other: 미생물학)` (1), `(other: 진균학)` (1), `(other: 핵형)` (1), `(other: 청력도)` (1), `(other: 응집억제)` (1), `(other: 심음도)` (1), `(other: 유전형)` (1), `(other: 절차)` (1), `(other: 효소면역분석)` (1), `(other: 사정)` (1), `(other: 융합)` (1), `(other: 발광)` (1), `(other: 수면다원기록)` (1), `(other: 심장탄도)` (1) |
| Incision - action (qualifier value) | 151 | `절개` (116), `절단` (7), `창냄술` (5), `절제` (5), `술` (4), `(other: 배농)` (3), `이식` (2), `절개술` (2), `연결` (1), `(other: 절골)` (1), `(other: 박리)` (1), `(other: 작은개복)` (1), `배액` (1), `(other: 고실천자)` (1), `제거` (1) |
| Measurement - action (qualifier value) | 146 | `측정` (91), `검사` (31), `(other: 계산)` (4), `(other: 전기영동)` (2), `(other: 침강비)` (1), `(other: 수치)` (1), `(other: 분광분석)` (1), `(other: 비)` (1), `(other: 기록)` (1), `(other: 청소율)` (1), `법` (1), `(other: 동맥혈산소분압)` (1), `(other: 영동)` (1), `(other: 조직)` (1), `(other: 배설률)` (1), `술` (1), `(other: 검사기)` (1), `(other: 형광동소교잡반응)` (1), `(other: 혈액상)` (1), `(other: 시간)` (1), `(other: 분석)` (1), `(other: 조절)` (1) |
| Computed tomography | 139 | `촬영` (103), `조영` (13), `생검` (10), `조영상` (5), `검사` (3), `스캔` (1), `(other: 지짐)` (1), `(other: 설정)` (1), `측정` (1), `술` (1) |
| Inspection - action (qualifier value) | 96 | `술` (75), `검사` (7), `절제` (4), `(other: 조명)` (2), `생검` (2), `(other: 시진)` (1), `(other: 보고)` (1), `세척` (1), `삽입` (1), `(other: 지혈)` (1), `확장` (1) |
| Biopsy - action (qualifier value) | 94 | `생검` (92), `술` (1), `(other: 내시경)` (1) |
| Repair - action (qualifier value) | 87 | `성형` (41), `복구` (24), `봉합` (9), `성형술` (2), `(other: 교정)` (2), `절제` (2), `이식` (2), `술` (1), `재건` (1), `치환` (1), `제거` (1), `(other: 요도고정)` (1) |
| Closure - action (qualifier value) | 79 | `봉합` (69), `술` (3), `복구` (2), `성형` (1), `(other: 매기)` (1), `(other: 묶음)` (1), `(other: 복원)` (1), `(other: 유착)` (1) |
| Imaging - action (qualifier value) | 79 | `조영` (56), `술` (4), `조영상` (4), `검사` (4), `조영술` (3), `배액` (2), `촬영` (1), `측정` (1), `(other: 검사명)` (1), `스캔` (1), `요법` (1), `삽입` (1) |
| Fine needle aspiration biopsy - action (qualifier value) | 77 | `생검` (67), `흡인` (10) |
| Anastomosis - action (qualifier value) | 76 | `연결` (61), `절제` (6), `창냄술` (2), `연결술` (2), `(other: 형성)` (2), `문합` (1), `성형` (1), `술` (1) |
| Administration - action (qualifier value) | 72 | `(other: 예방접종)` (24), `요법` (15), `(other: 마취)` (7), `(other: 진정)` (4), `치료` (3), `법` (3), `(other: 투여)` (2), `(other: 투약)` (2), `(other: 억제)` (1), `(other: 주입)` (1), `(other: 마취유도)` (1), `(other: 진통)` (1), `(other: 부위마취)` (1), `(other: 무호흡산소공급)` (1), `(other: 전신마취)` (1), `(other: 분석)` (1), `(other: 주기)` (1), `술` (1), `(other: 면역화)` (1), `(other: 유도)` (1) |
| Injection - action (qualifier value) | 64 | `(other: 주사)` (18), `(other: 차단)` (12), `(other: 마취)` (5), `(other: 상완신경총차단)` (4), `(other: 경막외마취)` (2), `요법` (2), `술` (1), `(other: 경추신경총차단)` (1), `(other: 요추신경총차단)` (1), `(other: 대퇴신경차단)` (1), `(other: 외측대퇴피신경차단)` (1), `(other: 폐쇄신경차단)` (1), `(other: 복재신경차단)` (1), `(other: 장골서혜신경차단)` (1), `(other: 장골하복신경차단)` (1), `(other: 안장차단)` (1), `(other: 척추경막외병용마취)` (1), `(other: 정맥부위마취)` (1), `(other: 혈관주사)` (1), `(other: 박리)` (1), `(other: 진피내주사)` (1), `(other: 흉부신경차단)` (1), `(other: 문신)` (1), `(other: 좌골신경차단)` (1), `(other: 용해)` (1), `(other: 척추주위마취)` (1), `(other: 말초신경차단마취)` (1) |
| Surgical action (qualifier value) | 58 | `술` (32), `(other: 교정)` (9), `성형` (3), `절개` (2), `봉합` (2), `배액` (1), `(other: 고정)` (1), `창냄술` (1), `(other: 전방각천자)` (1), `(other: 형성)` (1), `(other: 박리)` (1), `(other: 살포)` (1), `(other: 용해)` (1), `우회술` (1), `(other: 해리)` (1) |
| Radiographic imaging - action (qualifier value) | 58 | `촬영` (31), `검사` (5), `조영` (5), `(other: 관장)` (4), `조영술` (4), `측정` (4), `조영상` (2), `(other: 쵤영)` (1), `흡인` (1), `촬영술` (1) |
| Aspiration - action (qualifier value) | 57 | `흡인` (48), `술` (3), `(other: 천자)` (3), `(other: 직장자궁오목천자)` (1), `(other: 유리체천자)` (1), `(other: 결장천자)` (1) |
| Examination - action (qualifier value) | 42 | `검사` (25), `측정` (6), `(other: 진찰)` (2), `(other: 평가)` (2), `(other: 부검)` (1), `(other: 굴절)` (1), `(other: 자가검진)` (1), `법` (1), `(other: 신체검진)` (1), `(other: 전위도)` (1), `(other: 검진)` (1) |
| Fixation - action (qualifier value) | 38 | `(other: 고정)` (23), `술` (2), `(other: 골접합)` (1), `(other: 부착)` (1), `(other: 유착)` (1), `(other: 질고정)` (1), `(other: 자궁고정)` (1), `(other: 방광고정)` (1), `(other: 힘줄고정)` (1), `(other: 모뿔연골고정)` (1), `(other: 모루등자관절고정)` (1), `(other: 난소고정)` (1), `절제` (1), `(other: 재부착)` (1), `(other: 비장고정)` (1) |
| Reconstruction - action (qualifier value) | 34 | `성형` (19), `재건` (9), `복구` (2), `술` (1), `이식` (1), `절제` (1), `(other: 고정)` (1) |
| Education - action (qualifier value) | 32 | `교육` (29), `법` (1), `(other: 계획)` (1), `(other: 지도)` (1) |
| Drainage - action (qualifier value) | 32 | `배액` (28), `(other: 배농)` (2), `(other: 감압)` (1), `(other: 세척기)` (1) |
| Radionuclide imaging - action (qualifier value) | 29 | `검사` (11), `영상` (7), `스캔` (5), `조영` (4), `조영상` (1), `(other: 섭취율)` (1) |
| Surgical removal - action (qualifier value) | 28 | `제거` (19), `술` (3), `절제` (3), `(other: 갈이증)` (1), `절개` (1), `(other: 탐색)` (1) |
| Insertion - action (qualifier value) | 26 | `삽입` (17), `(other: 삽관)` (4), `(other: 도뇨)` (1), `(other: 패킹)` (1), `(other: 매우기)` (1), `술` (1), `이식` (1) |
| Brachytherapy - action (qualifier value) | 24 | `요법` (23), `(other: 적용)` (1) |
| Construction - action (qualifier value) | 23 | `창냄술` (12), `절제` (5), `연결` (2), `삽입` (1), `이식` (1), `(other: 형성)` (1), `(other: 지연)` (1) |
| Division - action (qualifier value) | 20 | `절개` (9), `절단` (8), `술` (1), `절제` (1), `절개술` (1) |
| Doppler ultrasound imaging - action (qualifier value) | 18 | `검사` (15), `촬영` (3) |
| Bypass - action (qualifier value) | 18 | `우회술` (7), `연결` (2), `(other: 조성)` (2), `이식` (1), `우회` (1), `절개` (1), `(other: 전환)` (1), `(other: 이식편)` (1), `창냄술` (1), `(other: 형성)` (1) |
| Wedge resection - action (qualifier value) | 17 | `절제` (14), `생검` (2), `절개` (1) |
| Exteriorization - action (qualifier value) | 17 | `창냄술` (9), `절개` (2), `(other: 창냄)` (1), `봉합` (1), `연결` (1), `술` (1), `(other: 형성)` (1), `절제` (1) |
| Dissection - action (qualifier value) | 16 | `(other: 박리)` (12), `술` (2), `(other: 신장박리)` (1), `(other: 자궁관박리)` (1) |
| Plain X-ray imaging - action (qualifier value) | 16 | `촬영` (13), `술` (1), `(other: 쵤영)` (1), `검사` (1) |
| Destruction - action (qualifier value) | 14 | `(other: 파괴)` (4), `요법` (3), `술` (2), `치료` (1), `성형` (1), `(other: 섬모체투열)` (1), `(other: 신경박리)` (1), `절단` (1) |
| Removal - action (qualifier value) | 14 | `제거` (8), `술` (3), `절개` (1), `절제` (1), `(other: 피부벗김)` (1) |
| Puncture - action (qualifier value) | 13 | `(other: 천자)` (7), `(other: 뇌천자)` (1), `(other: 정맥천자)` (1), `흡인` (1), `(other: 허리천자)` (1), `(other: 후두천자)` (1), `(other: 폐천자)` (1) |
| Monitoring - action (qualifier value) | 12 | `(other: 감시)` (9), `검사` (1), `(other: 심전도)` (1), `측정` (1) |
| Replacement - action (qualifier value) | 11 | `교환` (5), `교체` (3), `치환` (1), `술` (1), `성형` (1) |
| Fluoroscopic imaging - action (qualifier value) | 11 | `투시술` (2), `(other: 용해)` (2), `촬영` (1), `성형` (1), `(other: 주사)` (1), `생검` (1), `검사` (1), `조영` (1), `확장` (1) |
| Management - action (qualifier value) | 11 | `(other: 관리)` (9), `(other: 통증조절)` (1), `(other: 스트레스관리)` (1) |
| Counseling - action (qualifier value) | 10 | `상담` (9), `요법` (1) |
| Irrigation - action (qualifier value) | 9 | `세척` (8), `(other: 화장실)` (1) |
| Surgical transplantation - action (qualifier value) | 9 | `이식` (8), `치환` (1) |
| Sampling - action (qualifier value) | 9 | `(other: 수집)` (6), `(other: 채취)` (1), `생검` (1), `흡인` (1) |
| Amputation - action (qualifier value) | 9 | `절단` (6), `절제` (2), `성형` (1) |
| Surgical augmentation - action (qualifier value) | 8 | `술` (3), `성형` (2), `확장술` (1), `(other: 코높임)` (1), `성형술` (1) |
| Application - action (qualifier value) | 8 | `치료` (2), `요법` (1), `(other: 드레싱)` (1), `법` (1), `(other: 적용)` (1), `(other: 도포)` (1), `(other: 고정)` (1) |
| Dilation - action (qualifier value) | 8 | `확장` (6), `삽입` (1), `술` (1) |
| Therapy - action (qualifier value) | 8 | `요법` (6), `(other: 조사)` (1), `치료` (1) |
| Maintenance - action (qualifier value) | 8 | `(other: 관리)` (6), `(other: 유지)` (1), `(other: 위생)` (1) |
| Grafting - action (qualifier value) | 7 | `이식` (5), `이식술` (2) |
| Shunt - action (qualifier value) | 7 | `(other: 션트)` (2), `술` (2), `창냄술` (1), `(other: 홍채폄)` (1), `(other: 형성)` (1) |
| Filtration - action (qualifier value) | 7 | `(other: 투석)` (2), `(other: 초미세여과)` (1), `(other: 혈액여과)` (1), `(other: 여과)` (1), `(other: 복막투석)` (1), `요법` (1) |
| Delivery - action (qualifier value) | 7 | `(other: 분만)` (5), `(other: 집게분만)` (1), `절개` (1) |
| Ligation - action (qualifier value) | 7 | `결찰` (4), `(other: 묶음)` (3) |
| Ablation - action (qualifier value) | 7 | `절제` (3), `치료` (2), `(other: 지짐)` (1), `술` (1) |
| Extraction - action (qualifier value) | 6 | `절개` (2), `절제` (1), `(other: 발치)` (1), `(other: 적출)` (1), `제거` (1) |
| Plication - action (qualifier value) | 6 | `형성술` (4), `성형술` (1), `(other: 형성)` (1) |
| Stimulation - action (qualifier value) | 6 | `(other: 자극)` (2), `술` (1), `(other: 신경자극)` (1), `(other: 자기자극)` (1), `(other: 반응)` (1) |
| Infusion - action (qualifier value) | 6 | `(other: 주입)` (4), `(other: 전정맥마취)` (1), `(other: 정맥마취)` (1) |
| Perfusion - action (qualifier value) | 6 | `(other: 관류)` (2), `(other: 산소공급)` (1), `(other: 혈액관류)` (1), `(other: 투석)` (1), `(other: 혈액투석)` (1) |
| Apheresis - action (qualifier value) | 5 | `교환` (2), `(other: 성분채집)` (1), `술` (1), `(other: 채집)` (1) |
| Reduction plasty (qualifier value) | 5 | `성형` (3), `(other: 코낮춤)` (1), `절제` (1) |
| Transposition - action (qualifier value) | 5 | `(other: 전위)` (2), `(other: 옮김)` (1), `절제` (1), `술` (1) |
| Cauterization - action (qualifier value) | 4 | `(other: 지짐)` (3), `술` (1) |
| Functional assessment - action (qualifier value) | 4 | `측정` (2), `(other: 검사명)` (1), `검사` (1) |
| Surgical extraction - action (qualifier value) | 4 | `(other: 적출)` (3), `흡인` (1) |
| Mobilization - action (qualifier value) | 4 | `(other: 박리)` (1), `(other: 가동)` (1), `절제` (1), `(other: 가동화)` (1) |
| Consultation - action (qualifier value) | 4 | `상담` (3), `(other: 자문)` (1) |
| Crushing - action (qualifier value) | 4 | `(other: 쇄석)` (2), `(other: 으깸)` (1), `(other: 관쇄석)` (1) |
| Surgical insertion - action (qualifier value) | 4 | `삽입` (3), `치환` (1) |
| Exenteration - action (qualifier value) | 4 | `(other: 적출)` (3), `절제` (1) |
| Manipulation - action (qualifier value) | 4 | `(other: 다루기)` (1), `(other: 수기)` (1), `(other: 회전)` (1), `(other: 강압교정)` (1) |
| Debridement - action (qualifier value) | 4 | `제거` (3), `봉합` (1) |
| Chemosurgery - action (qualifier value) | 4 | `절제` (2), `(other: 박피)` (1), `술` (1) |
| Cryosurgery - action (qualifier value) | 4 | `요법` (2), `술` (2) |
| Curettage - action (qualifier value) | 3 | `(other: 긁어냄)` (2), `술` (1) |
| Exploration - action (qualifier value) | 3 | `술` (1), `(other: 탐색)` (1), `(other: 개복)` (1) |
| Opening - action (qualifier value) | 3 | `절개` (2), `술` (1) |
| Transection - action (qualifier value) | 3 | `절단` (2), `절개` (1) |
| Chemical destruction (qualifier value) | 3 | `술` (1), `(other: 파괴)` (1), `절제` (1) |
| Cryotherapy - action (qualifier value) | 2 | `(other: 진통)` (1), `요법` (1) |
| Microsurgery - action (qualifier value) | 2 | `술` (1), `절제` (1) |
| Implantation - action (qualifier value) | 2 | `이식` (1), `삽입` (1) |
| Inflation - action (qualifier value) | 2 | `(other: 팽창)` (1), `(other: 폴리처통기)` (1) |
| Obliteration - action (qualifier value) | 2 | `술` (1), `(other: 폐쇄)` (1) |
| Evacuation - action (qualifier value) | 2 | `(other: 배설)` (1), `제거` (1) |
| Cryoablation - action (qualifier value) | 2 | `(other: 지짐)` (1), `절제` (1) |
| Harvesting - action (qualifier value) | 2 | `절제` (1), `제거` (1) |
| Cerclage - action (qualifier value) | 2 | `(other: 묶음)` (1), `(other: 원형묶음)` (1) |
| Occlusion - action (qualifier value) | 2 | `(other: 폐쇄)` (1), `법` (1) |
| Direct anastomosis - action (qualifier value) | 2 | `문합` (1), `연결` (1) |
| Electrocoagulation - action (qualifier value) | 2 | `(other: 파괴)` (1), `(other: 응고)` (1) |
| Refashioning - action (qualifier value) | 2 | `성형` (1), `(other: 라식)` (1) |
| Preparation - action (qualifier value) | 2 | `성형` (1), `(other: 조정)` (1) |
| Introduction - action (qualifier value) | 2 | `(other: 전달)` (1), `(other: 주입)` (1) |
| Abrasion - action (qualifier value) | 2 | `(other: 박피)` (1), `(other: 박리)` (1) |
| Doppler ultrasound - action (qualifier value) | 2 | `측정` (1), `(other: 초음파)` (1) |
| Decompression - action (qualifier value) | 2 | `술` (1), `(other: 감압)` (1) |
| Insufflation - action (qualifier value) | 2 | `(other: 관통기)` (1), `법` (1) |
| Scraping - action (qualifier value) | 2 | `(other: 찰과)` (1), `제거` (1) |

### Per-modality suffix LLM verdicts

- **Excision - action (qualifier value)** — INTENTIONAL; canonical: `절제`. _The variations represent distinct clinical actions (e.g., excision, anastomosis, creation of a fistula, or modification) rather than mere linguistic inconsistencies. '절제' is the most frequent term for excision, while other terms like '연결', '문합', and '창냄술' describe different surgical procedures._
- **Magnetic resonance imaging** — INTENTIONAL; canonical: `영상`. _The variations reflect different clinical components: '영상' is the base modality, '생검' indicates a procedure guided by the modality, '조영/조영술' refers to contrast-enhanced studies, and '검사' refers to specific functional tests like perfusion._
- **Ultrasound imaging** — INTENTIONAL; canonical: `검사`. _The variations represent different clinical actions performed using ultrasound, such as diagnostic examination (검사), scanning (스캔), aspiration (흡인), drainage (배액), and biopsy (생검). '검사' is the most frequent and appropriate general term for diagnostic ultrasound._
- **Evaluation - action (qualifier value)** — INTENTIONAL; canonical: `검사`. _The variations represent distinct clinical actions or specific findings (e.g., measurement, culture, phenotype, or specific diagnostic results) that cannot be unified into a single term. '검사' is the most frequent general term for 'examination/test', but the others are clinically necessary to specify the nature of the procedure._
- **Incision - action (qualifier value)** — INTENTIONAL; canonical: `절개`. _The variations represent distinct clinical actions (e.g., incision, excision, amputation, transplantation) rather than inconsistent naming of the same concept. '절개' is the most frequent term for simple incision, but each term describes a unique surgical procedure._
- **Measurement - action (qualifier value)** — INTENTIONAL; canonical: `측정`. _The variations represent distinct clinical actions or specific measurement types (e.g., calculation, electrophoresis, rate, or method) that cannot be unified into a single term. '측정' is the most frequent and general term for measurement-based procedures._
- **Computed tomography** — INTENTIONAL; canonical: `촬영`. _The variations reflect different clinical actions: '촬영' (imaging/scanning), '조영' (contrast enhancement), '생검' (biopsy), and '검사' (examination/inspection). These are distinct clinical contexts rather than inconsistent naming of the same procedure._
- **Inspection - action (qualifier value)** — INTENTIONAL; canonical: `술`. _The variation reflects different clinical actions performed during or via endoscopy (e.g., inspection, biopsy, resection, irrigation). '술' is the most frequent suffix used to denote the procedure itself, while other terms specify distinct clinical objectives._
- **Biopsy - action (qualifier value)** — INTENTIONAL; canonical: `생검`. _The term '생검' is the standard noun for biopsy, while '술' is a suffix used in specific procedural names (e.g., determination procedure), and '내시경' refers to the tool used. These represent different linguistic structures rather than inconsistent translations of the same concept._
- **Repair - action (qualifier value)** — INTENTIONAL; canonical: `성형`. _The variations represent distinct clinical actions (e.g., reconstruction vs. repair vs. excision) rather than inconsistent naming of the same concept. '성형' is the most frequent root for plastic/shaping procedures, while others like '복구', '봉합', and '절제' denote specific, different surgical techniques._
- **Closure - action (qualifier value)** — INTENTIONAL; canonical: `봉합`. _The variations reflect specific clinical nuances: '봉합' (suture/closure), '성형' (reconstruction/plasticity), '복구' (repair/restoration), and '술' (procedure suffix). Using a single term would lose the distinction between simple suturing and complex reconstructive or restorative actions._
- **Imaging - action (qualifier value)** — INTENTIONAL; canonical: `조영`. _The variations represent distinct clinical actions (e.g., '조영' for contrast enhancement, '조영술' for angiography, '배액' for drainage, '촬영' for imaging/photography) rather than inconsistent naming of the same concept._
- **Fine needle aspiration biopsy - action (qualifier value)** — INTENTIONAL; canonical: `생검`. _The variation distinguishes between 'biopsy' (생검) and 'aspiration' (흡인). While 'aspiration biopsy' (흡인 생검) is used, 'biopsy' (생검) is the more general and frequent term for the procedure type._
- **Anastomosis - action (qualifier value)** — INTENTIONAL; canonical: `연결`. _The variations reflect different clinical nuances: '연결' is a general term for connection, '문합' is a formal medical term for anastomosis, and '연결술' or '창냄술' are specific procedural names. '연결' is the most frequent and versatile base form._
- **Administration - action (qualifier value)** — INTENTIONAL; canonical: `—`. _The variations represent distinct clinical actions (e.g., administration, anesthesia, therapy, suppression) that cannot be unified into a single form. Each term describes a specific medical intent or procedure type._
- **Injection - action (qualifier value)** — INTENTIONAL; canonical: `주사`. _The variations represent distinct clinical actions (injection, nerve block, anesthesia, or tattooing) rather than inconsistent naming of the same concept. '주사' is the most frequent general term for injection, but specific clinical procedures require their own descriptive suffixes like '차단' or '마취'._
- **Surgical action (qualifier value)** — INTENTIONAL; canonical: `—`. _The variations represent specific, clinically distinct surgical actions (e.g., incision, suturing, drainage, reconstruction) rather than inconsistent renderings of a single term. Each term describes a unique procedural method or outcome._
- **Radiographic imaging - action (qualifier value)** — INTENTIONAL; canonical: `촬영`. _The variations reflect distinct clinical actions: '촬영' (imaging/photography), '검사' (examination/test), '조영/조영술' (contrast-enhanced study), and '측정' (measurement). Using a single term would lose the specific clinical nuance of the procedure performed._
- **Aspiration - action (qualifier value)** — INTENTIONAL; canonical: `흡인`. _The variation reflects different clinical terminologies: '흡인' is the standard noun for aspiration, '술' is a suffix used to denote a specific procedure (e.g., aspiration procedure), and '천자' refers to puncture, which is a distinct clinical action._
- **Examination - action (qualifier value)** — INTENTIONAL; canonical: `검사`. _The variations represent distinct clinical actions (e.g., measurement, physical examination, autopsy, or self-examination) that cannot be unified into a single term without losing clinical specificity._

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

- Clusters reviewed by LLM: **42**
  - classified ARBITRARY: 10
  - classified INTENTIONAL: 32
  - classified UNCLEAR / other: 0

### Implications

- Arbitrary clusters are candidates for KR release curation (canonicalise to the recommended form, add the other form as an acceptable synonym) or for explicit style-guide rules.
- Intentional clusters inform the style guide: document the contextual rule so translators can reproduce it.
- Unclear clusters need SME input from KHIS.

### Caveats

- LLM verdicts are directional, not authoritative. They reflect one model's reading; disagreements with KHIS's own policy should be resolved by KHIS.
- Axis 1 uses substring matching of body-structure-concept synonyms to detect the 'which rendering was used' signal. Procedures that re-phrase the body site without reusing the canonical terms will be counted as `(none detected)` — that column is itself a useful signal about free-form anatomical rendering.
- Axis 2's modality variant list is hand-curated. Unmatched rows may indicate either modality renderings we forgot or procedures that deviate in unexpected ways.
