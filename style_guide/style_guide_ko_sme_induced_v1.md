# Korean SNOMED CT translation style guide (SME-induced v1)

---

## 1. Scope and goal

The reviewer consistently rewarded translations that read as **standard Korean clinical
terminology** — the register a hospital radiology/procedure worklist would actually use —
rather than a literal, word-for-word gloss of the English. Prefer the conventional term of art
over a transparent but non-idiomatic calque, while never adding or dropping clinical meaning.

---

## 2. Register: Sino-Korean vs native-Korean vs loanword

- **Sino-Korean and native-Korean anatomical terms are both acceptable** and are frequently
  treated as interchangeable synonyms (e.g. a native skeletal/organ name and its
  Sino-Korean equivalent). When a term has an established pair, either register is valid; the
  correction usually concerns *which body part* is named, not which register.
- **Keep register internally consistent within one term.** When a term lists several parallel
  anatomical sites (e.g. successive spinal regions, or several arteries), render them as a
  single parallel set in one register rather than mixing native and Sino-Korean across the
  members.
- **Prefer a descriptive Korean translation over a transliteration (loanword).** Bare
  phonetic transliterations of English medical words were routinely marked down. A
  transliteration may at most be offered as a *secondary* synonym after the descriptive term,
  never as the primary rendering.
- **Avoid English-derived loanwords when a Korean term of art exists** (e.g. do not carry an
  English "scan"-type loanword when the standard Korean modality noun with the "검사"
  examination suffix is available).

---

## 3. Orthography and spacing

- **Write established multi-morpheme technical compounds closed (no internal spaces).** Fixed
  modality and procedure compounds are conventionally set solid, not spaced out morpheme by
  morpheme. Machine output that inserts a space between every morpheme of a fixed compound was
  consistently corrected to the closed form.
- **Keep genuinely separate lexical units spaced.** Spacing is removed *within* a fixed
  compound, but distinct words (site, modality, modifier) remain separated by spaces.
- **Casing of Latin-letter tokens follows the conventional Korean orthography**, typically the
  lowercase form joined by a hyphen to its Korean qualifier where such a token appears (e.g.
  the plain-radiography abbreviation is written in its conventional lower-case hyphenated
  form, not spelled out as a long "radiographic imaging" phrase).

---

## 4. Word order and placement of modifiers

- **Front-load whole-study qualifiers.** Modifiers that scope the entire study — contrast
  usage (with / without contrast), imaging guidance (using X guidance), and similar
  study-level qualifiers — belong at the **beginning** of the Korean phrase, before the site
  and the base procedure, even when they appear at the end of the English source.
- **General order:** `[study-level qualifier] + [laterality] + [body site] + [base
  procedure/modality]`. The core noun (the modality or procedure) sits at the end; qualifiers
  cascade in front of it.
- **"with [accompanying procedure/finding]"** is expressed with an accompaniment
  construction (a "…를 동반한 …" / "…동반" pattern) and the accompanying element is placed as a
  leading qualifier, not appended after the main procedure.

---

## 5. Handling specific modifier classes

### 5.1 Laterality
- left / right / bilateral map to the standard laterality words; native (왼쪽/오른쪽/양쪽) and
  Sino-Korean (좌/우/양측) forms are both acceptable. Laterality precedes the site.

### 5.2 Contrast
- "with contrast" and "without contrast" each have a fixed standard rendering (contrast-used /
  contrast-not-used). Place them first (see §4). Do not omit the contrast state and do not
  invent one that the source does not state.

### 5.3 Approach / guidance
- Imaging **guidance** ("using X guidance") is rendered with the standard "유도하" (under-guidance)
  construction and front-loaded. Match the *named* modality of the guidance exactly — do not
  generalise a specific guidance modality up to a vaguer "imaging/radiologic guidance", and do
  not substitute a different modality.
- **Surgical/access approach morphemes are fixed and must be reproduced faithfully:**
  percutaneous → the "through-skin" morpheme (피부경유, or its Sino synonym 경피); transluminal →
  the "through-vessel/lumen" morpheme; a combined "percutaneous transluminal" chains both
  morphemes together. Do not drop, reorder, or leave one of these approach morphemes
  untranslated.
- **Locative "into [site]"** attaches the locative suffix (…내, "within") to the site, rather
  than leaving the site as a bare noun.

### 5.4 Quantifiers and coordinated sites
- Reproduce quantifiers such as "all [structures]" and coordinate lists of sites faithfully;
  coordinated sites may be joined with the standard conjunctions, and either the fully
  comma-listed or the "및"-joined form is acceptable as long as no site is added or lost.

---

## 6. Modality naming conventions

