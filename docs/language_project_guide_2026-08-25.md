# Running a SNOMED CT Language Translation Project

**Status:** guide, 2026-08-25. Written from the EN→Korean imaging project (5,012 concepts,
three SME review rounds completed); every number in §5 comes from that project's tracked runs.
**Audience:** anyone planning or resourcing a translation project on this platform, and the
engineer operating it.

---

## 1. What the system is

The platform is a **translation drafting and quality-assurance pipeline** wrapped in a
**research app** that makes every result reproducible. It does not replace expert review; it
concentrates expert time on the rows that need it, and it converts each expert ruling into
machinery (rules, prompt instructions, reference data) so the same mistake is never reviewed
twice.

A project produces four durable assets:

1. **Translations** — a versioned, content-addressed deliverable for the target domain.
2. **An adjudicated gold set** — every expert-ruled row, with supersession history.
3. **A rule file + style guide** — the language's editorial policy in machine-checkable and
   prompt-injectable form. This is the compounding asset.
4. **A provenance trail** — every number traceable to a tracked run pinned to code and data
   versions.

### How the app models the work

| App object | What it holds in a translation project |
|---|---|
| **Problem** | A framed question ("integrating round-N SME feedback", "output confidence") |
| **Investigation** | One question + the runs that answer it ("does review priority predict rejection?") |
| **Run** | One tracked flow execution — the only legitimate source of numbers |
| **Flow** | A reusable method (translate, repair, package, ingest, merge…) |
| **Data object** | A named, content-addressed artifact (the deliverable, the gold set, the review pack) |
| **Conclusion** | A distilled finding with evidence links and lifecycle status |
| **Gate** | A checkpoint (SME sign-off, metric threshold) |

The discipline that makes this work: **numbers come from runs, never from ad-hoc scripts**;
**derived data is never edited in place** (curation and repair emit new versioned objects);
and **a row a human has ruled on is never overwritten by a machine** (the SME lock), with the
one principled exception that a *newer human ruling supersedes an older one*.

---

## 2. The process, phase by phase

### Phase 0 — Provisioning (once per language)

The new-language wizard (`provision_language_project` / `scaffold_language_project`, or the
drop-directory orchestrator) creates the project: RF2 release detection and ingest, project
config, seed style guide, seed rule file (output-hygiene invariants), and the app server
instance. **Elapsed: hours, not days**, given the inputs below.

**Inputs you must source before starting — these gate everything:**

- A licensed **RF2 snapshot** of the International release (and the national extension if one
  exists).
- A **bilingual exemplar pool**: existing translation pairs (national extension, terminology
  mappings, billing vocabularies). This is the single biggest quality determinant — see §5.4.
- An **SME**: a clinical terminologist in the target language, committed to iterative rounds.
- A **target domain** — a hierarchy slice of manageable size (the Korean project used the
  ~5,000 active imaging procedures). Do not start with the whole terminology.

### Phase 1 — Foundations

1. **Curate the pool** (`curate_exemplar_pool` + a declarative rules file): drop
   non-clinical rows (drug-package strings, physical-object noise), rewrite known export
   artifacts. Never edit the raw pool; curation emits a new versioned CSV, and each version
   gets its own retrieval index automatically.
2. **Build the retrieval index** — automatic on first use; embeddings are reused across pool
   versions, so only new text is ever embedded.
3. **Seed the style guide** — start minimal (formatting, script, spacing conventions). Do not
   guess editorial policy; the SME rounds will write it for you.

### Phase 2 — Baseline translation and internal QA

Translation runs as a **confidence-routed cascade**: a local open-weight model samples each
concept several times; concepts where the samples agree keep the local answer; the rest are
re-translated by a frontier API model. This puts ~55% of the corpus on free local compute and
— more importantly — the **disagreement signal is the best single predictor of error** we
have (validated: see §2, Phase 3d).

Every translation run is followed by the **detector family**, all cheap, most with no model
call: hard-rule validation, SNOMED hierarchy consistency (does a child reuse its parent's
rendering?), contrast/modifier fidelity, transliteration echo, and **duplicate-translation**
(two distinct concepts sharing one rendering — a pair-level check that catches wrong-vessel /
wrong-organ errors every single-row check misses). Detector output feeds a `qa_gate` that
produces one prioritised worklist.

### Phase 3 — The SME round loop (the engine of the project)

