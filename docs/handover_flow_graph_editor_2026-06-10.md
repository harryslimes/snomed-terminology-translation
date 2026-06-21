# Handover: Block-library wizard + visual node-graph flow editor

**Date:** 2026-06-10
**Scope:** A large refactor of the `wizard/` app and `pipelines/` package, done
in one long session. Three connected pieces of work, all uncommitted:

1. **Block-library refactor** — the wizard stopped building one monolithic
   `PipelineConfig` and became a set of reusable *block* libraries; a *flow*
   composes blocks and an *assembler* materialises the config at run time.
2. **Visual node-graph flow editor** — flows became a DAG of typed nodes
   (datasource / translate / evaluate), edited on a Drawflow canvas.
3. **Column-aware ports** — datasource nodes show their dataset's columns;
   input ports declare required columns; connections are gated by compatibility.

> ⚠️ **`docs/wizard.md` is STALE** — it documents the old 11-step linear wizard
> that this work deleted. Don't trust it. This handover supersedes it.

---

## 1. Mental model (read this first)

```
BLOCKS (reusable, managed in the wizard libraries)
  • Project   configs/project.json     env: language, paths, Qdrant, overlap
                                        defaults, eval/optim/SME recipes
  • Models    configs/models.json       LLM endpoints (vLLM/llama.cpp/remote)
  • Sources   configs/sources/<id>.json data sources (SNOMED subset/CSV/Athena/LOINC)
  • Resources configs/resources_ko.yaml prompt addenda / dictionaries / corpora
  • Eval sets configs/eval_sets/*.json   (legacy block; not used by graph flows)
  • Style guides  style_guide/*.md

FLOW (configs/flows/<name>.json)  = a DAG of nodes that composes blocks
  nodes: [{id, type, pos, params, inputs}]
    datasource → references a registered source (params.source)
    translate  → inputs {terms, exemplars} (both datasources), params {model_key, style_guide_path, output_tag}
    evaluate   → inputs {translations (from a translate node), reference (datasource)}

RUN TIME
  assemble_pipeline_config(flow, project, registries) -> PipelineConfig   (base)
  graph compiler walks the DAG topologically, deep-copies the base per node,
  maps node wiring onto the EXISTING stage runners (translate/evaluate) unchanged.
```

The key design choice: **`PipelineConfig` is still the internal execution
artifact** (all stage runners consume it). The graph is an authoring layer that
*compiles down* to per-node `PipelineConfig` deep-copies. Nothing in
`pipelines/stages/*` was rewritten.

---

## 2. Key files

### pipelines/ (core, all untracked-new in git)
- **`config.py`** — Pydantic models. Added: `ProjectSpec`, `ResourceManifest`,
  `DataSourceSpec.from_file/save`, and `ModelSpec.llm_params`/`api_key_env`.
- **`flow.py`** — `FlowSpec` is now a node graph: `FlowNode` (id/type/pos/params/
  inputs) + `nodes: list[FlowNode]`. Constants: `NODE_INPUTS` (port→allowed
  upstream types), `NODE_OUTPUT`, `ROLE_LABELS`, `PORT_REQUIRES` (roles each
  datasource-input port needs). Validators enforce unique ids, valid/typed
  wiring, and acyclicity. **The old linear `steps`/`sources` fields and
  `FlowStepSpec`/`resolve_refs` were removed.**
- **`assemble.py`** — `Registries.load(...)` + `assemble_pipeline_config(flow,
  project, registries)`. Reads `flow.nodes`: `data_sources` = union of every
  datasource node's source; `translation.candidates` = models referenced by
  translate nodes; `pool.sources=[]`/`eval_set=None` (set per node by the
  compiler). Raises `AssemblyError` on unresolved refs.
- **`graph.py`** (NEW, the keystone) — `topo_order`, `resolve_datasource`,
  `build_translate`, `build_evaluate`, `source_schema` (reads CSV header +
  detects roles via aliases), `_require_roles` (column compatibility),
  `GraphError`. This is where node wiring → `cfg.eval_set` / `cfg.sources.pool`.
