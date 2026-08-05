# Design: New-language-project wizard (UI + MCP)

**Status:** Built 2026-07-08. Validated by re-deriving the Estonian bundle
(matches the hand-built `configs/et`) and via the live UI on 8099/8100.
**Audience:** anyone standing up a new translation workspace, or an agent doing it.

## Goal

Turn the manual steps used to create the Estonian project (see
`multi-language-and-data-layout.md`) into a **repeatable, guided capability** —
available both as a **UI wizard** and as **MCP tools**, so a human clicks through
or an LLM drives it and only asks the user for what it can't infer.

## One shared core, two front-ends

All provisioning logic lives in **`snomed_translation/provision.py`** (pure, no
FastAPI/MCP). Both drivers call it, so they do exactly the same thing:

- **UI wizard** — `wizard/routes/provision.py` + templates (`project_new.html`,
  `_archive_preview.html`, `project_created.html`); "New project" button on
  `/switch`. The archive step htmx-previews the detected refset before you commit.
- **MCP tools** — in `mcp_server/server.py`: `list_language_projects`,
  `detect_snomed_archive`, `scaffold_language_project`, `register_bilingual_pool`,
  `finalize_language_project`.

The registry/port logic is app-generic (`wizard/workspaces.py`:
`add_project`, `next_free_port`). Domain steps (RF2/refset) come from the plugin
via a lazy import, so the generic app degrades gracefully without it.

## Control-plane, not an investigation

Provisioning creates a **sibling workspace** — it writes `configs/<code>/`,
`data/languages/<code>/`, and the shared switcher registry. This is a level above
the existing `create_project` MCP tool (which makes an *investigation inside* one
workspace). The tools derive the shared repo roots from the running instance's
`project.json` path (the `configs` ancestor anchors the repo root), so they can
provision siblings even though each process serves one project.

## The ask-vs-auto split (why MCP fits)

Every step separates **must-ask-the-user** from **auto/derivable** — that split is
the "only bother the user when needed" behaviour:

| Step | Ask the user | Auto / defaulted |
| --- | --- | --- |
| Identity | target language (code, name) | `direction` = `EN->CODE`; `tokenizer_lang=en` |
| SNOMED archive | *where is the archive* | **language refset id** (parsed from the RF2 Language refset — modal active `refsetId`, warns if >1), edition dir, Description file, term count |
| Bilingual pool | which CSV | column mapping (header sniff: en / target / sctid / source) |
| Qdrant | URL only if non-default | collection names (derived from `code`) |
| Registry | — | next free port, registry entry |
| Problem | the research question | created in the running instance afterward |

## Flow of a full provision

`detect_snomed_archive` → `scaffold_language_project` (bundle + data skeleton +
seed guide + `<code>_snomed.json`) → `register_bilingual_pool` →
`finalize_language_project` (registry + port) → launch the instance (command shown
on the result page / in the app `CLAUDE.md`) → index exemplars.

## Deliberately left as follow-on runs

The wizard sets up **config + structure**, not results. Still requires real
pipeline runs per new language: the stratified **eval split**, **exemplar
indexing** into Qdrant, and the project **problem** framing. The result page and
MCP responses say so explicitly rather than implying the project is runnable
end-to-end.

## Tests

`tests/test_provision.py` — 9 tests over a synthetic RF2 fixture (refset
auto-detect incl. double-nesting + multi-refset warning, scaffold repo-relative
paths + existing-guard, pool sniff, invalid-code). No large archive needed.

## Project template (the runnable skeleton)

A new project can be seeded from a **curated canonical template** so it opens
already framed and wired, not empty. Template bundle:
`snomed_translation/templates/translation_project/` (ships as package data).

- **Problem tree** (`problems/*.json`) — root *Translate SNOMED CT into <Lang>* +
  subproblems *exemplar corpus*, *translation-prompt/GEPA*, *leakage-free
  evaluation*. Single parentless root → the planning layer auto-detects it as the
  project problem.
- **Plan** (`plan.json` → `.plan.json`) — 5 gated starter tasks (build split →
  index exemplars → baseline → GEPA → compare) tagged to those problems.
- **Flows** (`flows/*.json`) — **translate + evaluate** and **GEPA optimise**,
  authored against the real node ports (translate: terms/exemplars/style_guide;
  evaluate: translations/reference; optimize: trainset/devset/seed_style_guide).
- **Split sources** (`sources/*.json`) — forward-declared `<code>_{test,train,dev}_split`
  pointing at `data/languages/<code>/evals/dspy_splits/*.csv`, so the flows are
  fully wired and just wait for the eval-split run.

**Instantiation** — `provision.instantiate_template(code, name, configs_root, …)`
does placeholder substitution (`{{code}}`, `{{lang_name}}`, `{{pool_source}}`,
`{{test_split_source}}`, `{{seed_guide}}`, `{{model_key}}`, …) and JSON-validates
every file before writing. Exposed as the MCP tool `seed_project_template` and an
opt-in checkbox on the wizard (default on). Placeholders rebind each flow's
datasource/style-guide nodes to THIS project's ids.

**Validated live:** seeding the Estonian project produced 4 problems + 5 plan
tasks + 2 flows + 3 split sources; on 8100 the problem tree, plan, and both flows
render, open in the graph editor with rebound nodes (`et_pool`, `et_test_split`),
and the config **preview assembles**. `tests/test_provision.py` covers
instantiation (flows load as `FlowSpec` with no dangling wiring, single problem
root, plan references only seeded problems).

## Known follow-ups

- Node reuse across projects is handled separately by **flow-cloning**
  (`duplicate_flow` into the target project) — see
  `memory: node-sharing-across-projects`. A new project can start by cloning a
  chosen source flow.
- Architecturally the wizard lives in the app but imports the plugin for the
  domain steps; a cleaner split would contribute the provisioner via an entry
  point (`semi_automated_research.provision`). Deferred — the lazy import works.