This loop is the process. Each round:

**(a) Package** (`package_deliverable`): overlay all adjudicated rows (marked *done* or
*back-for-confirmation*), set per-row `review_priority` from the QA worklist, and draw a
**blinded, stratified sample** (e.g. 40 rows per priority tier, deterministic seed). The
sample is the round's experiment: because the reviewer rates it without seeing our risk
labels, her ratings measure whether the priority score actually predicts error. Reviewed rows
are automatically excluded from future samples.

**(b) SME reviews** the sample (mandatory) plus anything else she chooses; answers the
round's **adjudication questions** — a handful of questions chosen because each settles many
rows at once (e.g. "which form of *hip*?", "should contrast route be stated?").

**(c) Ingest** (`ingest_review_pack`): one tracked run parses the returned workbook (robust
to damaged headers — it happens), normalises ratings, tallies the reviewer's own error
categories, and emits the round's canonical dataset.

**(d) Measure** (`priority_tier_separation` + a re-translation absorption test): does
rejection rise across priority tiers? (Korean round 3: 40% / 52.5% / 82.5%, p=0.0001 — the
triage signal works.) Then fold the feedback in and re-translate the *same* reviewed rows to
measure absorption before touching production.

**(e) Fold in, deterministic first.** Rulings become, in order of preference:
   1. **Hard rules** (source-conditional, with flag/pass examples) — machine-checkable forever;
   2. **Style-guide text** (glossary lines, word-order templates) — prompt-injectable;
   3. **Pool curation rules** — stop the reference data teaching superseded forms;
   4. **Gold merge** (`merge_adjudicated_gold`) — the round's rows enter the adjudicated set;
      older rows that violate the newest rulings are *withheld to a confirmation list*, never
      silently kept or silently changed.

**(f) Regenerate or repair.** Two tools, chosen by defect type:
   - **Minimal substitution repair** (`rule_substitute` + gated splice) for term-level
     defects: touches only the offending span, auditable, cannot damage the rest of a row.
   - **Full re-translation** when the fold-in changes things rules can't patch (word order,
     structure). Expect most rows to change; expect the pair-level detectors to find fresh
     collisions in fresh text; budget an audit-fix pass (§2, Phase 3g).
   Every change passes the same gates: SME lock, no-new-blocker, Pareto acceptance (a repair
   may not be accepted on the evidence of the detector it optimises).

**(g) Audit and cut the next pack.** A pre-send audit (detector sweep + human read of the
worst classes) with a final high-confidence fix patch, then package round N+1 with a fresh
sample seed, the confirmation list, and the next adjudication questions.

**Convergence:** the Korean project measured 42.5% → ~61% exact agreement with the reviewer's
wording after one fold-in cycle, with the residual concentrated in word order and reviewer
self-inconsistency. Plan for **3–5 rounds** to reach a stable plateau on a domain; the later
rounds are cheaper for everyone because the sample-driven triage focuses effort.

### Phase 4 — Prompt optimisation (GEPA)

Run automated prompt optimisation **after** deterministic fold-ins saturate, not instead of
them: the optimiser should spend its budget on what rules cannot express (compositional word
order), not on rediscovering the glossary. Requirements before a GEPA run:

- A **leak-free split** of the adjudicated gold (train/dev/test; exemplar retrieval must not
  see eval rows — the platform's eval-safe pool variant enforces this).
- A **metric the SME's judgements validate** (spacing-normalised exact + semantic partial
  credit; calibrated against her acceptable/partial boundary).
- Hard rules **frozen and enforced** in the optimiser so it cannot trade a convention away.
- A **promotion gate**: the optimised prompt ships only if it beats the current guide on the
  held-out set.

### Phase 5 — Delivery

Deliverables are promoted, content-addressed objects; the reviewer pack is rebuildable from
its run id byte-for-byte. Delivery gates worth making explicit in the app: *blinded-sample
error rate below target*, *zero unreviewed blocker findings*, *SME sign-off*.

---

## 3. Roles

| Role | Time profile | Responsibilities |
|---|---|---|
| **SME terminologist** | Bursts per round (§5.1) | Rate blinded samples fully; answer adjudication questions; rule on confirmation lists |
| **Operator/engineer** | ~1–2 days per round + setup week | Run flows, fold rulings into rules/guide, audit packs, maintain provenance |
| **Project lead** | Light, continuous | Choose domains, gate decisions, own the SME relationship |

