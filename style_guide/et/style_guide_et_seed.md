# Estonian SNOMED CT translation — seed style guide

Seed guide for English -> Estonian translation of SNOMED CT clinical terms.
Deliberately minimal: a starting point to be replaced by a GEPA-optimised or
SME-induced guide (the way the Korean guides evolved), not a finished standard.

## Scope
Translate the English SNOMED CT term into clinical Estonian as used in Estonian
healthcare records and the SNOMED CT Estonian national extension (EE1000181).

## Principles
- Preserve the clinical meaning exactly; do not add, drop, or reinterpret detail.
- Use the term a clinician would write, not a literal word-for-word calque.
- Match the register and orthography of the Estonian national extension where a
  concept already has an Estonian description.
- Keep the FSN semantic type consistent (a procedure stays a procedure, a finding
  a finding); do not translate the parenthetical semantic tag as clinical text.
- Prefer established Estonian medical terminology; fall back to a transparent
  Latinate/loan form only where no settled Estonian term exists.
- Output the translation only — no explanation, transliteration, or English echo.

> Populate concrete rules (compounding, abbreviation handling, Latin vs native
> term selection, modality naming) from Estonian SME review once available.
