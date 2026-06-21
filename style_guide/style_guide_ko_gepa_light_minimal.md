# Korean SNOMED CT Medical Terminology Translation

Translate the provided English SNOMED CT procedure term into its standardized Korean medical equivalent. The goal is to match the specific nomenclature used in Korean clinical databases (e.g., hospital EMRs, National Health Insurance standards) and official SNOMED CT mappings.

## Core Objective
Identify the clinical concept described by the English term and provide the most professional, standard Korean medical equivalent. Do not perform a literal word-for-word translation; instead, aim for the term a Korean clinician or medical coder would actually use.

## Constraints & Guidelines

- **Output Format:** Output ONLY the Korean translation in Hangul. Do not include English, romanization, punctuation, or any explanatory text.
- **Style & Register:** 
    - Use formal, professional medical terminology.
    - **Idiomatic Substitution:** Replace descriptive English phrases with standardized Korean medical compounds. 
        - *Example:* Instead of "조영제 없는" (without contrast), use "조영제 미사용" or "비조영".
        - *Example:* Instead of "동반된" (with/accompanied by), use "동반" or specific clinical conjunctions.
- **Spacing & Formatting (Crucial):** 
    - While many technical terms are compounded, Korean medical nomenclature in databases frequently utilizes spaces to separate anatomical regions, modalities, and conditions for readability. 
    - **Do not force all words into a single unspaced string.** If the standard clinical term uses spaces (e.g., "컴퓨터 단층 촬영" instead of "컴퓨터단층촬영"), prioritize the spaced version to match the "accepted reference" style used in professional settings.
- **Terminology Selection:**
    - **Anatomical Precision:** Use standard medical terms for anatomy (e.g., "시신경공" for optic foramen, "복부" for abdomen).
    - **Modality Standard:** Ensure imaging modalities are translated using their standard clinical names (e.g., "컴퓨터 단층 촬영" for CT, "양전자 단층 촬영" for PET).
    - **Concept Mapping:** If the English term describes a specific procedure (e.g., "Diagnostic radiography of..."), the Korean equivalent should reflect the standard clinical name for that procedure (e.g., "...X선 촬영" or "...방사선 영상 촬영").

## Translation Strategy
1. **Deconstruct:** Break down the English term into [Modality] + [Anatomy] + [Condition/Contrast status].
2. **Identify Concept:** Determine the clinical procedure being performed.
3. **Retrieve/Synthesize:** Recall the standard Korean medical phrasing for that specific combination. 
4. **Refine:** Check if the phrase sounds like a "textbook translation" (bad) or a "clinical record" (good). If it sounds like a textbook, rephrase it into a concise medical compound.

## Task Input
### english_term
[Insert English term here]

## Generated Output
### korean