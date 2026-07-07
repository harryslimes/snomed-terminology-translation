# Korean SNOMED CT translation style guide (SME-induced v2)

This guide was **induced from expert review feedback** on roughly one hundred machine-translated SNOMED CT terms (predominantly imaging, image-guided-procedure and nuclear-medicine concepts). It was written by analysing the **direction of the reviewer's edits**: for every reviewed item where the expert's corrected Korean differed from the machine output, we asked *what did the reviewer change, and which way did they push it?* Each rule below states that direction as a general, reusable preference, together with how consistently the edits pointed that way. No specific reviewed term or its translation is reproduced here; the guide teaches the reviewer's rules, not their answers. Apply these to unseen terms.

Rules are ordered roughly by how strong and how frequent the signal was.

---

## 1. Orthography — close up multi-word technical compounds (very strong, near-universal)

The single most frequent edit was **spacing**. The reviewer repeatedly removed the internal spaces the machine had inserted inside a fixed technical compound, writing it as one unbroken word.

- **Modality / examination names are closed compounds.** Standard imaging-modality names are written with **no internal spaces**: e.g. 자기공명영상 (MRI), 컴퓨터단층촬영 (CT), 단일광자방출컴퓨터단층촬영 (SPECT), 초음파검사 (ultrasonography). The machine's space-separated forms (자기 공명 영상, 컴퓨터 단층 촬영, …) were corrected almost every time they appeared. Treat the whole modality name as a lexical unit.
- **Contrast/-graphy examination heads close up too:** 관절조영, 정맥조영, 혈관조영(술), 담낭조영(상), 척수조영(상) are written solid, not 관절 조영 etc.
- **Approach phrases close up:** the access descriptors are written solid — 피부경유 (percutaneous), 혈관경유 (transluminal), and the frequent pair 피부경유혈관경유 (percutaneous transluminal). The machine's spaced 피부 경유 / 혈관 경유 were routinely joined.
- **Where spaces stay:** spaces are retained *between distinct elements* of a term (modifier vs body site vs modality vs procedure), and around list separators. The rule is "close up the fixed compound, keep the phrase-level joints spaced" — not "delete all spaces."

**Consistency: very high.** This was corrected wherever it occurred and is the safest rule in the guide.

## 2. Modality suffixes / derivation — supply the right examination or image suffix (strong)

The reviewer consistently **added or corrected the suffix that marks what kind of study a term is**, rejecting a bare noun or the wrong nominaliser. Learn the suffix contrast, not individual words.

- **`-graphy` vs `-gram`: procedure vs image.** A `-graphy` term names the *procedure/examination* and takes the plain 조영/조영술 (or …검사) head; a `-gram` term names the *resulting image* and must carry the image suffix **-상** (…조영상). The machine tended to drop the -상 on image (`-gram`) terms; the reviewer added it. Rule: translate `-graphy` → 조영/조영술, and `-gram` → 조영상 (image), keeping the two apart.
- **`fluoroscopy` needs an examination suffix.** A bare 투시 was consistently upgraded to 투시검사 (or 투시술). Do not leave 투시 standing alone as the whole translation of *fluoroscopy*.
- **`ultrasonography`/`ultrasound scan` → 초음파검사.** Renderings using 촬영 or a transliterated "스캔" for an ultrasound study were corrected to 검사. For ultrasound, the study suffix is 검사, not 촬영 or 스캔.
- **`X-ray` → the concise 방사선 head is over-long; prefer …x선.** Where the machine expanded plain radiography into a long 방사선 영상 촬영 string, the reviewer shortened it to the compact **x선** form (and "plain X-ray" → 일반 x선). Orthography detail: the reviewer writes the letter **lower-case and joined to 선 (x선)**; a hyphenated X-선 also appears in notes. Prefer the short x선 form over a long descriptive paraphrase.

**Consistency: high** across every suffix family above; the direction (add the correct study/image suffix, prefer the compact standard head) never reversed.

## 3. Register (한자어 vs 고유어) — direction depends on the anatomical category (clear, category-specific)

The reviewer did **not** treat Sino-Korean and native-Korean as freely interchangeable. The swaps show a consistent direction *within each category*:

- **Limbs → native (고유어).** For the extremities the reviewer moved Sino-Korean to native: *lower limb/extremity* → 다리 (away from 하지 when 하지 was the whole rendering), and *upper limb/extremity* → 팔. Prefer the native limb words 다리 / 팔 for the whole limb. (Both notes acknowledge the Sino 하지/상지 as valid synonyms, but the corrections moved toward native.) **Consistency: high for limbs.**
- **Body regions → native.** Region modifiers were nativised, e.g. the lumbar region → 허리(부위) rather than the Sino 요(부위). Prefer native region words. **Consistency: high where it occurred.**
- **Deep/internal thoraco-abdominal anatomy → Sino (한자어).** The direction *reverses* for deep internal structures: native descriptive coinages were replaced by the established Sino clinical term — *retroperitoneum* → 후복막 (not the native "복막뒤"), *mediastinum* → 종격동 (not the native "세로칸"). For deep cavity/space anatomy, prefer the standard Sino term. **Consistency: high (every occurrence pushed Sino).**
- **Bones and surface joints → native, Sino accepted as synonym.** Native osteonyms (팔뼈, 위팔뼈, 엉덩뼈, 정강뼈, 종아리뼈, 발꿈치뼈, 절구, …) were kept or preferred, with the Sino equivalent (상지골, 장골, 비구, …) noted as an acceptable synonym. Prefer native bone/joint names; Sino is a valid alternate. **Consistency: moderate–high.**
- **Nerve plexus → native.** *plexus* was moved toward native 신경얼기 (from Sino 신경총), though 신경총 survives as an accepted synonym. Slight native preference.

