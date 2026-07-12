# Design: Multi-language projects + a saner data layout

**Status:** Draft / proposed (2026-07-08).
**Audience:** the agent (and project owner) adding a second target language
(Estonian) alongside Korean, and cleaning up `data/`.

> This is a proposal. §7 lists the decisions that need sign-off. The Estonian
> **config scaffold** (§4) is risk-free and can land immediately — nothing points
> at it yet. The **data restructure** (§5) touches a live pipeline and is phased
> behind compat symlinks; confirm §7 before Phase 2.

## 1. Motivation

We want to run a **second translation project** — English→Estonian — next to the
existing English→Korean one, and be able to switch between them. Two things stand
in the way, plus one thing that is nicer than expected:

- **Nice surprise:** the plugin code is already language-agnostic. `config.py`
  states outright *"No language string is hard-coded in the schema"*; language
  lives in a `cfg.language` block (`code`/`name`/`direction`/`tokenizer_lang`),
  exemplar Qdrant collections are keyed by `language_code`
  (`exemplars.py:collection_prefix`), GEPA scaffolding takes
  `language_name`/`language_script_name`, and translate prompts interpolate
  `{language_name}`/`{language_native}`. The `language` block even names `'et'`
  and `'es'` as examples. **The engine does not need to change to add Estonian.**

- **Problem 1 — "project" is not a first-class switchable thing.** The app
  (`semi-automated-research`) binds to *one* project per process: the whole set of
  `WIZARD_*` directories is read into a module-global `SETTINGS` at import
  (`wizard/settings.py`). A "project" is materially that env bundle + its data
  home + its root Problem tree + its `wizard_runs` ledger. There is no in-app
  project selector.

- **Problem 2 — everything Korean is baked into filenames, not config.** The
  content that *is* language-specific encodes the language into the **file name**
  (`resources_ko.yaml`, `configs/hints/ko.yaml`, `style_guide_ko_*`,
  `configs/pipeline_ko*.json`) and into **hand-written data paths**
  (`data/korean`, `data/EN-KO`, `output_dir: data/evals/korean`). `project.json`
  already has `paths.data_dir`/`output_dir` as the intended base, but dozens of
  configs and scripts **bypass it** with literal `data/evals/korean` strings.

- **Problem 3 — `data/` is a flat dumping ground.** ~20 GB mixing five unrelated
  lifecycles: downloaded reference terminologies, per-language source corpora,
  per-language derived/eval artifacts, machine-local caches/services, and app
  run-output state that shouldn't be in the repo `data/` at all.

## 2. Goals / non-goals

**Goals**
- Add an **Estonian project** using the Korean project as the template, driven by
  config rather than new code.
- Establish a **per-language config bundle** convention so language N+1 is a
  directory copy, not a rename-hunt.
- Switch between projects via **one app process per project** (Option A) — cheap,
  fully isolated state, matches today's design.
- A **data layout** organised by lifecycle and language, with per-language
  subtrees that are *isomorphic* (identical shape for `ko` and `et`).
- Do all of the above **without disturbing the live Korean pipeline** (8099).

