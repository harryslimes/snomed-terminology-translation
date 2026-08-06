# Spanish resource strategy & the pool-density ablation

**Status:** Research note, 2026-07-22 (trimmed 2026-08-06). The build this originally
designed — the agentic new-language orchestrator (drop-dir → runnable project) — **shipped
and is on `main`**: pure core `snomed_translation/orchestrate.py` + `materialize.py`, MCP
tool `provision_language_project` (`semi-automated-research/mcp_server/server.py`), operated
per the **`docs/add-a-language.md`** runbook. This note keeps only the parts the runbook does
*not*: the Spanish **sourcing strategy**, the **Korean-vs-Spanish resource comparison**, and
the still-open **pool-density ablation**. Test case: **Spanish** (`es`).

> **What was descoped from the original design** (recorded so the decisions aren't lost):
> the shipped orchestrator stops at the exemplar `lookup_cache` (stage 6) — the baseline
> `translate_eval` + `gepa_optimize` (stage 8) are run manually per the runbook, not by the
> orchestrator. Checkpointing (`.orchestrator/state.json`, `from_stage`, `auto`) was **not**
> built — idempotency comes from scaffold guards + content-hashed indexing + re-running with
> the same args. Materialization runs as plain function calls, **not** as git-sha'd tracked
> Runs (only the manual stage-8 flows are tracked Runs). The dropped-dir contract is narrower
> than first sketched: `inspect_sources()` recognizes only RF2 / Athena bundle / `pool*.csv`.

## Spanish source strategy (post-Athena research)

Two paths to the EN↔ES pool, both requiring the **same SNOMED affiliate / UMLS license**:

- **Path A — Athena `SNOMED` bundle (fast bootstrap, recommended first).** Athena ships
  Spanish descriptions as `CONCEPT_SYNONYM` rows with `language_concept_id = 4182511` on
  the standard SNOMED concepts (verified against the downloaded v5 bundle's own `CONCEPT.csv`,
  domain_id=Language → "Spanish language"; the static map in `wizard/athena.py` was wrong for
  v5 and has been fixed to resolve ids from each bundle's CONCEPT.csv). **Confirmed present:
  911,480 Spanish SNOMED synonyms** in the downloaded bundle. A single download yields EN↔ES
  pairs directly (English `CONCEPT.concept_name` ↔ Spanish synonym, keyed by SNOMED
  `concept_code`) — this solves **both** sides of the pool with no Intl-RF2 alignment, and
  feeds the existing `athena_vocabulary` source kind. Caveat: the Athena slice may not carry
  preferred/acceptable flags and may be a subset of the full Spanish Edition.
- **Path B — RF2 Spanish Edition `SCTSPA` (authoritative eval gold).** From MLDS / NLM UTS,
  same license. Carries preferred-term flags and the full description set → the rigorous
  choice for the held-out **test** gold (translate-to-preferred, evaluate-against-preferred).
  Feeds `detect_snomed_archive` + `snomed_national_extension` exactly like ET/KO.

**Plan:** start on **Path A** to unblock a first end-to-end pass and prove the orchestrator,
then swap in **Path B** as the eval gold once the RF2 arrives. Add **LOINC Spanish Linguistic
Variants** (`esES`/`esAR`, from LOINC.org — *not* on Athena) via `loinc_linguistic_variant`
for lab/measurement coverage. National extensions (Argentina/Uruguay) only if regional
variants matter. `build_pool()` therefore supports two ingest modes: Athena-synonym join
(Path A) and RF2 sctid alignment (Path B), unified to the `sctid,en,target` pool schema.

## Resource comparison: Korean (prior art) vs Spanish — why we must ablate the pool

Spanish is a **far richer, and therefore more optimistic, resource setting than Korean was.**
This is not a leakage bug (the disjoint split + self-exclusion guard handle that — see below);
it is a difference in how *dense* the exemplar neighbourhood is around each test concept.

**Measured from the Korean project (`data/languages/ko/pool/all_bilingual_pairs.csv`):**

| | Korean | Spanish (this project) |
|---|---|---|
| Total bilingual pool | 514,756 pairs | 911,480 (Athena) / 987,880 preferred (RF2) |
| SNOMED-aligned pairs | ~95,834 (only ~19% of pool) | ~all of it |
| SNOMED concepts covered | ~39k (**~11%** of SNOMED) | ~complete |
| Rest of the pool | 76% **non-SNOMED padding** (EDI drug codes 75%, KCD7, LOINC) | none needed |

**What retrieval actually used (measured from the ko exemplar caches):**
- Despite the pool being 75% EDI drug codes, **semantic (BGE-M3) retrieval pulled 72–77%
  SNOMED exemplars** and only ~13% EDI — the padding is semantically distant and mostly went
  unused. *Total pool size oversells the effective resource; what matters is SNOMED-neighbourhood
  density.*
- But Korean's SNOMED slice was too **sparse** to fill the top-5: only **~24–27% of concepts got
  all 5 exemplars from SNOMED** (61/249; 1599/5908). For the other ~3/4, retrieval fell back to
  looser cross-vocab (KCD7/EDI/LOINC) pairs to complete the neighbourhood.
- Spanish (~10× the SNOMED-aligned pairs, ~complete coverage) will instead fill **nearly every**
  test concept's top-5 with *close* SNOMED neighbours (siblings/parents/near-synonyms). Higher
  exemplar quality per concept → an easier, more optimistic regime than Korean.

**Leakage guard is prior art and works.** The ko `main` exemplar cache shows **0/5908 concepts**
retrieve their own sctid; the `.excluded.json` sibling records the self-matches that were filtered
out. `build_pool()`/`materialize_exemplars()` must port this same self-exclusion (test sctids out
of the pool *and* self-match out of retrieval), spanning **both** Athena and RF2 sources since they
carry the same SCTSPA content.

## Open experiment — the pool-density ablation (not yet run)

**This is still TODO — no ablation is baked into the eval flows on `main`.** Report Spanish
performance as a curve over SNOMED-neighbourhood density (e.g. full pool → subsample to
Korean-like ~11% coverage → small seed → none), not a single full-pool number. The subsampled
points recreate Korean's difficulty regime *on a language with clean gold to score against*, and
the no/low-pool point approximates the true zero-resource case. Same flow, different pool
datasource; it needs to be **baked into the eval flows so it is measured, not assumed** — that
wiring does not exist yet.

## Open decisions

- **Which pool source first**: Path A (Athena, faster to obtain) vs wait for Path B (RF2).
  *Recommendation: Path A now, Path B as eval gold.* Both need the same license.
- **GEPA reward**: the semantic + bounded-LLM-judge metric is now **available on `main`**
  (`snomed_translation/gepa_metric.py` `make_semantic_metric()` — BGE-M3 cosine-to-gold + a
  capped Fable judge — plus `dspy_provider.py`), so it is no longer a separate rebuild. Ship
  the Spanish baseline with exact+chrF, then optionally re-optimise with the semantic metric
  for the ablation. See memory `fable-gepa-judge-result`.
- **Orchestrator home**: lives at `snomed_translation/orchestrate.py` today; promote to a
  `semi_automated_research.provision` entry point later (the wizard doc's deferred cleanup).
