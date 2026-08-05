You are given a pruned corpus of English->Korean SNOMED CT translation evidence. It has four parts:
- A. Model critiques of naive machine translations: each gives the naive output, a suggested fix, and a reasoned convention (often grounded with Korean body-site/modality dictionary lookups). Treat these as STRONG PRIORS, not gospel — they are model-generated and not yet human-verified.
- B. Gold minimal pairs: terms differing by ONE feature (laterality, contrast, with/without), which isolate how that single feature maps.
- C. Gold reference pairs: diverse correct EN->KO mappings across construction patterns.
- D. Breadth pairs: clean SNOMED pairs beyond procedures.

Your task: write a concise, actionable INSTRUCTION GUIDE that a smaller translation model can follow to translate EN SNOMED terms into the Korean a clinician would file. Requirements:
1. Derive RULES from the evidence — word order (head-final / slot order), nominalisation (-술 vs bare stem), Sino-Korean vs pure-Korean vocabulary choice, canonical modality forms, scope preservation (don't add/drop/narrow), particles and spacing.
2. For EVERY rule, cite the example IDs that motivate it (e.g. (A11, A22)) and give a counter-example where useful.
3. Provide a canonical lexicon table (English -> preferred Korean) for the recurring modalities/anatomy/actions you observe.
4. Explicitly flag any INCONSISTENCIES in the gold data (e.g. competing conventions) as open questions for SME ruling, rather than silently picking one without noting it.
5. End with a short self-check checklist the translator runs before answering.

Output ONLY the guide as Markdown. Do not translate the corpus; analyse it and produce the guide.

--- CORPUS ---
{{context}}