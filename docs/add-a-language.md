# Runbook: add a new language project

Operational guide for provisioning an EN→`<lang>` SNOMED translation project and
getting its flows running. Written for an agent (or human) with MCP access to a
running instance. Companion to the design docs `new-language-project-wizard.md`
and `new-language-orchestrator.md`.

**The fast path is one call** (`provision_language_project`). The manual steps
and every gotcha behind it are documented below so the fast path is debuggable
and a partial/custom setup is still doable.

---

## 0. Prerequisites (check these FIRST — most failures are here)

| Need | Check | Fix if down |
|---|---|---|
| **Qdrant** (vector DB for exemplars) | `qdrant_status` MCP tool | `docker start snomed-qdrant` (needs the docker daemon: `sudo systemctl start docker`). If the container is gone: `docker run -d --name snomed-qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant` |
| **Translation model backend** | `curl -s localhost:<port>/v1/models` for the model's `port` in `configs/models.json` | `docker start <container_name>` (the `container_name` field of the model spec) — it's a vLLM container; wait ~2 min for weights to load |
| **`style_guide` symlink in the app dir** | `ls semi-automated-research/style_guide` | `ln -s ../snomed-terminology-translation/style_guide semi-automated-research/style_guide` (only `data` is symlinked by default; flows referencing style guides fail without this) |
| **Reflection model** (GEPA only) | remote (e.g. DashScope) needs its API key env set; **or use the local translation model as judge** (see §6) | — |

## 1. What to drop

Point the orchestrator at a directory (or pass paths explicitly). It classifies:

- **RF2 Snapshot** — an unzipped SNOMED edition containing
  `Snapshot/Terminology/sct2_Description_*Snapshot*.txt` +
  `Snapshot/Refset/Language/der2_cRefset_Language*Snapshot*.txt`. Source of the
  **eval gold** (the Preferred term per concept). National extensions
  (`…-et_EE…`) and International editions (`…SpanishExtensionSnapshot-es_INT…`)
  are both recognized.
- **Athena OHDSI bundle** — a dir with `CONCEPT.csv` + `CONCEPT_SYNONYM.csv`
  (tab-separated). Source of the **bilingual pool** (English `concept_name` ↔
  target-language synonyms). The target `language_concept_id` is resolved from
  the bundle's own `CONCEPT.csv` (`domain_id=Language`) — **never hardcode it**
  (the ids are release-specific; the static map in `wizard/athena.py` was wrong
  for the v5 vocab).
- **`pool*.csv`** — an optional pre-built pool (`sctid,en,target[,source]`),
  used instead of building one from Athena.

## 2. The fast path — one call

```
provision_language_project(
    drop_dir="/path/to/dropped/resources",   # or rf2_archive=… athena_bundle=…
    code="es", name="Spanish")               # language_name inferred for common codes
```

