# Translation project-template handover

**Prepared:** 2026-08-26  
**Source:** the long Claude Code project conversation on GX10, with the last
substantive reply at 2026-08-25 08:06 BST. The final later Claude output was
an organisation/subscription access error, not project work.

## Executive summary

The conversation turned the lessons from the English-to-Korean SNOMED CT
translation project into a reusable `translation_process` project template.
The template installs the process structure, plan, gates, flows, standing
methodological conclusions, starter rules, and source definitions into a new
language project. A Korean greenfield demonstration named `kog` was then
scaffolded and brought online to prove that the template can be instantiated
without an existing target-language archive.

The implementation is complete and committed in the
`snomed-terminology-translation` repository. The demo is live on GX10, but it
is intentionally at the cold-start stage: its English domain slice exists,
while its bilingual exemplar pool and adjudicated gold are empty. The first
real task is therefore to source those gating inputs; a cascade run should not
be started until that is done.

## Project topology

The registered project is an umbrella directory, not a Git repository itself:

```text
/home/jc2301/Projects/semi-automated-research-with-language-translation/
├── semi-automated-research/
├── snomed-terminology-translation/
└── snomed_translation_poc_2/
```

The current GX10 state observed during this handover was:

| Repository | Branch | State | Latest relevant commit |
|---|---|---|---|
| `semi-automated-research` | `fix/multi-ref-eval-scoring` | clean, 2 commits ahead of its remote branch | `fdf91ae` — exposes template choice and `rf2_relationship_file` |
| `snomed-terminology-translation` | `feat/sme-batch2-integration` | 23 commits ahead of its remote branch; four tracked files modified | `7ea7668` — `kog` demo seeded from the template |
| `snomed_translation_poc_2` | `feature/qwen122b-translation-pipeline` | heavily dirty legacy/POC checkout with many untracked files | `5f4c2f6` |

Do not run a broad cleanup, reset, or checkout operation in this umbrella.
The dirty files and untracked material in the second and third repositories
contain project work and research artefacts from the conversation.

## What was built

### The playbook

The process was first formalised in:

```text
snomed-terminology-translation/docs/language_project_guide_2026-08-25.md
```

Commit: `5878157` (`Guide: running a language translation project on the
platform`). Claude also published a private shareable copy as the **SNOMED
Translation Playbook**.

The central process is a seven-step SME round loop:

1. Package a blinded, stratified review sample.
2. Send it to the SME and collect both ratings and adjudication questions.
3. Ingest the returned review and measure tier separation.
4. Fold rulings in, deterministically first.
5. Test absorption on the reviewed rows.
6. Repair or re-translate under the locks and gates.
7. Audit the result and cut the next review pack.

GEPA is deliberately later in the process, after deterministic rules, guide
changes, pool changes, and gold merges have reached saturation. Its required
preconditions are a leakage-free split, a SME-validated metric, frozen rules,
and an explicit promotion gate.

### The installable template

Commit `9283be7` (`translation_process project template: the formalised method,
installable`) added the template under:

```text
snomed-terminology-translation/snomed_translation/templates/translation_process/
```

It contains:

- `manifest.json`
- `plan.json`
- eight phase/problem definitions
- nine process flows
- nine standing conclusions/laws
- two source definitions
- two starter rule files

The manifest declares these placeholders:

```text
{{code}}
{{lang_name}}
{{data_dir}}
{{pool_source}}
{{seed_guide}}
{{model_key}}
{{project}}
{{configs_dir}}
{{rf2_relationship_file}}
```

The template seeds 8 problems, 14 plan tasks, 5 gates, 9 flows, 2 sources, 9
conclusions, and 2 verbatim files.

The provisioning machinery in `snomed_translation/provision.py` was extended
so templates can:

- merge conclusions without clobbering conclusions already present in a
  project;
- ship verbatim files such as language rule YAML, with `__code__` replaced by
  the target project code;
- use `{{configs_dir}}` and `{{rf2_relationship_file}}` in flow definitions;
- clone and parameterise the process flows for a new language.

The nine flows are:

```text
cascade
qa_gate
rule_repair
package_review
ingest_review
tier_separation
merge_gold
absorption_test
curate_pool
```

The plan is dependency ordered:

