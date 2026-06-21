# SNOMED Translation Pipeline — Wizard

A FastAPI + HTMX wizard that walks through configuring a SNOMED translation
pipeline for a new language, persists the full setup as a JSON/YAML
`PipelineConfig`, and runs stages from that config with progress streaming.

The wizard is the UX over the `pipelines.*` package. Anything the wizard does
can be reproduced from the command line:

```bash
python -m pipelines.run --config configs/pipeline_ko.json --stage translate
python -m pipelines.run --config configs/pipeline_ko.json --stage evaluate
```

## Running the wizard

```bash
uvicorn wizard.app:app --port 8090 --reload
# open http://localhost:8090
```

No auth — assumes you're on localhost. The wizard uses your existing
`~/.claude/` credentials for the Sonnet judge probe and reads
`DASHSCOPE_API_KEY` / `OPENAI_API_KEY` from `.env` (via shell export) for
remote LLMs.

## What the wizard configures

Eleven steps in order:

1. **Language** — code, name, direction string, script regex
2. **Data sources** — a *list* of bilingual-pair producers. Each one is added
   via a subwizard with its own form. Supported kinds:
   - **SNOMED national extension** — RF2 release path + optional filter
     (hierarchy / method axis / body site presets, or raw ECL override).
     The "Radiology procedures" preset auto-fills hierarchy=71388002 (Procedure)
     + method=363679005 (Imaging - action), reproducing the 774-row
     `imaging_eval_set.csv` slice we built for Korean.
   - **Plain CSV** — point at an existing CSV with sctid + EN + target
     columns. The *only* kind needed for languages without a national extension.
   - **Athena vocabulary** — pull from an OHDSI/Athena release directory by
     vocabulary code + target-language concept id (e.g. EDI for Korean health
     insurance codes).
   - **LOINC linguistic variant** — LOINC core + a target-language variant
     file. Lab/imaging codes only.

   Multiple sources are unioned into a **bilingual pool** (the
   <code>pool.output_csv</code>) used as the RAG exemplar corpus. The eval
   set step can either point at a pre-built CSV or **derive from a single
   source by id** (with optional stratified sampling).
3. **Resources** — pointer to a `resources_<lang>.yaml` manifest (the existing
   `configs/resources_ko.yaml` schema, see its header for the kinds + scope
   ECL + overlap policy DSL)
4. **Qdrant** — URL + collection name + BGE-M3 config
5. **Eval set** — CSV path + **column mapper** (abstract `sctid` /
   `source_term` / `reference` / `all_references` → physical column names)
6. **Models** — points at `configs/models.json` (loaded inline at save time)
7. **Translation** — model_key, concurrency, style guide, sampling params
8. **Evaluation** — scorer mix (exact / chrF / cosine / …), multi-reference
   toggle, judge kind (none / Sonnet / local LLM)
9. **Optimization** — GEPA preset, reflection LM, language-hints file
10. **SME packet** — sample size, stratification, reviewer
11. **Review** — read-only config preview + Save / Download / Run buttons

## File picker