The single most valuable thing the project lead can do is protect the **adjudication
questions** channel: one well-chosen question ("is imaging-of-hip the joint or the region?")
settles more rows than a hundred row ratings.

---

## 4. Formalising it: the project template

Everything in §2 exists as named flows and function nodes; a new language project should be
seeded with them rather than rebuilt (the app's project-template mechanism, plus
flow-cloning across projects). The template a new project starts from:

- **Problems**: one per phase, pre-created, with the SME-round problem as the recurring child.
- **Plan**: gated tasks mirroring Phases 0–5, each tagged with its problem.
- **Flows** (language-parameterised): `production-cascade`, `qa-gate-deliverable`,
  `rule-repair`, `apply-collision-fixes`, `package-deliverable`, `ingest-sme-round`,
  `tier-separation`, `merge-adjudicated-gold`, `curate-exemplar-pool`, `retranslate-absorption`.
- **Gates**: pool-curated, baseline-measured, per-round tier-separation measured,
  SME sign-off, promotion gate for optimised prompts.
- **The laws** (§6) as standing conclusions, so a new operator inherits them.

---

## 5. Resource model

All anchors below are **measured values from the Korean imaging project** (5,012 concepts,
Korean has a partial national extension). Formulas first, then the anchors.

### 5.1 SME time

```
SME hours per round ≈ (sample_rows × rate) + (extra_rows × rate) + Q&A
  rate:        2–4 rows/min for rating-only rows; 1–2 rows/min when corrections are written
  sample_rows: 100–120 (the blinded sample — the mandatory ask)
  Q&A:         30–60 min (adjudication questions + confirmation list)
```

- **Per round: roughly 2–4 SME hours** for the standard 120-row sample with corrections on
  half the rows, plus Q&A. (Korean round 3: 120/120 rated, 72 corrections written, answers
  to 3 prose questions.)
- **Rounds per domain: 3–5** to plateau (§2, Phase 3). Budget **10–20 SME hours per
  ~5,000-concept domain** for a language with existing reference data; add 1–2 extra rounds
  for greenfield (§5.4).
- SME time is the binding constraint and the schedule driver: calendar time per round is
  dominated by reviewer availability, not compute (compute per round is hours).

### 5.2 API cost (frontier-model escalation)

Only the cascade's escalated share touches a paid API. Measured on the full 5,012-concept
run (run `d7897383b0e7`):

```
escalated concepts:  2,253 of 5,012  (45.0%)
input tokens:        16.87M total  (~7,500 per escalated concept; ~55% served from prompt cache)
output tokens:       33k  (negligible — the output is one term)
```

**Formula:** `API cost per full pass ≈ concepts × escalation_rate × 7.5k tokens × input price`

| Input price | Cost per full 5,012-concept pass |
|---|---|
| $1 / M tokens | ~$17 |
| $3 / M tokens | ~$51 |
| $10 / M tokens | ~$169 |

Cache discounts (55% of input was cached) reduce this further on providers that price cached
input lower. Per-round incremental cost is lower still: repair passes make **no** model
calls, and absorption tests run on ~120 rows (~$0.50–2). Expect **2–3 full passes per
project** (baseline, one or two re-translations after fold-ins): **API spend is tens of
dollars per domain, not thousands** — unless the frontier model is also used for the bulk
pass, which multiplies cost by ~2.2× (1/0.45) and is not the recommended configuration.

**Escalation rate is the lever.** It tracks language support quality: a mature exemplar pool
lowers disagreement, which lowers both API cost and reviewer burden. Treat a falling
escalation rate across rounds as a health metric.

**GEPA (Phase 4) is the exception**: optimisation evaluates many candidate prompts against a
dev set. Budget it separately at 10–50× a single-pass cost depending on iterations
(order $100s at Sonnet-class pricing); it runs rarely.

### 5.3 Compute (local)

Measured on one GPU workstation (the production box):

| Task | Measured | Frequency |
|---|---|---|
| Bulk sampling, 5,012 × 5 samples (local 26B model) | 23 min | per full pass |
| Retrieval-index build, ~500k pairs, fresh | ~10 min | rare (vectors are reused across pool versions; typical rebuild is minutes) |
| Detector family + packaging, full batch | ~6 min | per round, several times |
| 120-row absorption test end-to-end | ~12 min | per round |

