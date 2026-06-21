# snomed-terminology-translation

Translation, evaluation, and optimization pipelines for **SNOMED CT terminology
translation** (initially English → Korean), plus the SME-review and analysis
tooling around them.

This repository holds the *domain work*. The generic web app and workflow graph
editor used to author and run flows live in a separate project,
[`semi-automated-research`](https://github.com/harryslimes/semi-automated-research).
This package plugs its translate / evaluate / optimize functions into that app
via the `semi_automated_research.functions` entry-point group (see
[Plugin](#plugin) below).

## Layout

| Path           | Purpose                                                           |
| -------------- | ---------------------------------------------------------------- |
| `snomed_translation/`   | Stage runners + config schema for translate/evaluate/optimize etc. |
| `scripts/`     | Standalone runners: translation, evaluation, optimization, analysis, data prep, SME review |
| `configs/`     | Korean/SNOMED project, flow, source, eval-set, hard-rule, and resource configs |
| `style_guide/` | Korean translator style guides and their version lineage          |
| `agent/`       | Legacy DSPy-based translation agent                                |
| `tests/`       | Hard-rule tests                                                    |
| `docs/`        | Ablation reports, findings, runbooks, presentation                |
| `notebooks/`   | Resource-preparation notebook                                      |
| `docker-compose.yml` | VLLM / llama.cpp / Qdrant services backing the pipelines     |

## Data

Runtime data (`data/`), model weights (`models/`), and vector stores
(`chroma/`, Qdrant storage) are **not** committed. Regenerate them with the
scripts under `scripts/data_prep/` and by indexing exemplars into Qdrant; see
the docs for the per-corpus steps.

## Services

```bash
docker compose up -d qdrant vllm   # bring up the vector DB + an LLM endpoint
```

## Plugin

This package depends on `semi-automated-research` and registers its node
functions so they appear in the workflow editor. Install both in the same
environment, then launch the app from `semi-automated-research`.