1. Source RF2, the exemplar pool, SME commitment, and the domain slice.
2. Curate the versioned exemplar pool.
3. Index exemplars, reusing vectors across pool versions where possible.
4. Seed the style guide.
5. Run the baseline cascade.
6. Run detector sweep and QA.
7. Package the blinded round-1 review pack.
8. Conduct SME review and collect adjudication questions.
9. Ingest the review and measure tier separation.
10. Fold in rulings: rules, guide, pool, then gold merge.
11. Run the absorption test.
12. Repair/re-translate, audit, and package the next round.
13. Run GEPA optimisation on the remaining residue.
14. Apply delivery gates and promote the deliverable.

The five explicit gates are:

- gating inputs sourced;
- baseline cascade and detector sweep recorded;
- round-1 tier separation measured on a pre-registered blinded sample;
- an optimised prompt beats the current guide on held-out data;
- SME sign-off on the deliverable.

### The nine standing laws

These are seeded as established conclusions in every new project:

1. Numbers come from tracked runs.
2. The SME lock is absolute, and supersession is explicit.
3. Canonical forms come from adjudicated sources, not batch frequency.
4. Repair by minimal substitution; re-translate only for structure.
5. Blind and pre-register experiments.
6. Expect the reviewer to supersede herself.
7. Pair-level detectors catch what row-level checks cannot.
8. Single-run A/Bs at production temperature are not decision evidence.
9. Derived data is never edited in place.

## Greenfield demonstration: `kog`

The demo was created by commit `7ea7668` in the translation repository. Its
configuration lives under:

```text
configs/kog/
style_guide/kog/style_guide_kog_seed.md
```

It is registered in `configs/projects.registry.json` as:

```text
code: kog
name: Korean (greenfield demo)
direction: EN→KO
web port: 8102
MCP port: 8767
```

The corresponding GX10 user services were observed running:

```text
mcp-snomed@kog.service
wizard-app@kog.service
```

Browse it on GX10 at `http://localhost:8102`, or through the GX10 Tailscale
address at `http://100.73.210.77:8102` when network access permits.

The demo contains:

- the eight phase problems, including Foundations, Baseline/QA, SME rounds,
  the editorial rulings ledger, Prompt Optimisation, and Delivery;
- 14 dependency-ordered plan tasks;
- five open gates, with SME sign-off required for the final gate;
- all nine parameterised flows;
- all nine methodological conclusions;
- universal starter hygiene rules and a starter style guide;
- an English-side imaging domain slice of 5,012 concepts.

It intentionally does **not** contain a target-language archive, because this
is a greenfield language case. The exemplar pool and adjudicated gold are also
empty. This is an honest cold-start state, not a failed seed: task 1 is to
source the gating inputs, and the first cascade should refuse until a pool is
available. Language-specific rules are expected to emerge from SME rounds;
only universal hygiene blockers are seeded initially.

The reusable provisioning recipe is:

```text
scaffold_language_project
seed_project_template(template="translation_process")
finalize
provision_project_server
```

The exact placeholder values must be supplied for the new language, especially
the project code, language name, model, data/config directories, pool source,
seed guide, and RF2 relationship file.

## Important research and engineering findings behind the template

The template is not generic process decoration; it encodes lessons measured in
the Korean project.

### Evaluation discipline

An early GEPA comparison was found to be invalid because approximately 88% of
the held-out gold terms were present in the retrieved exemplar pool. After
self-concept exclusion and a clean re-evaluation, the hand guide scored 36.3%
exact / 70.1 chrF and the GEPA guide scored 21.8% / 63.9 on the clean split.
The clean dev improvement from a one-line seed (28% to 42% exact) remained a
useful result, but it was not evidence that the GEPA guide beat the hand guide.

This is why leakage-free evaluation, pre-registration, and the distinction
between a screen and a verdict are explicit template laws.

### Cascade and production run

The successful blind cascade used Gemma for the unanimous/confident half and
escalated any disagreement (`min_distinct: 2`) to Qwen. On the 200-row
diagnostic, 99/200 rows were escalated and the cascade reached 41.0% exact,
versus 36.0% for Gemma alone and 37.5% for Qwen alone. Repeated runs averaged
40.25% with a 0.65-point run-to-run standard deviation, but the conversation
explicitly corrected the mistaken inference that this represented concept-level
statistical significance.

The production v6.1 re-run covered all 5,012 concepts and made 25,060 local
sampling calls with zero errors. It completed in about 45 minutes, with a
44.95% escalation rate. The fresh output had 15 detector findings, compared
with 815 warnings plus 35 blockers in the v6.0 first pass; 2,784 rows changed
relative to the previously reviewed text.

