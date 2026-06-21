<!--
Auto-generated style-guide additions, revised after regression analysis.
Inputs: 30 target errors, 40 regressions
  (sampled from 40 regressions vs v1)
Proposed by: gemma4-26b (cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit)
Generated: 2026-04-14 12:57:32
-->

## Proposed additions (from error analysis, revised)

### Avoid phonetic transliteration for established medical concepts
Do not use phonetic transliterations (e.g., English loanwords written in Hangul) when a standard Sino-Korean or descriptive Korean medical term is the established clinical reference. Transliteration should be reserved for modern technology, specific drug names, or when no Korean equivalent is clinically recognized.

**Rationale:** Several errors involved translating common procedural terms like `debridement` into phonetic Hangul (`데브리망`) instead of the established descriptive Korean (`죽은 조직 제거`).

| English | Avoid (Transliteration) | Prefer (Standard Korean) |
|---|---|---|
| Debridement | 데브리망 | 죽은 조직 제거 |
| Plasmapheresis | 플라즈마페레시스 | 혈장분리 교환 |

### Maintain distinction between specific anatomical structures and generic terms
Ensure that terms describing specific anatomical structures or pathologies (e.g., `ureterocele`, `pouch of Douglas`, `limbus`) are not translated into generic or different anatomical terms (e.g., `cyst`, `cecum`, `peritoneum`). 

**Rationale:** Errors occurred where specific anatomical pathologies or locations were generalized into incorrect or different structures (e.g., translating `ureterocele` as `ureteral cyst` or `pouch of Douglas` as `cecum`).

### Use established terminology for anatomical sites and clinical entities
Prefer the terminology used in the KR reference data for anatomical sites. While Sino-Korean is often preferred for internal organs, do not override established pure Korean terms (e.g., `가슴` for thorax, `머리뼈` for skull, `볼기` for buttock) with Sino-Korean alternatives (e.g., `흉부`, `두개골`, `엉덩이`) if the reference uses the pure Korean form.

**Rationale:** New rules attempting to force Sino-Korean caused regressions in terms where pure Korean is the standard (e.g., `머리뼈`, `가슴`, `볼기`).

### Distinguish between "Anastomosis/Connection" and "Stoma Creation"
Do not use terms for stoma creation (e.g., `창냄술`, `조루술`) when the English term specifies a connection or anastomosis (e.g., `anastomosis`, `connection`). Conversely, do not use `연결` (connection) when the procedure specifically describes the creation of a stoma/opening.

**Rationale:** A recurring pattern of error involved conflating `anastomosis` (connecting two structures) with `ostomy` (creating an opening/stoma), leading to clinically different meanings.

| English | Preferred Korean | Note |
|---|---|---|
| Anastomosis / Connection | **연결** / **문합** | Joining two structures. |
| Stoma creation / Ostomy | **창냄술** / **조루술** | Creating an opening. |

### Avoid literal translation of complex English modifiers and maintain hierarchy
Do not perform word-for-word literal translations of English noun phrases that describe a single medical concept or a relationship between two techniques. When an English term combines two distinct methods (e.g., `A using B`), ensure the Korean reflects the hierarchy of the procedure. 

**Critical:** For `with` (subordinate step), follow the pattern: `[Secondary Procedure] 동반 [Main Procedure]`. For `using` or `by`, follow the pattern: `[Method/Device] 유도하 [Procedure]` or `[Method/Device] 이용 [Procedure]`.

**Rationale:** Over-generalizing "complex modifiers" caused regressions in established patterns like `with` (reversal) and `using` (guidance).

### Do not add clinical or administrative detail not present in the source
Do not expand a general concept into a specific clinical action or a billing-related term. If the source is a general concept (e.g., `Consultation`), do not translate it as a specific fee-based action (e.g., `Consultation fee`).

**Rationale:** Translators occasionally added "extra" information, such as turning a general concept into a specific "examination fee" or adding "differential" to a blood count where it was not specified.
