Translate the given English SNOMED CT procedure term into Korean, adhering to strict medical nomenclature and semantic precision standards.

### Constraints & Rules:
1. **Output Format:** Output ONLY the Korean translation. Do not include any explanations, introductory text, or quotation marks.
2. **Punctuation:** Korean SNOMED terms must NOT end with punctuation (no periods, no commas). Commas should only be used within list-like constructions.

### Semantic Accuracy & Terminology Rules (Crucial):

#### A. Preserve Procedural Head Nouns (Imaging vs. Modality)
In SNOMED CT, it is critical to maintain the distinction between a *modality* (the tool) and a *procedure* (the act of performing the scan). 
- Do **NOT** omit the procedural head noun if the English term specifies an action.
- **Mapping Rules for Imaging/Diagnostics:**
    - If the term is "[Modality] scan" $\rightarrow$ Use **[Modality] 스캔** (e.g., "Ultrasound scan" $\rightarrow$ "초음파 스캔").
    - If the term is "Ultrasonography of [Anatomy]" $\rightarrow$ Use **[Anatomy] 초음파검사** or **[Anatomy] 초음파촬영** (e.g., "Ultrasonography of liver" $\rightarrow$ "간 초음파검사" or "간 초음파촬영").
    - **Avoid Bare Modalities:** Do not simply translate "Ultrasonography" as "초음파" (modality); you must add the procedural suffix (검사 or 촬영) to preserve the medical scope.

#### B. Anatomical Precision
- Use **canonical, established Korean anatomical vocabulary**. 
- Favor standard clinical terms over ad-hoc Sino-Korean back-formations from muscle names.
- **Example:** For "calf," use **장딴지** (standard anatomical term) rather than "비복부" (which can be misread or is considered obscure/incorrect in this context).
- Use the most widely accepted clinical terms (e.g., choosing "액와" vs "겨드랑이" based on formal clinical context, but prioritizing the term that matches the most common medical registry usage).

#### C. Handling Classifiers (The "Omission" Exception)
- **When to Omit:** Only omit "procedure", "method", or "technique" if they function as a redundant hierarchical tag that does not change the core medical meaning (e.g., "Ultrasonic guidance procedure" $\rightarrow$ "초음파 유도").
- **When to Keep:** Do **NOT** omit words that define the specific type of medical action (like "scan" or "ultrasonography") as these are essential to the SNOMED CT hierarchy.

### Workflow:
1. **Analyze the English term:** Determine if it is a simple modality, a specific imaging procedure (scan/ultrasonography), or a guidance method.
2. **Identify the Anatomical target:** Select the most canonical Korean medical term for the body part.
3. **Select the Procedural Head:** Map "scan" $\rightarrow$ "스캔", "ultrasonography" $\rightarrow$ "초음파검사/촬영", etc.
4. **Verify Lexical Mapping:** Ensure the Korean term allows for a one-to-one mapping back to the English source to prevent semantic collapsing (e.g., ensure "scan" and "ultrasonography" result in different Korean terms).