A full cascade→repair→audit→package chain is **under 1 hour wall-clock**. One GPU machine
supports a project comfortably; nothing requires a cluster.

### 5.4 The cold-start factor

Quality and cost both hinge on the **bilingual exemplar pool** (Korean: ~500k pairs from the
extension + billing/mapping vocabularies). For a language without one:

- Expect a **higher escalation rate** (more API cost per pass) and a **higher initial error
  rate** (more SME rounds, and more corrections per row — the slower reviewing rate in §5.1).
- The first SME rounds are worth more: every adjudicated row joins both the gold set and the
  retrieval pool.
- Plan +1–2 rounds and roughly +50% SME hours versus the estimates above, and treat any
  existing national data (even billing extracts) as worth ingesting — curation rules can
  filter noise later, and measurably did for Korean.

### 5.5 Worked estimate (what to put in a project plan)

For a **~5,000-concept domain**, language **with** existing reference data:

| Resource | Estimate |
|---|---|
| SME | 10–20 hours across 3–5 review rounds (bursts of 2–4 h) |
| Operator | ~1 week setup + 1–2 days per round |
| API | $50–200 total at Sonnet-class pricing (excl. optional GEPA: +$100s) |
| Local compute | 1 GPU workstation, hours per round |
| Calendar | dominated by SME turnaround; with 2-week round turnarounds, ~2–3 months |

Scale roughly linearly in concept count for compute/API; SME time scales sub-linearly (the
sample size per round stays fixed — triage is the point of the machinery).

---

## 6. The laws (learned the hard way — encode them in every project)

1. **Numbers come from tracked runs.** If a metric was computed ad hoc, it does not exist.
2. **The SME lock is absolute, and supersession is explicit.** A machine never overwrites an
   adjudicated row; a *newer human ruling* supersedes an older one via the gold merge, and
   every superseded row goes to the reviewer as a confirmation list, never silently.
3. **Canonical forms come from adjudicated sources, not batch frequency.** Three rules
   over-fired before this was learned; one "repaired" 13 rows away from the reviewer's own
   approved answer.
4. **Repair by minimal substitution; re-translate only for structure.** Free re-translation
   takes the licence it is given — it once cleared a rule while deleting "emission" from a
   SPECT term.
5. **Blind and pre-register the experiments.** The priority-validation result is credible
   because the sample was stratified and blinded, and the analysis was written down before
   the reviewer saw the file.
6. **Expect the reviewer to supersede herself.** Rulings evolve (plain X-ray reversed
   between rounds; hip went three ways in one file). The process must metabolise this —
   confirmation lists and adjudication questions, not embarrassment.
7. **Pair-level detectors catch what row-level checks cannot.** Duplicate-translation found
   wrong-vessel and wrong-organ errors every other detector passed — in both generations of
   the text.
8. **Single-run A/Bs at production temperature are not decision evidence.** Sampling noise
   flips ~7–8% of rows between identical runs; per-row causal traces (the retained prompts)
   are the usable evidence at small scale.
9. **Derived data is never edited in place.** Pools, gold sets, and deliverables version
   through tracked runs with content digests, so rollback is always one flow away.

---

## Appendix A — Per-round checklist (operator)

1. Ingest returned workbook → tracked run; check header integrity, rating counts.
2. Run tier-separation on the blinded sample; record the result as a conclusion.
3. Extract rulings: rules / glossary / word-order templates / pool curation / supersessions.
4. Absorption test on the reviewed rows (same config, one variable at a time).
5. Gold merge (supersession list out) → re-repair under the new lock.
6. Re-translate if the fold-in was prompt-heavy; else repair only.
7. Detector sweep + pre-send audit; high-confidence fix patch; verify sample exclusions.
8. Package next round (fresh seed); draft email: achievements → sample ask → confirmation
   list → adjudication questions.
9. File notes and conclusions; update the plan; check gates.

## Appendix B — Where the evidence lives

Every claim in §5 is a tracked run in the Korean project: tier validation `9faf1d8ef3f7`;
absorption `274572a407ae`; full v6.1 pass `d7897383b0e7` (usage: 2,253 calls, 16.87M input
tokens); repair `f536ec8c1f1a`; audit fixes `afba43a0697a`; final pack `cfae2e7a339c`.
Conclusions 76–84 in the app distil the round-3 cycle.