- **`run_flow.py`** — `run_flow()` assembles the base, writes
  `assembled_config.json`, then `_run_graph()` executes the DAG. CLI:
  `python -m pipelines.run_flow --flow configs/flows/<name>.json`.
- **`stages/translate.py`, `stages/evaluate.py`, `registry.py`, `context.py`** —
  unchanged by this work. translate outputs `output_csv`; evaluate `scored_csv`.

### wizard/ (FastAPI + HTMX UI, all untracked-new)
- **`app.py`** — registers routers: home, probes, runs, browse, eval_sets,
  flows, style_guides, **project, sources, resources, models**.
- **`routes/flows.py`** — flow library + the graph editor. Contains the
  Drawflow↔FlowSpec converters `nodes_to_drawflow`/`drawflow_to_nodes`, the
  `/flows/{name}/graph` + `/graph/save` routes, `/preview` (assembles + lists
  column problems via `_graph_problems`), `_source_schemas()`.
- **`routes/{project,sources,resources,models}.py`** (NEW) — block-registry
  CRUD, each mirroring `routes/eval_sets.py`'s pattern.
- **`routes/home.py`** (NEW) — the dashboard landing page (replaced the old
  session-driven home).
- **`settings.py`** — added `sources_dir`, `resources_path`, `project_path`.
- **`templates/flows_graph.html`** — the Drawflow editor (palette, node HTML
  with `df-*` binding, column display, port-requirement labels, connection
  validation). **Most of the new front-end logic lives here.**
- **`static/drawflow.min.js` / `.css`** — vendored (v0.0.59, no CDN).
- Deleted: `routes/wizard.py`, `session.py`, all `step_*.html`,
  `flow_step_edit.html`, `source_new_*.html`, `translation_candidate_edit.html`.

### configs/ (untracked)
- `project.json`, `sources/{kr_snomed,pooled_legacy}.json`,
  `flows/ko_baseline.json` (the one example flow, in node form).
- `pipeline_ko.json` kept as the frozen pre-refactor reference (the migration
  equivalence test diffs against it). `pipeline_ko_wizard.json` is stale — ignore.

### scripts/
- **`migrate_pipeline_to_blocks.py`** — splits the old monolith into
  project/sources/flow and asserts the assembled config matches. Already run.

---

## 3. How to run & verify

**Start the server** (note the gotcha below):
```bash
uvicorn wizard.app:app --host 0.0.0.0 --port 8090
# Tailscale: http://gx10-224c:8090  ·  open /flows/ko_baseline/graph
```
> **Gotcha:** starting uvicorn with a trailing `&` in this environment gets
> SIGKILLed (exit 144) when the shell turns over. Use the agent's
> `run_in_background: true` Bash param instead, or run it foreground in a
> dedicated terminal. `--reload` was NOT used (changes need a manual restart).

**Headless UI check** (no Playwright installed; snap chromium works):
```bash
chromium --headless --no-sandbox --disable-gpu --virtual-time-budget=4000 \
  --dump-dom "http://localhost:8090/flows/ko_baseline/graph" | \
  grep -c drawflow-node    # expect 4 nodes; 4 connection wires
```

**Headless logic checks** (no pytest installed — run inline):
```python
# round-trip converters
from pipelines.flow import FlowSpec
from wizard.routes.flows import nodes_to_drawflow, drawflow_to_nodes
f = FlowSpec.from_file('configs/flows/ko_baseline.json')
rt = FlowSpec(name=f.name, project=f.project, nodes=drawflow_to_nodes(nodes_to_drawflow(f.nodes)))
# assert node ids/types/params/inputs equal

# assemble + compile dry-run (no GPU needed)
from pipelines.assemble import Registries, load_project, assemble_pipeline_config
from pipelines.graph import topo_order, resolve_datasource, build_translate, build_evaluate
```

**Equivalence test:** `python scripts/migrate_pipeline_to_blocks.py` (dry-run)
should print "✅ Assembled config matches the monolith".