Every path field (RF2 roots, CSVs, style guides, output dirs, …) has a
**Browse…** button that opens a server-side file picker (`GET /api/browse`,
rendered into the shared `#file-picker` modal in `base.html`). It walks the
**backend's** filesystem — the machine running `uvicorn` — not the machine the
browser is on. This is deliberate: the wizard is often opened from a laptop
while the data lives on the backend host, so a native `<input type=file>`
(which reads the operator's local disk) would be the wrong machine. Access is
restricted to under the repo root via the same `_safe_path` guard the probe
endpoints use, and the modal header names the host it's browsing.

Three modes (set per field via the `browse_button` macro in `_picker.html`):
`file` (pick an existing file, optionally filtered by extension), `dir` (pick a
folder), and `save` (pick a folder + type a new filename — used for output
paths). The picker opens at, or near, whatever path is already typed in.

## State persistence

Each wizard run gets a UUID (`run_id`); state is persisted as
`data/wizard_sessions/{run_id}.json` after every POST. The home page lists
recent runs so you can resume one. The state shape is a partial
`PipelineConfig` — when you click Save, it's validated and written to disk.

## Job execution

Clicking "Run stage" from the Review page POSTs to `/runs` which launches
`python -m pipelines.run --config X --stage Y` as a **subprocess** (not an
asyncio task). Rationale baked into [docs/wizard.md](docs/wizard.md) and
the plan file:

- BGE-M3 + LLM in the same process OOMs the GPU on this hardware (see the
  `--prepare-lookups` two-phase pattern in
  `scripts/translation/translate_korean_with_lookup.py`)
- `dspy.settings` is global; two concurrent stages in the same process
  step on each other
- `Process.terminate()` is the cleanest cancellation path

Log files land in `data/wizard_runs/{job_id}/log.txt`. Live updates are
streamed to the run page via Server-Sent Events.

## Stages currently wired (Phase 1)

- `translate` — the production translator, config-driven
- `evaluate` — exact match + chrF against `all_references`

Phase 4 will add: `source_ingestion`, `dictionaries`, `qdrant_index`,
`prepare_lookups`, `optimize`, `judge`, `sme_packet`.

## Config schema

See `pipelines/config.py`. Two existing files are subsumed by the new schema
but kept around for backward compat:

- `configs/models.json` — `models{}` + `jobs{}` are inlined into the
  pipeline config when you Save.
- `configs/resources_ko.yaml` — the `resources[]` schema is a 1:1 port to
  `pipelines.config.ResourceSpec`. Phase 4 will load these files inline; for
  now they're referenced by path.

## Language-agnostic by design

Three pieces of language coupling were called out in the plan and have all
been addressed in Phase 1:

1. **Column names** (`ko_reference`, `ko_all`) — surfaced as
   `EvalSetSpec.columns` mapper.
2. **Optimization metric hints** (Korean compounds, native-vs-Sino lists,
   contrast markers, `-graphy/-gram` suffixes) — moved to
   `configs/hints/{lang}.yaml`, loaded by `dspy_translate.make_metric()`.
3. **Prompt templates** ("translate to Korean") — `cfg.language.name` is
   interpolated into the templates at runtime.

Result: a Spanish run is just a new `PipelineConfig` pointing at Spanish
data — no code changes needed.

## Verifying parity with the pre-refactor pipeline

The Phase 1 verification harness compares the wizard's `translate` stage
output against a direct run of `translate_korean_with_lookup.py`:

```bash
# 1. Reproduce yesterday's gemma4-26b + v5_1 + 124-row test eval:
python -m pipelines.run \
    --config configs/pipeline_ko.json \
    --stage translate

python -m pipelines.run \
    --config configs/pipeline_ko.json \
    --stage evaluate
# Expect: exact ~46-50%, chrF ~75-77 (the gemma+v5_1 baseline)
```

Bit-identical CSV output to the original CLI was confirmed during Phase 1.

## Pitfalls

- **The lookup cache (`paths.lookup_cache`) must exist** for translation to
  use real exemplars. The wizard doesn't yet build it; until Phase 4 lands
  `prepare_lookups`, either:
  - Symlink or copy an existing cache: e.g.
    `data/sme_review/2026-04-24/lookup_cache.json` →
    `data/evals/{lang}/lookup_cache.json`
  - Or run the existing CLI: `python scripts/translation/translate_korean_with_lookup.py --prepare-lookups`
- **vLLM must be up at the configured port** before kicking off `translate`.
  The runner doesn't (yet) auto-start the container.
- **Stop sequences and `enable_thinking`** for reasoning models (qwen3.7-max,
  gpt-oss-120b) need to be in `llm_params` — see the
  `chat_template_kwargs.enable_thinking=false` + top-level `enable_thinking=false`
  combo in `configs/pipeline_ko.json`.