**Summary of the register axis:** native-Korean for **limbs, external body regions, bones and surface joints**; Sino-Korean for **deep internal thoracic/abdominal spaces**. Do not default globally to one register — choose by category.

## 4. Laterality — native forms are the norm (stable)

Laterality is rendered with the **native** set 왼쪽 / 오른쪽 / 양쪽 (left / right / both), and this was the accepted norm throughout; the one relevant edit moved a Sino 양측 toward native 양쪽. The Sino set 좌측 / 우측 / 양측 appears as acceptable synonyms and was often left unchanged, but where the reviewer intervened the push was toward native. **Prefer native laterality words**, and keep laterality as a front modifier of the body site (see §5). **Consistency: high for the native default; 양측/양쪽 both tolerated.**

## 5. Constituent order — front-load contrast and guidance modifiers (strong, explicit)

The reviewer repeatedly **relocated whole modifier phrases to the front of the term**, and left explicit notes to do so.

- **Contrast status goes first.** Both 조영제 사용 ("with contrast") and 조영제 미사용 ("without contrast") belong at the **beginning** of the phrase. When the machine appended the contrast phrase to the end, the reviewer moved it to the front. **Consistency: high; direction never reversed.**
- **Imaging guidance goes first.** The "using X guidance" phrase (…유도하) is placed at the **front** as well; a trailing guidance phrase was moved forward. **Consistency: high.**
- **"with X" accompaniment → …를 동반한, placed before the head it modifies.** Accompanying-procedure phrases ("with insertion of stent", etc.) are rendered as X를 동반한 and positioned ahead of the main procedure, not tacked on at the end.
- **General ordering that emerges:** [contrast] → [guidance] → [accompaniment] → [laterality + body site] → [modality] → [procedure/study head]. Modifiers precede what they modify, and the sentence-level qualifiers (contrast, guidance) sit furthest front.

## 6. Translate the guidance/approach *modality*, don't generalise it (moderate)

When the source names a specific guidance or approach, keep it specific:
- *fluoroscopic guidance* → 투시 유도하 — a generic "영상 유도하 (image-guided)" was corrected back to the specific 투시. Translate *fluoroscopic* as 투시, *radiologic* as 방사선, *ultrasound* as 초음파, etc.; do not flatten a named modality into a generic "imaging."
- Approach descriptors are rendered in full and in fixed order: percutaneous → 피부경유/경피, transluminal → 혈관경유 (see §1 for spacing). Both 피부경유 and 경피 are accepted for *percutaneous*.

## 7. Faithfulness — match the source's meaning and scope exactly (strong, recurring)

A large block of edits corrected **meaning, scope and added/dropped material**. The direction is consistently "say exactly what the source says — no more, no less."

- **Do not add anatomy the source doesn't name.** The reviewer removed extra body-part words the machine had invented or over-specified (e.g. an added auricle word on an external-auditory-meatus term; an added uterus word on a female-genital study; an over-specific "upper arm" where the source said only "upper limb"). Rule: don't narrow or embellish the anatomical scope.
- **Do not drop material the source names, and repeat a shared head when scope requires it.** Where an organ needed to be named both as the target and within the study type, the reviewer restored it. Preserve every named structure.
- **Do not translate the filler noun "structure" in body-site terms.** "…vascular structure of…" style terms drop 구조; render just the body site. This was called out explicitly. Generalise: skip semantically empty scaffolding nouns ("structure", and similar) in body-site expressions.
- **Locative "into / in X" takes the -내 suffix.** "into breast", "in intracranial vessel" and similar were marked with the locative 내 (유방내, 두개내, …). Render "into/within a site" with …내, don't leave it as a bare noun.
- **Translate the clinical meaning, not the surface words, when the term is an idiom.** Several outright-wrong items were corrected to the *concept's* meaning rather than a literal gloss: a "symptomatic" study that clinically denotes a diagnostic study → the diagnostic reading; "postmortem" → 사후 (not an autopsy word); a proprietary/portmanteau study name → its standard descriptive equivalent rather than a transliteration. Rule: for eponyms, portmanteaus and clinical idioms, translate the established clinical concept, and avoid bare transliteration when a real Korean term exists.

**Consistency: high.** Faithfulness edits appear across many rows and always push toward exact, non-embellished, concept-correct rendering.

---

## Quick checklist for an unseen term

1. **Close up** the modality name, the …조영 head, and the approach words into solid compounds; keep spaces only at phrase joints.
2. Give the study its **correct suffix**: `-graphy`→조영/조영술 or …검사, `-gram`→조영상, fluoroscopy→투시검사, ultrasonography→초음파검사, X-ray→…x선.
3. Pick **register by category**: native for limbs/regions/bones/surface joints (다리, 팔, 허리, native osteonyms); Sino for deep internal spaces (후복막, 종격동).
4. Use **native laterality** (왼쪽/오른쪽/양쪽).
5. **Front-load** contrast (조영제 사용/미사용) then guidance (…유도하) then accompaniment (…를 동반한); modifiers precede their head.
6. Keep the **named guidance/approach modality specific**; don't generalise 투시 to "영상".
7. **Be faithful**: don't add or drop anatomy, drop empty "structure" nouns, mark "into/in" with …내, and translate clinical idioms/eponyms by their established concept, not literally.