**A real run** needs vLLM/Qdrant up (not available headless). `python -m
pipelines.run_flow --flow configs/flows/ko_baseline.json --log-dir /tmp/run1`.

---

## 4. Current state — DONE & verified

- ✅ Block libraries (project/sources/resources/models) with CRUD UIs; all pages
  render 200, save round-trips persist correctly.
- ✅ Assembler reads node graph; equivalence with old monolith proven.
- ✅ Graph editor: load existing graph (positions + wires restored), add nodes
  via palette, save (export→`drawflow_to_nodes`→FlowSpec). Converters round-trip
  exactly. Headless browser confirms 4 nodes + 4 wires render.
- ✅ Column-awareness: datasource nodes show real CSV columns + detected roles;
  ports labelled with required columns; incompatible connections rejected in the
  UI, by the graph compiler at run time, and surfaced in `/preview`.
- ✅ Legacy linear-steps machinery fully removed; app boots (59 routes).

The approved plan is at `~/.claude/plans/misty-nibbling-naur.md` (it covers the
block-library + node-graph phases; the column-awareness work was added after).

---

## 5. OPEN ITEMS / next steps

### 5a. Unresolved design question — the `exemplars` port (was mid-discussion)
The user asked whether the translate `exemplars` input should require **concept
id + translation** and "join on concept id". **Do not implement that as asked** —
exemplars are retrieved by **English-similarity RAG**, not a concept-id join:
- `scripts/translation/translate_korean_with_lookup.py:94-148` (`prepare_lookups`)
  embeds the English term (BGE-M3 hybrid) and searches Qdrant for similar EN→KO
  pairs. The exemplar payload is `{direction, text=English, translation=Korean}`
  — **no sctid stored** (`scripts/data_prep/build_qdrant_index_ko.py:66-71`).
- So `exemplars` genuinely needs **(English term, translation)** — which is the
  current `PORT_REQUIRES["translate"]["exemplars"] = ["en","target"]`.
- A concept-id join would hand the model the exact answer = **leakage** (see
  `docs`/memory: the cache-leakage finding, ~35pp inflation).