During that work, a production hang was traced to an infinite HTTP read timeout
in `translate_one`: a wedged request could block one worker forever, and 16
such workers made a run silently stop. A finite timeout was added and verified
with an 8,000-call reproduction at about 31 requests/second with zero errors.
Embedding reuse was also implemented and verified so a new pool version can
harvest vectors for unchanged English terms instead of rebuilding everything.

### Round-4 review deliverables

The final Korean round-4 pack is canonical in:

```text
data/languages/ko/sme_review/2026-08-21/production_imaging_review_pack_round4.xlsx
data/languages/ko/sme_review/2026-08-21/superseded_rows_for_confirmation.csv
data/languages/ko/sme_review/2026-08-21/superseded_rows_for_confirmation.xlsx
data/languages/ko/sme_review/2026-08-21/covering_email_draft_round4.md
```

The pack contains 4,727 `machine_v6_1` rows plus a 285-row adjudicated overlay,
and a fresh blinded 120-row sample with 40 rows per tier and no overlap with
the prior reviewed set. All 285 adjudicated rows match the merged gold
byte-for-byte. A final audit applied 71 high-confidence fixes: collision
groups fell from 39 to 11, and the remaining groups were deliberately left as
reviewer questions rather than silently rewritten. The final pack was tracked
by run `cfae2e7a339c`; the audit fixes were committed as `98ad961`.

The confirmation workbook is designed for one-click SME decisions:
`APPLY MY NEW RULE` or `KEEP AS WRITTEN`, with a notes column. The email draft
must be reviewed for voice and have its `[Name]` placeholders filled before
sending. Do not use the earlier `2026-08-19` pack or files under `wizard-data`
as the canonical attachments.

## Product/UI decisions

The conversation considered what should become a first-class UI. The strongest
repeated needs were:

1. **Adjudication ledger:** track open → asked → ruled → encoded, including the
   exact rule/guide section and the ruling it superseded.
2. **Round dashboard:** show packaged, sent, returned, ingested, measured,
   folded-in, regenerated, audited, and blocked states with run IDs and trend
   metrics.
3. **Pack audit/diff view:** show changed rows, collisions, detector flags,
   gold overlay identity, sample blinding, and label checks.

The recommended implementation order was ledger, then round dashboard, then
audit view. A separate resource dashboard is unnecessary; escalation rate,
SME hours, and rule findings belong on the round dashboard. A full SME web
review UI was intentionally deferred because the spreadsheet workflow had
already been validated (120/120 returned with corrections and categories). A
small internal ingest drop-zone would be more valuable first.

## Resource model

The guide’s measured planning model is:

- SME time is the binding constraint: roughly 2–4 hours per round, 3–5 rounds,
  or 10–20 SME hours for a 5,000-concept domain; add roughly 50% for a
  greenfield language.
- A full 5,012-concept pass measured 16.87M input tokens. At an assumed
  $1–3/M input tokens, that is approximately $17–51 per pass; two or three
  passes are typical, while deterministic repair is local/free. GEPA is a
  separate order-of-hundreds-of-dollars budget.
- One GPU workstation is sufficient for the cascade → repair → audit → package
  chain, which completed in under an hour in the measured run.
- Escalation rate is both a cost measure and a language-support health metric;
  it should fall as the exemplar pool, guide, and rules mature.

## Recommended next actions

1. Preserve the current dirty repositories; do not reset or delete branches.
2. Review the four uncommitted files in `snomed-terminology-translation` and
   commit them deliberately when their intended ownership is clear.
3. For a real new language, source the RF2/licence, domain slice, exemplar
   pool, SME commitment, and seed guide before running `cascade`.
4. Treat `kog` as a demonstration until its pool and gold are populated. It
   is safe to tear down later with `teardown_project_server`; that should remove
   the `kog` registry entry and its two services as one operation.
5. Before sending the Korean round-4 pack, fill in the email names and resolve
   the 15 supersession confirmations with the SME.
6. If product work resumes, start with the adjudication ledger so future SME
   reversals and supersession lists are recorded structurally rather than
   reconstructed from notes and email.

## Last substantive Claude handover

Claude’s final normal reply said the template existed and the `kog` demo was
live. It highlighted the eight problems, 14-task plan, nine flows, nine laws,
empty greenfield pool/gold, the template’s provisioning extensions, and the
`snomed-research-kog` MCP server on port 8767. The next transcript entry was
the Claude subscription-access error; no later project work was completed in
that session.