**Non-goals (this round)**
- A first-class in-app project switcher / dropdown (Option B). Deferred — see §6.
- Rewriting the engine (it's already language-agnostic).
- A big-bang `data/` move. The restructure is phased behind symlinks; the literal
  dereferencing (Phase 2) is opt-in per pipeline.

## 3. Switching model — Option A (workspace per process)

A **project = one `WIZARD_*` env bundle + its own data home + its own port.**
Korean stays on 8099 with `wizard-data/`; Estonian runs on 8100 with a separate
`wizard-data-et/`. Same code, same models, fully isolated research state
(problems, investigations, runs, promoted objects). A tiny "Projects" landing
page (or two bookmarks) links to each instance.

Estonian launch block (mirrors the Korean one in the app `CLAUDE.md`):

```bash
cd semi-automated-research
SV=.venv
TR=../snomed-terminology-translation
WIZARD_FLOWS_DIR="$TR/configs/et/flows" \
WIZARD_SOURCES_DIR="$TR/configs/et/sources" \
WIZARD_MODELS_JSON="$TR/configs/models.json" \
WIZARD_EVAL_SETS_DIR="$TR/configs/et/eval_sets" \
WIZARD_INVESTIGATIONS_DIR="$TR/configs/et/investigations" \
WIZARD_ENVIRONMENTS_DIR="$TR/configs/et/environments" \
WIZARD_PROJECT_PATH="$TR/configs/et/project.json" \
WIZARD_RESOURCES_PATH="$TR/configs/et/resources.yaml" \
WIZARD_STYLE_GUIDES_DIR="$TR/style_guide/et" \
WIZARD_PROBLEMS_DIR="$TR/configs/et/problems" \
WIZARD_PROMPTS_DIR="$TR/configs/et/prompts" \
WIZARD_DATA_DIR="$PWD/../wizard-data-et" \
  $SV/bin/python -m uvicorn wizard.app:app --host 0.0.0.0 --port 8100 --reload
```

`configs/models.json` is **shared** (it describes serving infra — vLLM ports,
quantisation — not language). Everything else is per-language.

## 4. Per-language config bundle

Keep Korean's flat `configs/` untouched (zero risk to 8099); introduce a
per-language bundle for new languages:

```
snomed-terminology-translation/
  configs/
    models.json                 # SHARED — serving infra
    et/
      project.json              # language.code=et, direction EN->ET, EE refset 71000181105
      resources.yaml            # Estonian resource registry (sonaveeb, eesti_arst, national ext)
      hints.yaml
      sources/                  # EE RF2 source + EE-EN bilingual pool source
      eval_sets/  investigations/  environments/  problems/  prompts/  flows/
  style_guide/
    et/                         # Estonian style guides + lineage
```

`project.json` for Estonian is a copy of the Korean one with:

| field                         | Estonian value                                                        |
| ----------------------------- | --------------------------------------------------------------------- |
| `language.code`               | `et`                                                                  |
| `language.name`               | `Estonian`                                                            |
| `language.direction`          | `EN->ET`                                                              |
| `language.tokenizer_lang`     | `en` (unchanged — YAKE runs on the English source)                    |
| `data_sources[].rf2_root`     | `data/languages/et/snomed/<EE edition>` (see §5)                      |
| `data_sources[].description_file` | `…/Snapshot/Terminology/xsct2_Description_Snapshot-et_EE1000181_20250530.txt` |
| `data_sources[].language_refset_id` | `71000181105` (verified from the EE Language refset)            |
| `paths.data_dir`              | `data/languages/et`                                                  |
| `paths.output_dir`            | `data/languages/et/evals`                                            |
| `pool_output_csv`             | `data/languages/et/pool/all_bilingual_pairs.csv`                     |
| `optimization.seed_style_guide` | `style_guide/et/style_guide_et_seed.md`                            |

Everything else (Qdrant, scorers, GEPA reflection LM) carries over unchanged;
collection names derive from `language.code` automatically.

**What Estonian already has** (staged in `data/`): the EE RF2 edition
(`xSnomedCT_ManagedServiceEE_PREPRODUCTION_EE1000181_…`, refset `71000181105`),
the national extension, the EE-EN bilingual pool (`data/EE-EN/all_bilingual_pairs.csv`),
lexical resources (`sonaveeb.csv`, `eesti_arst`, `haiglateliit`, `kliinikum`,
`ravimregister`), and some prior experiments (`data/evals/ee_extension_*`).

**What's missing** (needs a real pipeline run — do NOT hand-fake):
1. A **stratified eval split** (`dspy_splits/{train,dev,test}.csv`) — generated by
   the data-prep sampler, not written by hand.
2. **Exemplar indexing** of the EE-EN pool into Qdrant (creates the
   `exemplars_*_et_*` collections).
3. A **seed style guide** — a minimal "clinical Estonian register" starter; a
   GEPA/SME-induced guide comes later, the way Korean's did.

## 5. Data directory restructure

### 5.1 The five lifecycles currently tangled in `data/`

| Lifecycle                         | Examples today                                                     | Where it should live                 |
| --------------------------------- | ----------------------------------------------------------------- | ------------------------------------ |
| Language-neutral **reference**    | `snomed_graph`, `loinc`, `athena`, `cache/fsn_to_sctid.json`       | `data/reference/`                    |
| Per-language **source** (immutable) | `korean/` RF2, `xSnomedCT…EE`, `SNOMED_EE_national_extension`, lexicons | `data/languages/<code>/…`      |
| Per-language **derived** (regenerable) | `EN-KO`/`EE-EN`, `evals/*`, `cleaned/*`, `register_oracle`, `analysis`, `sme_review` | `data/languages/<code>/…` |
| Machine-local **services/caches** | `qdrant_storage` (11G), `marker_model_cache` (3.3G)               | `data/services/` (gitignored)        |
| App **run-output state**          | `wizard_runs`, `objects`, `published`, `wizard_sessions`          | **`WIZARD_DATA_DIR`** — not repo `data/` |

The last row is a latent leak: per the app `CLAUDE.md`, run outputs belong in the
`wizard-data/` home, and newer runs already write there
(`wizard-data/wizard_runs/…`), but older ones sit in `data/wizard_runs`. Pulling
these out is independent of the language work and worth doing regardless.

### 5.2 Proposed layout

```
data/
  reference/                 # language-neutral, downloaded/regenerable
    snomed-intl/             # international edition + snomed_graph
    loinc/                   # loinc/ + Loinc_2.82.zip
    athena/
    cache/                   # fsn_to_sctid.json and other neutral lookup caches
  languages/
    <code>/                  # ko, et — ISOMORPHIC subtrees
      snomed/                # national RF2 edition + extension (source; immutable)
      lexicons/              # ko: EDI/KCD7/NIKL   et: sonaveeb   (dictionaries)
      corpora/               # raw domain text; et: eesti_arst, haiglateliit, kliinikum, ravimregister
        <name>/raw/          #   (replaces top-level data/<corpus>)
        <name>/cleaned/      #   (replaces top-level data/cleaned/<corpus>_dedup)
      pool/                  # bilingual pairs: all_bilingual_pairs.csv + cross-maps (was EN-KO / EE-EN)
      evals/                 # dspy_splits, eval sets, sweeps, embeddings (was evals/korean, evals/ee_*)
      derived/               # register_oracle, analysis, marker_outputs, rules
      sme_review/
  services/                  # machine-local, huge, .gitignored
    qdrant/                  # qdrant_storage
    model_cache/             # marker_model_cache
  # run OUTPUT state lives under WIZARD_DATA_DIR ( ../wizard-data[-<code>] ), NOT here
```

Two properties this buys us:
- **Isomorphic languages** — `data/languages/ko` and `data/languages/et` have the
  same shape, so `project.json.paths` can be `data/languages/{code}/…` for every
  language and future languages need **zero literal paths**.
- **Lifecycle-aligned gitignore/backup** — `reference/` and `services/` are
  regenerable and huge (gitignore + document how to rebuild); `languages/*/source`
  is precious immutable input; `languages/*/derived` is reproducible from runs.

### 5.3 Migration — phased, behind symlinks

The move is risky *only* because ~60 config/script literals hard-code
`data/korean`, `data/EN-KO`, `data/evals/korean`. We use the same symlink-compat
trick the app already uses (`semi-automated-research/data -> …`):

- **Phase 0 — Estonian, free (no migration).** Create
  `data/languages/et/…` clean from day one and point Estonian `project.json.paths`
  there. Relocate the already-staged EE assets into it. Korean untouched.
- **Phase 1 — Korean canonical move + compat symlinks.** Move Korean assets into
  `data/languages/ko/…`, `data/reference/…`, `data/services/…`, then leave the old
  names as **symlinks** into the new tree (`data/korean -> languages/ko/snomed`,
  `data/EN-KO -> languages/ko/pool`, `data/evals/korean -> languages/ko/evals`, …).
  Every literal keeps resolving; nothing breaks; the tree is tidy immediately.
- **Phase 2 — dereference literals (opt-in, per pipeline).** Rewrite config/script
  literals to derive from `project.json.paths`, verify each pipeline end-to-end,
  then drop that symlink. This is the real work and is done incrementally, never
  big-bang.

**Enforcement:** add a convention (and ideally a lint) that no config or script
names a `data/<language-specific>` path directly — it comes from
`project.json.paths`, which is `data/languages/{code}/…`. This is what keeps
language N+2 free.

## 6. Deferred: in-app project switcher (Option B)

When a unified UI is wanted: reintroduce `Project` as a first-class entity, make
config resolution **per-request** (thread a resolved workspace object through
routes + runner instead of reading the `SETTINGS` global), and add a project
dropdown. The per-language bundles (§4) and isomorphic data tree (§5) are exactly
what such a switcher would enumerate, so nothing here is wasted. Scoped as a
separate design once the second language is actually running.

## 7. Decisions — signed off 2026-07-08

- **D1 — Korean data: MIGRATE now.** Move Korean into `data/languages/ko/` +
  `data/reference/` behind compat symlinks (Phase 1); literals keep resolving.
- **D2 — `configs/ko/`: YES.** Move Korean's language-specific configs into
  `configs/ko/` (git mv + compat symlinks); `models.json` stays shared at
  `configs/models.json`.
- **D3 — Pull run-state out of `data/`: YES.** Relocate
  `wizard_runs`/`objects`/`published`/`wizard_sessions` out of repo `data/`.
- **D4 — gitignore `services/` + `reference/`: YES.** Treated as regenerable +
  machine-local.

**Live-migration safety (how the above is done without downtime):** `data/` is a
single filesystem, so `mv` is an inode-preserving rename — open file descriptors
(incl. qdrant's mmap) survive it, and a compat symlink at each old path covers any
re-open. The two large service caches (`qdrant_storage`, `marker_model_cache`) are
exposed at their new `services/` path via **symlink, not moved**, so the running
qdrant is never touched. Configs are git-tracked, so their move is git-reversible.
The running server (8099) is **not** restarted; only the next launch uses the new
paths (launcher blocks updated in the app `CLAUDE.md`).

## 8. Implementation plan

1. **Estonian config scaffold** (§4) — `configs/et/{project.json, resources.yaml,
   hints.yaml, sources/}`, `style_guide/et/style_guide_et_seed.md`, empty
   `problems/ investigations/ environments/ prompts/ flows/ eval_sets/`. Risk-free.
2. **Estonian data into `data/languages/et/`** (Phase 0) — relocate the staged EE
   assets; point `project.json.paths` at them.
3. **Generate the Estonian eval split** — run the stratified sampler over the
   EE-EN pool → `dspy_splits/`. (Real run.)
4. **Index EE exemplars** into Qdrant. (Real run.)
5. **Launch the Estonian instance** on 8100 with `wizard-data-et/`; smoke-test a
   translate flow.
6. *(Pending D1–D4)* Korean Phase 1 symlink migration; run-state cleanup;
   reference/services gitignore.

## 9. Open questions

- The Estonian **register oracle** (Sino/native/loan is Korean-specific): does
  Estonian have an analogous register axis worth modelling, or is that a
  Korean-only concern? (Affects `derived/register_oracle` per language.)
- Seed style guide: start from a translated/adapted Korean guide, or induce fresh
  from Estonian SME data when available?
