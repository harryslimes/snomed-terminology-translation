# Radiology editorial addendum (Korean SNOMED imaging procedures)

This addendum applies **only when the concept is a descendant of
`363679005 |Imaging (procedure)|`**. It supplements the base Korean style
guide and encodes the conventions from the KHIS radiology editorial guide
(`RadiologyEditorialGuide.md`). Where this addendum conflicts with the base
style guide, the addendum wins for imaging concepts.

## Anatomy and laterality

- For anatomical site names, prefer pure-Korean (고유어) forms first; use
  Sino-Korean (한자어) only when no pure-Korean form is standard.
- Laterality synonym preference, in decreasing order: `왼쪽 / 오른쪽`,
  `좌측 / 우측`, `왼 / 오른`, `좌 / 우`. Use the first form unless the source
  data establishes otherwise.

## Modality synonym ranking

Use the earliest matching synonym in each ordered list for the preferred
Korean term. Later synonyms are acceptable alternates.

| English modality | Korean synonym ranking (preferred → accepted) |
|---|---|
| X-ray | X선 > 엑스선 > 엑스레이 |
| Plain X-ray | 단순 X선 > 일반 X선 > 일반 엑스레이 |
| Computed tomography (CT) | 컴퓨터단층촬영 > 전산화단층촬영 |
| Magnetic resonance imaging (MRI) | 자기공명영상 |
| Ultrasound / Sonography / Echography | 초음파검사 > 초음파촬영술 |
| Fluoroscopy | 투시 |
| Series (e.g. upper GI series) | 조영술 |

Specific modality compound terms:

| English | Korean |
|---|---|
| High resolution computed tomography | 고해상 컴퓨터단층촬영 |
| Quantitative computed tomography | 정량 컴퓨터단층촬영 |
| Sonic computed tomography | 초음파 컴퓨터단층촬영 |
| Single photon emission computed tomography (SPECT) | 단일광자방출 컴퓨터단층촬영 |
| Magnetic resonance mammography | 자기공명유방촬영 |
| Magnetic resonance myelography | 자기공명척수조영 |
| Doppler ultrasonography | 도플러 초음파검사 |
| Duplex ultrasonography | 이중 초음파검사 |
| Upper gastrointestinal series | 상부위장 조영술 |
| Small bowel series | 소장 조영술 |

## Word-order templates

### Site + modality

For a simple imaging study of a single body site:

`[body site] + [modality]`

- Magnetic resonance imaging of breast → 유방 자기공명영상검사

### Contrast + site + modality

When the source names contrast usage, use the preferred / accepted pair:

`[body site] + [조영제 사용 | 조영제 미사용] + [modality]` (preferred)
`[body site] + [조영증강 | 비조영증강] + [modality]` (accepted alternate)

- Computed tomography of upper extremity with contrast → 상지 조영제 사용 컴퓨터단층촬영 (preferred) / 상지 조영증강 컴퓨터단층촬영 (accepted)
- Computed tomography of shoulder without contrast → 어깨 조영제 미사용 컴퓨터단층촬영 (preferred) / 어깨 비조영증강 컴퓨터단층촬영 (accepted)
- Computed tomography of chest without contrast (high resolution) → 흉부 조영제 미사용 고해상도 컴퓨터단층촬영 (preferred) / 흉부 비조영증강 고해상도 컴퓨터단층촬영 (accepted)
- Computed tomography of adrenal gland without contrast → 부신 조영제 미사용 컴퓨터단층촬영 (preferred) / 부신 비조영증강 컴퓨터단층촬영 (accepted)

### Site + view + modality

When the source names a projection / view:

`[body site] + [view] + [modality]`

View translations (preferred / accepted):

| English view | Korean view (preferred / accepted) |
|---|---|
| anteroposterior | 앞뒤 / 전후면 |
| posteroanterior | 뒤앞 / 후전면 |
| apical and lordotic | 첨단 및 전만상 / 폐첨 전만위상 |

- Plain X-ray of chest, apical and lordotic views → 흉부 첨단 및 전만상 일반 X선 촬영 (preferred) / 흉부 폐첨 전만위상 일반 X선 촬영 (accepted)
- Plain X-ray of pelvis, anteroposterior view → 골반 앞뒤 일반 X선 촬영 (preferred) / 골반 전후면 일반 X선 촬영 (accepted)
- Plain X-ray of chest, posteroanterior view → 흉부 뒤앞 일반 X선 촬영 (preferred) / 흉부 후전면 일반 X선 촬영 (accepted)

### Timing + site + contrast + view + modality

When the source specifies timing (intraoperative, postoperative, real-time):

`[timing] + [body site] + [contrast] + [view] + [modality]`

- Intraoperative ultrasound of blood vessel → 수술중 혈관 초음파검사
- Intraoperative computed tomography of head → 수술중 머리 컴퓨터단층촬영

### Approach + site + modality

When the source specifies an access route (transvaginal, transrectal):

`[approach] + [body site] + [modality]`

- Transrectal ultrasonography of prostate → 경직장 전립선 초음파검사
- Transvaginal obstetric ultrasonography → 질경유 산과 초음파검사

### Bone density scans

Three templates depending on source structure:

- `[body site] + [method] + 골밀도 검사` — general pattern.
- `[body site] + 골밀도 검사` — for the "Bone density scan of X" form.
- `[body site] + 정량 컴퓨터단층촬영기반 골밀도 검사` — for
  "Computed tomography bone density study of X".

Examples:

- Bone density scan of distal radius → 원위 요골 골밀도 검사
- Computed tomography bone density study of femur → 대퇴 정량 컴퓨터단층촬영기반 골밀도 검사

### Bone density T / Z scores

- `[body site] + [test] + [Z점수 | T점수]` — general pattern.
- `[body site] + 정량적 컴퓨터단층촬영 골밀도 [Z점수 | T점수]` — for the
  "CT bone density study T / Z score" form.
- `[body site] + 이중 에너지 X선 흡수 측정 [Z점수 | T점수]` — for the
  "dual energy X-ray photon absorptiometry scan Z score" form.

Examples:

- Femoral trochanter computed tomography bone density study T score → 넙다리뼈 돌기 정량적 컴퓨터단층촬영 골밀도 Z점수
- Hip dual energy X-ray photon absorptiometry scan Z score → 엉덩이관절 이중 에너지 X선 흡수 측정 Z 점수

## Notes

- Spacing inside modality compound terms is written **without internal
  spaces** in this guide (e.g. `컴퓨터단층촬영`, not `컴퓨터 단층 촬영`).
  The base Korean style guide observes the opposite pattern in some KR
  release data. Until KHIS confirms, prefer the unspaced form when this
  addendum is active.
- The (preferred / accepted) synonym distinction maps to SNOMED's
  preferred term vs acceptable synonym — use the preferred form when
  producing a single translation.