This runs, in order: **inspect → detect RF2 → scaffold → build/ingest pool →
register pool → seed flows → build disjoint train/dev/test splits → index
exemplars → build lookup cache → finalize (switcher + port)**. It returns a
**receipt** with `stages[]`, `gaps[]`, and `next`. Anything needing infra that's
down lands in `gaps[]` (not a crash) — bring the infra up and **re-run with the
same args** (it's idempotent: scaffold guards, indexing is content-hashed).

Then:

```
provision_project_server(code="es")   # brings the project live on its own port + MCP server
```

(You must reload/reconnect once for the new `mcp__snomed-research-es__*` tools to appear.)

The pure core is also a CLI (no MCP): `python -m snomed_translation.orchestrate
--code es --name Spanish --drop-dir … [--no-index --no-lookup-cache]`.

## 3. Running a flow (the incantation that bites everyone)

Flows are run with `run_flow` (MCP, on the project's own server) or the CLI
`python -m pipelines.run_flow`. **Two non-obvious requirements:**

1. **`--investigation project`** — the seeded flows have `project=<code>`, but
   there's no investigation named `<code>`; `project.json` resolves under the
   name `project`. Without this you get `investigation '<code>' not found`.
2. **`WIZARD_MODELS_JSON=configs/models.json`** — the shared model catalog is
   `configs/models.json`, not `configs/<code>/models.json`. Without this env var
   you get `model_key … not in catalog; available: []`.

Full CLI example (run from the plugin repo root, using the app's venv):

```
cd snomed-terminology-translation
WIZARD_MODELS_JSON=configs/models.json \
  ../semi-automated-research/.venv/bin/python -m pipelines.run_flow \
    --flow configs/es/flows/es_translate_eval.json \
    --investigation project \
    --log-dir data/languages/es/evals/runs/baseline_1
```

Every run writes `usage.json` (per-model token accounting) next to `journal.json`.

## 4. Data schemas (what the CSVs must contain)

- **Pool** (`<code>_pool` source) — columns mapped via `csv_columns`:
  `sctid`, `en`, `target` (required: `en` + `target`), optional `source`.
- **Splits** (`<code>_{test,dev,train}_split`) — columns
  `sctid`, `preferred_term` (English input), `<code>_reference` (the gold), plus
  `semantic_tag` (for analysis). The template's split-source specs map
  `target → <code>_reference`.
- **Lookup cache** (`data/languages/<code>/evals/lookup_cache.json`) —
  `{sctid: [[en, target], …]}` for every train+dev+test concept. **GEPA requires
  this to pre-exist** (the translate node builds it live; the optimizer does not).

## 5. Common failures → fixes (all seen in practice)

| Error | Cause | Fix |
|---|---|---|
| `could not find a Description snapshot for language 'es'` | national-ext glob didn't match an International edition filename | fixed in `detect_snomed_archive` (globs now allow the `…SpanishExtensionSnapshot…` infix) |
| pool build finds ~0 or wrong-language synonyms | trusted the hardcoded language-id map | resolve `language_concept_id` from the bundle's `CONCEPT.csv` (the orchestrator does) |
| `exemplar lookup cache not found` (GEPA) | no `lookup_cache.json` | build it (orchestrator step; or `materialize.build_lookup_cache`) |
| `multiple exemplar sources selected` (building the cache) | assembled cfg has >1 datasource | pin `cfg.sources.pool.sources = ["<code>_pool"]` (materialize does this) |
| `seed style guide not found: style_guide/…` (via the app) | missing `style_guide` symlink in the app dir | see §0 |
| translate stage fails `exemplars unavailable` | Qdrant down or pool not indexed | see §0; index via `materialize.index_exemplars` |

## 6. GEPA (prompt optimization) notes

- **Reflection ("judge") LM**: configured in `project.json` `optimization.reflection_lm`.
  A remote frontier model (e.g. `qwen3.7-max` via DashScope) works, but so does
  **the local translation model itself** — set `reflection_lm` to gemma's local
  endpoint with `max_tokens: 4000` (it needs room to write prompts). In testing,
  local-gemma-as-judge matched-or-beat the remote model at zero API cost. Do this
  via a variant investigation (e.g. `configs/es/investigations/gemma_judge.json`)
  and run with `--investigation gemma_judge`.
- **Budget/length**: `optimization.gepa.auto` = `light | medium | heavy` (~1190
  rollouts for medium).
- **Seed**: set `GEPA_SEED=<n>` (env) to vary/reproduce the search for a seed sweep.
- **Fresh runs**: point `DSPY_CACHEDIR` at an empty dir to force real calls
  (DSPy disk-caches completions, so a rerun with the same inputs is served from
  cache in seconds and consumes ~0 tokens — correct, but not a fresh run).
- **Then evaluate**: point a translate-eval flow variant's `seed_guide` at the
  evolved guide (`…/artifacts/style_guide_<code>_gepa.md`) and run it on the test
  split to get the held-out score.

## 7. What's reusable code vs. one-off

- `snomed_translation/materialize.py` — `build_pool`, `build_splits`,
  `index_exemplars`, `build_lookup_cache` (language-agnostic; the CSV/index steps).
- `snomed_translation/orchestrate.py` — the driver + CLI.
- `snomed_translation/provision.py` — scaffold / detect / register / template.
- The `translation_project` template (`snomed_translation/templates/…`) — the
  seeded problem tree, plan, and translate/GEPA flows.
