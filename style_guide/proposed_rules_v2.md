<!--
Auto-generated style-guide additions.
Source: 30 consensus-WRONG errors from
  judge_gemma4-26b.csv and judge_qwen35b.csv
Proposed by: gemma4-26b (cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit)
Generated: 2026-04-14 11:35:53
-->

## Proposed additions (from error analysis)

### Avoid phonetic transliteration for established medical concepts
Do not use phonetic transliterations (e.g., English loanwords written in Hangul) when a standard Sino-Korean or descriptive Korean medical term exists. Transliteration should be reserved for modern technology, specific drug names, or when no Korean equivalent is clinically recognized.

**Rationale:** Several errors involved translating common procedural terms like `debridement` into phonetic Hangul (`데브리망`) instead of the established descriptive Korean (`죽은 조직 제거`).

| English | Avoid (Transliteration) | Prefer (Standard Korean) |
|---|---|---|
| Debridement | 데브리망 | 죽은 조직 제거 |

### Maintain distinction between anatomical structures and clinical entities
Ensure that terms describing specific anatomical structures (e.g., `ureterocele`, `pouch of Douglas`, `limbus`) are not translated into generic or different anatomical terms (e.g., `cyst`, `cecum`, `peritoneum`). 

**Rationale:** Errors occurred where specific anatomical pathologies or locations were generalized into incorrect or different structures (e.g., translating `ureterocele` as `ureteral cyst` or `pouch of Douglas` as `cecum`).

### Use standard Sino-Korean terminology for professional clinical use
Avoid using overly colloquial or "pure Korean" (고유어) terms for anatomical sites and procedures in a professional medical context unless they are the established standard. Stick to the Sino-Korean terms used in official medical coding (KCD/KOSTOM).

**Rationale:** Candidates frequently used non-medical or colloquial terms (e.g., `곧창자` instead of `직장`, `샛길` instead of `누공`, `창냄술` instead of `조루술/연결`) which are inappropriate for formal medical records.

### Distinguish between "Connection/Anastomosis" and "Stoma Creation"
Do not use terms for stoma creation (e.g., `창냄술`, `조루술`) when the English term specifies a connection or anastomosis (e.g., `anastomosis`, `connection`). Conversely, do not use `연결` (connection) when the procedure specifically describes the creation of a stoma/opening.

**Rationale:** A recurring pattern of error involved conflating `anastomosis` (connecting two structures) with `ostomy` (creating an opening/stoma), leading to clinically different meanings.

| English | Preferred Korean | Note |
|---|---|---|
| Anastomosis / Connection | **연결** / **문합** | Joining two structures. |
| Stoma creation / Ostomy | **창냄술** / **조루술** | Creating an opening. |

### Avoid literal translation of complex English modifiers
Do not perform word-for-word literal translations of English noun phrases that describe a single medical concept or a relationship between two techniques. When an English term combines two distinct methods (e.g., `A using B`), ensure the Korean reflects the hierarchy of the procedure rather than a flat list of terms.

**Rationale:** Errors were noted where translators either combined two distinct techniques into one confusing phrase or failed to recognize that one technique was the method used to perform the other (e.g., `PCR polyacrylamide gel electrophoresis`).

### Do not add clinical or administrative detail not present in the source
Do not expand a general concept into a specific clinical action or a billing-related term. If the source is a general concept (e.g., `Consultation`), do not translate it as a specific fee-based action (e.g., `Consultation fee`).

**Rationale:** Translators occasionally added "extra" information, such as turning a general concept into a specific "examination fee" or adding "differential" to a blood count where it was not specified.