- **Cross-sectional / MR / CT modalities** use their established closed Korean compound nouns
  (magnetic-resonance-imaging, computed-tomography, etc.), written solid (§3).
- **Examination-type modalities take the "검사" (examination) suffix.** Modalities whose English
  is a bare "-scopy/-graphy/scan/fluoroscopy" examination are rendered with the examination
  noun plus 검사 (or, for some, the 술 "procedure" suffix), not as a bare stem. Leaving off the
  examination/procedure suffix (producing a bare modality stem) was a recurrent PARTIAL
  correction.
- **Combination / hybrid modalities** ("A with B", "A with computed tomography") are joined
  with a coordinating/combining connector (a "및 / 결합 / 동반"-type link) so that both modalities
  survive in the output.
- **Functional/quantitative add-ons** (e.g. a measured fraction, perfusion parameter) are
  preserved as named coordinated components, not dropped.

---

## 7. Suffix / derivation conventions for imaging and procedures

This was the single most systematic correction pattern. Distinguish the **result/image** from
the **procedure**:

- **English "-gram" (the produced image) → the image-noun suffix "조영상"** (…-contrast-image).
  A machine output ending in the bare procedure suffix for a source ending in "-gram" was
  repeatedly upgraded to the "-상" image form.
- **English "-graphy" (the imaging procedure) → "조영" or the procedure form "조영술".**
- **English "-graphy/-scopy/-scan" examinations → base + "검사" / "술"** (see §6).
- Generalise: choose the Korean derivational suffix by whether the English denotes the
  *image/result* (→ …상) or the *act/procedure* (→ …술 / …검사 / bare 조영). Keep this
  image-vs-procedure distinction even when the base morpheme is identical.
- Procedure verbs must be matched precisely: ablation, destruction, drainage, biopsy,
  aspiration, injection, block, etc. each have a distinct standard Korean verb-noun; do not
  collapse two different English procedure verbs onto one Korean word.

---

## 8. Faithfulness rules (no adding or dropping meaning)

- **Name the exact anatomical entity the source names.** The most common error class was a
  near-miss body part: translating a whole limb/region as a narrower sub-part (or vice-versa),
  or picking a neighbouring structure. Verify the site denotes exactly the English scope
  (whole limb vs a segment of it; a region vs an adjacent region).
- **Drop SNOMED filler nouns that carry no clinical content in Korean.** A trailing generic
  "structure" on a body-site term is not translated; render the site directly.
- **Translate clinical *meaning*, not surface words, for lexicalised qualifiers.** Where an
  English qualifier is a domain term of art whose real meaning differs from its literal words
  (e.g. a qualifier that in clinical usage denotes the *diagnostic* vs *screening* purpose of a
  study), render the intended clinical category, not a literal word-for-word gloss that would
  mislead.
- **Do not omit or invent qualifiers.** Contrast state, laterality, guidance modality,
  purpose/indication ("for [finding/condition]"), and temporal qualifiers (e.g.
  post-procedure / post-mortem) must all be preserved — each has a fixed standard morpheme —
  and none may be added if absent from the source.
- **Keep the modality word even when a purpose word is present.** When the English names both
  a screening/indication and the modality, retain the modality noun; do not let the
  purpose word absorb it.
- **Preserve indication clauses ("for [condition]").** A "for [finding]" purpose clause is
  kept as a leading purpose qualifier; the underlying pathology/indication term is translated
  with its standard clinical name.

---

## 9. Synonym handling

- Many source terms admit **more than one acceptable Korean rendering** (a native/Sino pair, or
  a descriptive term plus an accepted transliteration). When both are valid, the reviewer
  accepts either but flags the *preferred term*; where a house preferred term exists, lead with
  it and list the alternative as a synonym.
- A transliteration, when kept at all, is demoted to synonym status behind the descriptive
  Korean term (§2).

---

## 10. Quick checklist (apply to every term)

1. Are whole-study qualifiers (contrast, guidance, accompaniment) **front-loaded**? (§4)
2. Is every fixed modality/procedure compound **written closed**, with real words still
   spaced? (§3)
3. Does an English **-gram** end in the image suffix (…상) and a **-graphy/scan/-scopy** carry
   a procedure/examination suffix (술 / 검사 / 조영)? (§7)
4. Is the **exact** anatomical scope named — no widening, narrowing, or neighbour-swapping?
   (§8)
5. Are approach morphemes (percutaneous / transluminal), locative "into" (…내), and laterality
   all present and correctly placed? (§5)
6. Is any SNOMED filler ("structure") dropped, and any lexicalised qualifier translated for
   its clinical meaning rather than literally? (§8)
7. Is nothing added and nothing lost versus the source? (§8)
8. Is the register internally consistent, with loanword transliterations demoted to synonyms?
   (§2, §9)