The *legitimate* use of concept id on exemplars is **leakage-safe exclusion**
(drop the query's own concept from its retrieved examples). That needs sctid
added to the exemplar payload + re-indexing + exclusion logic — a bigger change.
**Decision pending from the user**: keep `[en, target]` (recommended, no change)
vs. add optional sctid for exclusion. The user last asked for a plain-English
explanation of "what exemplars is" (provided); they have not chosen yet.

### 5b. Data issues the column feature surfaced (worth fixing)
- **`pooled_legacy` mapping is stale.** Its source declares columns
  `sctid/en_term/target_term`, but the real file `data/EN-KO/all_bilingual_pairs.csv`
  has **`EN,KO,source`**. Alias detection rescues it (en→EN, target→KO) so it
  works as *exemplars*, but it has **no concept-id column** → can't be *terms* or
  *reference*. Consider fixing `configs/sources/pooled_legacy.json` csv_columns.
- **`kr_snomed` is not built** — `data/EN-KO/snomed_kr.csv` doesn't exist, so its
  columns are assumed from the spec (node shows "not built yet"). Needs ingesting
  before a real `ko_baseline` run. (The SNOMED ingestion stage isn't wired into
  `pipelines/` yet — sources are pre-built by `scripts/data_prep/*`.)

### 5c. Known not-yet-wired
- `optimize` / `sme_packet` node/stage types exist in the schema but have no
  runner (`pipelines/registry.py` only registers translate + evaluate). The graph
  editor palette only offers datasource/translate/evaluate.
- The source-ingestion ("build the CSV from a SNOMED RF2 subset") is not a
  pipeline stage; datasource CSVs are produced out-of-band.

---

## 6. Conventions & gotchas

- **`FlowSpec`/`FlowNode` use `extra="forbid"`** — old flow files with `sources`/
  `steps` keys now fail to load. Only `ko_baseline.json` exists and is clean.
- **Drawflow connection format**: on an input, `connections=[{node: srcId,
  input: "output_1"}]`; on an output, `[{node: tgtId, output: "input_2"}]` (the
  key names the *other* end's port). Ports are numbered; the named-port mapping
  is `PORT_ORDER` in `routes/flows.py` (derived from `NODE_INPUTS`). The editor
  guards validation during initial load with a `loading` flag so restoring wires
  doesn't trip the connectionCreated handler.
- **Column roles vs literal columns**: compatibility is by semantic *role*
  (`sctid`/`en`/`target`) with alias detection (`ROLE_ALIASES` in `graph.py`), so
  differently-named CSVs interoperate; the node *displays* literal columns.
- **Server can't reach localhost over 192.168.x**; use the Tailscale hostname
  `gx10-224c`. uvicorn must bind `--host 0.0.0.0`.

---

## 7. Git state

**Nothing is committed.** The entire `pipelines/` and `wizard/` trees are
untracked, plus `configs/{project.json,sources/,flows/,...}`,
`scripts/migrate_pipeline_to_blocks.py`, and this doc. `configs/models.json` is
modified (the gemma4-26b `llm_params` fold from the migration). Branch:
`feature/qwen122b-translation-pipeline`. When ready, this should likely be its
own commit/PR — confirm scope with the user first.

---

## 8. ADDENDUM (later session, 2026-06-10): output schemas + optimize loop

A follow-up session extended the graph. Summary of what changed:

- **Output schemas (`NODE_PROVIDES` in `flow.py`).** Executable nodes now
  declare the dataset roles their output provides; translate's output CSV
  (`sctid, preferred_term, ko_reference, translation`) is advertised as a
  dataset providing (sctid, en, target) via `graph.translate_output_schema()`.
  Wire compatibility is now uniform — *upstream provides ⊇ port requires* —
  for datasource **and** executable outputs (UI `checkEdge`, compiler
  `_require_roles`, `/preview`). `evaluate.translations` now requires
  `[sctid, target]`.
- **Optimize node is fully wired.** Ports `trainset` (required) + `devset`
  (optional), both requiring `[sctid, en, target]` (GEPA scores against gold).
  `graph.build_optimize` + new runner `pipelines/stages/optimize.py` (wraps
  the dspy_translate/GEPA harness; task LM = translation candidate, reflection
  LM = recipe candidates → legacy `reflection_lm` → task LM; writes the guide
  to `paths.output_dir/style_guide_<tag>.md`). Registered in `registry.py`,
  executed by `run_flow`, offered in the editor palette.
- **Translate gained an optional `style_guide` input port** (accepts an
  optimize node; overrides `params.style_guide_path`). This enables the
  baseline-vs-optimised A/B flow:
  `ds_test → translate(seed) → evaluate` ∥ `ds_train → optimize → translate →
  evaluate` (both evaluates referencing ds_test).
- **Leakage guard:** `/preview` warns when an optimize node's trainset/devset
  source is also an evaluate node's reference source.
- **Drawflow port numbering** is derived from `NODE_INPUTS` order on both
  server and client (`PORT_ORDER` is now passed to the template) — append new
  ports at the END of a node type's dict to keep saved graphs stable.
- `scripts/migrate_pipeline_to_blocks.py` moved to `scripts/archive/` — it
  still builds the deleted linear-`steps` FlowSpec, so it no longer runs; it
  was a one-shot that already served its purpose (§3's equivalence-test
  instruction is therefore obsolete).
- The optimize runner is **untested end-to-end** (needs vLLM + dspy + the
  BGE-M3 lookup cache); compile-path and preview are verified headless.

### 8b. (2026-06-11) Exemplars wire made load-bearing

The translate stage previously read a pre-built `paths.lookup_cache` JSON and
**warned + translated with empty exemplars** if it was missing — so re-wiring
the exemplars datasource on the canvas changed nothing at run time. Fixed:

- New **`pipelines/exemplars.py`** — `ensure_exemplars(cfg, rows)`: the wired
  pool is the source of truth. The Qdrant collection (derived `pool_<lang>_<hash>`
  name) is auto-indexed from the source CSV when missing (count-based resume on
  interrupt; EN->LANG points only), uncovered rows are looked up live
  (refactored `lookup_pairs()` in translate_korean_with_lookup.py), and the
  cache (`lookup_cache.<collection>.json` + `.meta.json` sidecar) is a pure
  accelerator, invalidated when the collection/topn changes. Unservable →
  `ExemplarError` → stage FAILS (no more silent empty-exemplar runs).
- **`configs/project.json` unpinned `qdrant.exemplar_collection`** (was
  `paired_translations_ko`) so the per-pool derived name takes effect.
  Consequence: the first real translate run re-indexes the pool under
  `pool_ko_6c1944` (~475k pairs ≈ 30-60 min BGE-M3, one-time per pool). The
  old `paired_translations_ko` collection is now orphaned (still used by the
  legacy CLI script's prepare_lookups path, which is unchanged).
- Verified with faked Qdrant/BGE: cold index + lookup + cache write, warm
  cache hit (zero live calls), incremental append, stale-meta invalidation,
  empty-pool hard failure. Real Qdrant/BGE-M3 path untested headless.

### 8c. (2026-06-11) Embeddings moved to the datasource lifecycle

Per user direction, exemplar embeddings are owned by the **source**, not the
translate run:

- Collections are now **per-source**: `exemplars_<source_id>_<lang>_<digest>`,
  digest = blake2b(embedder model | CSV content). Rebuilding the CSV ⇒ new
  collection name; after a successful re-index, stale siblings for the same
  source are dropped. Unchanged sources keep embeddings forever.
- **Sources page** has an Embeddings column (indexed/partial/not indexed/no
  CSV/n-a/unreachable) + an **Index** button that launches
  `python -m pipelines.index_exemplars --source <id>` (new CLI) as a tracked
  run job (`wizard/runner.py` grew a `source` mode) — live log, cancel, SSE.
- `ensure_exemplars` (translate run time) now: requires exactly ONE pool
  source; uses the per-source collection; verifies completeness by point
  count; resumes/indexes inline only as a loud fallback. A pinned
  `qdrant.exemplar_collection` is still honoured verbatim but never
  auto-built (error if absent).
- Status checks cache CSV digests by (path, mtime, size) so the sources page
  stays fast. Verified with faked Qdrant: status transitions, sibling
  cleanup, partial-resume, multi-source and pinned-missing failures.

### 8d. (2026-06-11) Style guides are nodes; guide pickers removed

- New **`style_guide` node type** (params: `path` into the style_guide/
  library; no inputs; output `style_guide`). The static counterpart of an
  optimize node's output — translate's `style_guide` port accepts either.
- **translate.style_guide is now REQUIRED** (compile error if unwired and no
  legacy `style_guide_path` param); the guide picker was removed from the
  translate node. **optimize gained an optional `seed_style_guide` port**
  (falls back to the recipe's `optimization.seed_style_guide`); its seed
  picker was removed too. Legacy `style_guide_path` params still compile
  (wire supersedes param) but the UI no longer writes them.
- **Models stay per-node pickers** (a model is a role/resource, not dataflow;
  model-A/B flows legitimately differ per node). The real invariant is
  enforced instead: `/preview` warns on **model mismatch** when a guide
  optimized for model X feeds a translate node running model Y.
- `configs/flows/ko_baseline.json` migrated: `style_guide_v5_1` node wired
  into `translate_full` (now 5 nodes / 5 wires).

### 8e. (2026-06-11) Artifact store + publish_as promotion

Adopted the registry pattern (MLflow/W&B/Kedro-style): every output is kept
in an immutable run store; *naming* an artifact for reuse is an explicit act.

- **Run-scoped outputs**: `RunContext.artifacts_dir()` →
  `data/wizard_runs/<run_id>/artifacts/`; translate + optimize write there
  (fixes the output_tag overwrite bug). Bare CLI runs without --log-dir fall
  back to the legacy shared `paths.output_dir`. Note: `--resume` now means
  re-running with the same --log-dir.
- **`publish_as` param** on translate/optimize nodes (text field on the
  node). On success, run_flow promotes the artifact: translate output →
  immutable copy `data/published/<name>/<run_id>.csv` + registered source
  `configs/sources/<name>.json` (csv kind, translate-output columns, full
  `provenance`: flow/node/run_id/params/inputs/model/style guide); optimize
  output → `style_guide/<name>.md` + `.provenance.json` sidecar. Re-publish
  repoints the registry entry, older copies kept ("latest" semantics).
- **Hand-authored entries are protected**: publish refuses to overwrite any
  source spec/guide that lacks provenance; `/preview` warns about such
  collisions before the run (`_publish_warnings`). Invalid publish names fail
  at compile (`_check_publish_name` in graph.py).
- `pipelines/publish.py` is the module; `DataSourceSpec` gained an optional
  `provenance` field; sources list shows "published by flow/node · run · date".
- Consumption needs no new node type: a published dataset is an ordinary
  datasource (roles detect as sctid/en/target; embeddings/index per usual).

### 8f. (2026-06-11) Retroactive publishing + run-linked provenance

- **Run page "Artifacts" section**: every successful translate/optimize
  output in the run journal gets a name field + Publish button →
  `POST /runs/{id}/publish` calls the same publish_dataset/publish_style_guide
  with `retroactive: true` in provenance. Forgetting `publish_as` costs
  nothing — promote later from the run page.
- **Provenance now links back to the run**: `run_dir` field +
  `retroactive` flag; sources and style-guides pages render
  "published by flow/node · run <id> (link) · date" (full provenance JSON in
  the hover title). The run dir holds the complete reproduction context:
  `assembled_config.json`, **`flow.json` (new: run_flow snapshots the flow
  as-run)**, `journal.json`, log, artifacts.
- **Run pages survive server restarts**: `JobRunner.get_or_load` falls back
  to a read-only `DiskJob` built from `state.json` (which now also persists
  `flow`/`source`), so provenance run-links never dangle. SSE/log/cancel
  degrade gracefully for disk jobs.
- Retroactive provenance takes node params/inputs from the run's flow
  snapshot (authoritative even if the flow file changed since); pre-snapshot
  runs synthesize a bare node and rely on the run_dir pointer.

### 8g. (2026-06-11) Project = goal + run ledger; flow versioning

Reframed the project (user-driven): identity (language) + environment
(Qdrant/paths) + experiment defaults (model/scorers/recipes), with the run
ledger as the project's real content (MLflow-experiment style).

- **`/runs` ledger** (new nav item): all runs from `state.json` scan —
  date, flow, **flow version**, state, and artifacts *published from* the run
  (matched via registry provenance, so retroactive publishes count).
- **Flow version history**: every wizard save content-hashes the flow; new
  content appends `configs/flows/.history/<name>/<ts>_<hash>.json` (dedup by
  hash). Runs stamp `flow_version` into state.json — runs sharing a hash ran
  the identical flow.
- **Re-run this version**: run-page button executes the run's `flow.json`
  snapshot (the flow as it was; blocks resolve against *current* registries —
  re-run semantics, not bit-perfect reproduction; `assembled_config.json`
  records what the blocks were).
- **Project page** regrouped into Identity / Environment / Experiment
  defaults (+ runs link); `Pool output` row dropped, `output_dir` labelled
  legacy fallback. Optimization row now shows GEPA budget/seed/reflection.
- **Hidden defaults surfaced on the canvas**: evaluate nodes display the
  scorer weights, optimize nodes the GEPA budget + reflection LM
  (`_recipe_info` → `RECIPES` in the editor). Display-only for now; making
  them per-node params is a possible next step.
### 8h. (2026-06-11) First real run failed → robustness fixes; flow runnable

Run 129697803018 (ko_baseline) crashed: `kr_snomed`'s CSV was never built —
the RF2 release in its spec is NOT on disk and **no ingester exists for the
snomed_national_extension kind** (handover §5b still open). The crash escaped
run_flow (no journal.json), leaving only a traceback at the log bottom. Fixed:

- `resolve_datasource` now raises GraphError for unbuilt sources → clean
  failure at the datasource node AND a `/preview` problem before running.
- `_run_graph` wraps stage runners in try/except: crashes become journal
  entries (`crashed: …`), journal.json always written.
- Run page shows a **failure banner** (first failed journal entry; falls back
  to the log's last error line for journal-less crashes).
- Preview suppresses cascade errors — only the root cause is listed.
- Registered `kr_{train,dev,test}_split` sources (dspy splits: sctid /
  preferred_term / ko_reference) and pointed **ko_baseline's terms node at
  kr_test_split** so the flow can actually run. The train/dev splits are
  ready for optimize-node trainset/devset wiring. `kr_snomed` spec kept for
  the day an RF2 ingester exists.

### 8j. (2026-06-11) CSV source column mapping inverted

The csv-source form's mapping is now **column → role**: an htmx fragment
(`GET /sources/csv-mapping`, template `_csv_mapping.html`) lists every column
in the chosen CSV with a role dropdown (concept id / English term /
translation / not used), pre-selected from the saved mapping then
`ROLE_ALIASES`. Re-fetches on csv_path change (the shared file picker now
dispatches a `change` event after programmatic value-sets). Falls back to
the old free-text role inputs when the CSV isn't readable yet. The save
parser accepts the new (map_col, map_role) pairs — first column per role
wins — with the legacy `col_*` fields still honoured.

### 8i. (2026-06-11) First successful run (831e96d5ac58) → polish

ko_baseline ran end-to-end: 124 translations, exact 57.3% / chrF 83.6 /
composite 0.760; output auto-published as `translate_run_1`. Follow-ups:

- **Live log streaming fixed**: run page now uses a native `EventSource`
  tail (htmx-sse swap dropped) — clears on (re)connect so the full-replay
  stream never duplicates, follows the bottom, closes on the final
  `[run <state>, exit=N]` marker.
- **Artifacts table lists every executable node's outputs** (incl.
  evaluate's `*_eval.csv` per-row scores: sctid/candidate/best_ref/exact/
  chrf) — publish form only on the promotable ones.
- **Artifact viewer**: artifact paths on the run page link to
  `/runs/{id}/artifact?path=…` — CSVs render as a table (first 500 rows),
  text/markdown as-is, with a download endpoint. Both routes whitelist
  against the run's own journal artifacts (no arbitrary file serving).
- **Log blink fixed**: the SSE stream's old inline `[run …]` marker arrived
  with a leading newline so the client's close-regex never matched → the
  EventSource reconnect-looped every ~3s, re-clearing/replaying the log
  (the blink). Streams now end with a dedicated `done` SSE event; the
  client appends it and closes.
- **LiteLLM "botocore" warnings explained + removed from evaluate**: they
  were harmless (LiteLLM preloading AWS Bedrock/SageMaker shapes; we don't
  use Bedrock), but came from evaluate importing dspy_translate just for
  `_norm`/`_best_ref_by_chrf`. Those moved to **`pipelines/scoring.py`**
  (dspy_translate re-imports them — same objects, bit-identical scoring);
  evaluate no longer loads dspy/LiteLLM at all. The optimize stage (which
  legitimately imports dspy) sets the LiteLLM logger to ERROR.

- **Config fingerprint** (user-spotted gap: a model-temperature edit between
  runs wouldn't change flow_version): run_flow writes `run_meta.json` with
  `config_version` = blake2b(assembled base config + content digests of every
  referenced style guide). The ledger shows Flow + Config columns: same
  Flow/different Config ⇒ same graph, changed conditions. Verified sensitive
  to llm_params edits and guide-content edits, stable otherwise. (Known
  remaining hole: source CSV content isn't folded in — the embedding
  collections' content-hashed names partially cover that.)
