---
marp: true
theme: default
paginate: true
header: 'SNOMED CT translation with LLMs'
style: |
  section { font-size: 26px; }
  h1 { color: #1a4d7a; }
  h2 { color: #1a4d7a; }
  code { background: #f0f3f7; }
  table { font-size: 22px; }
  .small { font-size: 20px; color: #555; }
  .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; align-items: start; }
  .columns pre { font-size: 15px; line-height: 1.25; }
  section.compact { font-size: 21px; }
  section.compact table { font-size: 19px; }
  section.compact pre { font-size: 15px; }
---

<!--
SPEAKER: 30-minute talk, mixed audience (technical + non-technical, varying AI familiarity).
Timing is in the companion file: docs/presentation/speaker_runbook.md
Rule of thumb: ~1 min/slide, the GEPA + MCP demo sections are where to spend the buffer.
-->

# Translating SNOMED CT with LLMs

### A systematic, reproducible pipeline for medical terminology translation

**Korean (KHIS) — Procedures first**

<span class="small">Project demo & walkthrough · 2026-06-17</span>

<!--
Open with the one-sentence framing: "SNOMED has ~350,000 medical concepts. Translating
them by hand is years of specialist work. I'll show how we turn an LLM into a reliable
batch translator, and — more importantly — a workbench for systematically improving it."
Set expectation: first the idea, then the app, then how we make it better, then a live demo.
-->

---

## What we'll cover

1. **The core idea** — an LLM as a batch transformer with a template prompt
2. **The task** — SNOMED CT and why translation is hard
3. **The app** — building translations as *flows*; importing data
4. **Using existing translations** as context (the hierarchy trick)
5. **Capturing every variable** for systematic experimentation
6. **The model & speed** — how fast, and what "all of SNOMED" costs
7. **Auto-improving the prompt** with GEPA
8. **Live demo** — driving the app from an AI assistant (MCP)

<!-- Keep this up for 20s. Tell them the demo is at the end so they hold questions. -->

---

# Part 1 — The core idea

## One prompt template, thousands of items

Write the instructions **once**, leave **slots** to fill — then loop over every concept.

<div class="columns">
<div>

**The template** (written once)

```text
SYSTEM
  Follow these rules:
  {style guide}

USER
  Examples:
  {context}
  Translate: {term}
```

</div>
<div>

**Filled in for one term**

```text
SYSTEM
  Follow these rules:
  …Hangul only; write
  초음파검사 as one word…

USER
  Examples:
  MRI of abdomen
    → 복부 자기공명영상
  Translate: MRI of pelvis
```

→ model returns **골반 자기공명영상**

</div>
</div>

<!--
Analogy for non-technical folks: a mail-merge letter — fixed body, swap in the name/address
per recipient. Here we swap in the term and its context. LEFT = the reusable template;
RIGHT = exactly what the model sees for one concept, and what it returns. The {style guide}
slot is where all our domain knowledge lives — and (foreshadow) what GEPA improves later.
-->

---

## The actual template we use

<span class="small">`scripts/translation/translate_korean_with_lookup.py`</span>

**System** (the rules — same for every term):
```
You are a medical terminology translator specialising in English→Korean
translation of SNOMED CT clinical terms... Return ONLY the Korean (한글).

# Korean SNOMED CT translation style guide
{style_guide}
```

**User** (filled in per term):
```
Here are similar Korean SNOMED translations for reference:
{paired_translations}          ◄── retrieved context (more on this soon)

Translate this SNOMED CT procedure term from English to Korean.
English: {english}             ◄── the term to translate
Korean:
```

<!--
Point at the two slots: {english} is the item; {paired_translations} and {style_guide}
are the "extra information". Everything else is constant. This is a real file in the repo.
-->

---

# Part 2 — The task

## SNOMED CT, and why this is hard

- **SNOMED CT** = the international clinical terminology. ~**350,000** active concepts
  (procedures, findings, body structures, substances…).
- Each concept has an English name + a place in a **hierarchy** (parents/children).
- Countries maintain **national extensions** with translations — but coverage is partial.
- **Korea (KHIS):** procedures are the 2026 priority; tens of thousands still untranslated.

Translation isn't word-for-word: spacing rules, Sino-Korean vs native terms,
laterality, fixed compounds, modality idioms… **specialist conventions matter.**

<!--
For the clinical/terminology people: acknowledge this is hard and convention-heavy —
that's exactly why we encode conventions in the style guide and verify rigorously,
rather than trusting the model blindly.
-->

---

<!-- _class: compact -->

# Part 3 — The app

## Translations are built as *flows*

A **flow** is a graph (DAG) of typed building blocks you wire together:

```
 [datasource: terms] ─┐
                       ├─► [translate] ─► [evaluate] ─► [score]
 [datasource: examples]┤        ▲
                       │        │
 [style guide] ────────┴────────┘
```

| Node | What it does |
|---|---|
| `datasource` | Load a set of terms / examples |
| `style_guide` | The rules block (the system prompt) |
| `translate` | Run the LLM over the terms |
| `evaluate` | Score against references |
| `optimize` | **GEPA** — improve the style guide |

<span class="small">Built visually in the wizard; stored as JSON in `configs/flows/`.</span>

<!--
Emphasise: the same building blocks compose into many experiments. A flow is a *recipe* —
human-readable, versioned, reproducible. Show the wizard graph editor live here if time
allows (browser), otherwise the screenshot.
-->

---

## A real flow (the baseline)

<span class="small">`configs/flows/ko_baseline.json` — abbreviated</span>

```json
{ "id": "ko_baseline", "project": "project",
  "nodes": [
    {"id":"terms",     "type":"datasource", "params":{"source":"kr_test_split"}},
    {"id":"exemplars", "type":"datasource", "params":{"source":"pooled_legacy"}},
    {"id":"sg",        "type":"style_guide","params":{"path":"...ko_v5_1.md"}},
    {"id":"translate_full","type":"translate",
       "params":{"model_key":"gemma4-26b"},
       "inputs":{"terms":"terms","exemplars":"exemplars","style_guide":"sg"}},
    {"id":"evaluate_full","type":"evaluate",
       "inputs":{"translations":"translate_full","reference":"terms"}}
  ]}
```

Every arrow in the picture = one `inputs` wire here. Nothing hidden.

<!--
Don't read the JSON. Just say: "the picture and the file are the same thing — the app
generates this for you, and it's the complete, reproducible definition of the experiment."
-->

---

## Importing data — SNOMED in, examples out

Data sources are registered once, then reused by any flow (`configs/sources/`):

- **SNOMED national extension** (`snomed_national_extension`): point at an RF2
  release folder → it extracts concept IDs, English names, and any **existing
  translations** in the language refset.
- **CSV** (`csv`): a test/eval split with column→role mapping (`sctid`, `en`, `target`).
- **Pooled examples**: all enabled sources merged into a retrieval corpus.

```json
{ "id": "kr_snomed", "kind": "snomed_national_extension",
  "rf2_root": "data/korean/SnomedCT_ManagedServiceKR_.../",
  "language_refset_id": "21000267104" }
```

<!--
Key message: the same SNOMED release is BOTH the source of terms to translate AND a
source of already-translated examples we can learn from. That dual use is the next slide.
-->

---

## The hierarchy trick — reuse what's already translated

When we translate a term, we give the model **related terms that are already
translated** in the official extension — retrieved automatically.

```text
   To translate:   "MRI of pelvis"   →   ?

   A sibling — same scan, different body part — is already in the KR release:

       "MRI of abdomen"   →   복부 자기공명영상      (abdomen · MRI)

   The model keeps 자기공명영상 (= MRI) and just swaps the body part:

       "MRI of pelvis"    →   골반 자기공명영상  ✓   (pelvis · MRI)
```

- Retrieval = **BGE-M3** embeddings in a **Qdrant** vector DB (semantic + keyword).
- The model anchors new translations to **established, human-approved** terminology
  — borrowing the rendering of "MRI" from a sibling and changing only the site.
- Reference-free where no translation exists yet; consistent where it does.

<!--
This is the "aha" for terminology experts: we're not inventing translations from scratch,
we're propagating the conventions already agreed in the extension down the hierarchy.
The {paired_translations} slot from slide 5 is filled by exactly this.
-->

---

<!-- _class: compact -->

# Part 4 — Systematic experimentation

## The point: capture *every* variable

Translation quality depends on many knobs. The app makes each one **explicit,
named, and versioned** — so results are comparable and reproducible.

| Variable | Where it lives |
|---|---|
| Model + quantization | `configs/models.json` (`model_key`) |
| Style guide version | `style_guide/*.md` (node input) |
| Example pool / source | `configs/sources/*` |
| Retrieval depth (top-N) | node params |
| Temperature / sampling | node params |
| Evaluation recipe | project (`evaluation.scorers`) |

Change one knob → new flow → new run → directly comparable score. **No spreadsheets, no "what did I run last time?"**

<!--
This is the project's real contribution. The LLM is commodity; the *discipline* around it
is the value. Every run writes an assembled_config.json + journal.json — a full audit trail.
-->

---

## How we measure quality (rigorously)

Three complementary signals — no single number trusted alone:

- **Exact / chrF match** vs the KR reference — strict, fast, automatic.
- **LLM-as-judge** — labels each output
  `ACCEPTABLE / PARTIAL / WRONG` with reasoning.
- **Back-translation & cross-lingual similarity** (BGE-M3) — *reference-free*,
  so it works on the long tail where no human translation exists.

<!--
SPEAKER — IMPORTANT: do NOT quote "78% exact match" as a quality headline. That number
came from runs affected by a cache-leakage bug (~35pp inflation). If asked for a quality
number, say "we're re-validating; honest long-tail acceptable-rate is in the 40s%, and the
framework's job is to push that up measurably." Speed numbers (next part) are unaffected.
-->

---

# Part 5 — The model & speed

## Gemma 4 26B-A4B — small where it counts

- **26B total parameters, but only 4B *active* per token** (Mixture-of-Experts).
  → quality of a big model, speed/cost closer to a 4B model.
- **4-bit quantized** (NVFP4) → ~13 GB → runs on a **single workstation GPU**.
- Served locally via **vLLM** (no data leaves the building — matters for health data).

<span class="small">`gemma-4-26B-A4B-it` · `configs/models.json` → `gemma4-26b` / `gemma4-26b-nvfp4-remote`</span>

<!--
Non-technical translation of "MoE": a panel of specialists where only the relevant few
answer each question, instead of the whole panel. That's why 26B can run fast.
"No data leaves the building" — privacy point lands well with health audiences.
-->

---

## How fast? Measured throughput

<span class="small">Prior measurement — `docs/gemma4_26b_nvfp4_ablation_2026-04-21.md`, 774-concept batch, concurrency 32</span>

| Model | Quant | Throughput | Note |
|---|---|---|---|
| **Gemma 4 26B-A4B** | **NVFP4** | **~32 / sec** | production default |
| Gemma 4 26B-A4B | AWQ-4bit | ~15 / sec | prior default |
| Qwen 122B-A10B | GPTQ-Int4 | ~0.5 / sec | 64× slower, no quality gain |

**~32 concepts per second**, on one workstation GPU, fully local.

<!--
The Qwen line is the punchline: bigger is not better here. A 122B model is 64× slower
for *no* quality improvement on this task. The MoE + good quantization is the win.
Caveat the audience: these are req/s where each request = one concept translation.
-->

---

## What would "all of SNOMED" cost?

At ~**32 concepts/sec** (current local Gemma 4 setup):

| Scope | Concepts | Time |
|---|---|---|
| KR untranslated **procedures** | ~55,000 | **~29 minutes** |
| **All active SNOMED CT** | ~350,000 | **~3 hours** |
| Same, on the AWQ build (~15/s) | ~350,000 | ~6.5 hours |
| Same, on Qwen 122B (~0.5/s) | ~350,000 | ~8 days |

> The entire terminology, translated in an afternoon — then the real work
> (review & refinement) begins, on a complete first draft.

<span class="small">Estimates extrapolate measured throughput; real runs add lookup + I/O overhead.</span>

<!--
This is the slide leadership remembers. "A first-pass translation of all of SNOMED in
about 3 hours" reframes the problem from 'years of manual work' to 'hours of compute +
focused human review'. Be clear it's a *first draft for review*, not a finished product.
-->

---

<!-- _class: compact -->

# Part 6 — Auto-improving the prompt

## GEPA: let the system rewrite its own rules

The style guide is the highest-leverage knob. **GEPA** improves it automatically.
(**G**enetic **E**volutionary **P**rompt **A**daptation, Pareto-based) — a loop:

```text
   start from the current style guide
       ▼
   ①  translate a training sample with it
       ▼
   ②  score every output, collect the failures
       ▼
   ③  reflection LLM reads the failures, proposes guide edits
       ▼
   ④  keep only the best-scoring edits  (Pareto = best trade-offs)
       ↺  the winner becomes the next guide — repeat
```

A model **reads its own mistakes** and rewrites the rules to fix them.

<!--
Plain-language framing: it's like a writer keeping a running style sheet — every time an
editor flags a mistake, the rule gets added so it never recurs. Here the "editor" is the
scorer and a reflection model. "Pareto frontier" = we keep the candidates that are best on
*some* trade-off, not just one winner, so we don't over-fit to a single metric.
-->

---

## GEPA as a flow

The same building blocks — just add an `optimize` node:

```
 [datasource: train] ─┐
 [datasource: dev]   ─┼─► [optimize] ─► improved style guide
 [seed style guide]  ─┘        │
                               ▼
                    feeds the next translate flow
```

- Inputs: a **train** split (to learn from) and a **dev** split (to validate on).
- Output: a new `style_guide_ko_*.md`, ready to drop into a translation flow.
- Budget presets: `light / medium / heavy` (how much compute the reflection gets).

<span class="small">`scripts/optimization/run_gepa.py` · `pipelines/stages/optimize.py`</span>

<!-- Reinforce: optimisation is not a separate tool — it's one more node in the same graph. -->

---

## What GEPA actually produced (a diff)

Real edits from a v5.1 → v5.4 GEPA run, distilled from scoring failures:

```diff
  **Spacing (띄어쓰기).**
- Korean terms are predominantly space-separated by word unit.
+ *  Default: space-separated by word unit.
+ *  CRITICAL EXCEPTIONS (fixed compounds, NO spaces):
+      초음파검사  → NEVER 초음파 검사
+      림프조영상  → NEVER 림프 조영상

+ ## Laterality preference
+ | Context              | Preferred  | Alternative |
+ | Internal organs      | 우측 / 좌측 | 오른쪽 / 왼쪽 |
+ | Surface anatomy      | 오른쪽/왼쪽 | 우측 / 좌측  |
```

The system **discovered** these rules from its own errors — the diff is reviewable
by a human expert before adoption.

<!--
Land the trust point: a domain expert can read the diff (the app renders it word-by-word,
wizard/diffview.py) and approve/reject. AI proposes, human disposes. Every guide version
is tracked in a lineage file so you can see exactly how it evolved.
-->

---

# Part 7 — Live demo

## Driving the app from an AI assistant (MCP)

**MCP** lets an AI assistant (Claude) call the app's functions directly —
`list_flows`, `duplicate_flow`, `set_node_params`, `run_flow`, `get_run`.

**Demo:** "Run the translation flow at temperatures 0, 0.5, and 1.0 and compare."

```
for t in [0.0, 0.5, 1.0]:
    duplicate_flow("ko_baseline", new_name=f"temp {t}")
    set_node_params(new_flow, "translate_full", {"temperature": t})
    run_flow(new_flow)            # → job_id
get_run(job_id) ...               # compare headline scores
```

<span class="small">Temperature = how "creative" vs deterministic the model is. 0 = same answer every time.</span>

<!--
SPEAKER: run this live against the MCP server. Detailed runbook + fallback in
docs/presentation/speaker_runbook.md. If the live demo is risky, the pre-built flows
temp-0-0 / temp-0-5 / temp-1-0 already exist — open their runs in the wizard instead.
Explain temperature simply: 0 = "give me your single best answer, always the same";
higher = "allow variation" — useful when we want to sample alternatives and pick the best.
-->

---

## Why the MCP connector matters

- The app is **not** just a UI — it's a set of operations an agent can orchestrate.
- "Sweep these 5 settings and tell me which wins" becomes **one instruction**,
  not an afternoon of clicking.
- Same audit trail: every agent-launched run is logged, scored, reproducible.

> The human sets the **question**; the assistant runs the **experiment**;
> the app keeps the **evidence**.

<!-- This is the future-of-the-workflow slide. Experimentation at conversation speed. -->

---

## Recap

- LLM + **template prompt** = a batch translator for SNOMED CT.
- **Flows** make each translation experiment a reproducible recipe.
- We reuse **already-translated hierarchy** as context — anchoring to approved terms.
- Every **variable is captured** → systematic, comparable experiments.
- **Gemma 4 26B-A4B**: ~32 concepts/sec → all of SNOMED in ~3 hours, locally.
- **GEPA** rewrites the rules from its own mistakes — human-reviewable diffs.
- **MCP** lets an assistant run the whole workbench by conversation.

### Next: full procedures long-tail run · GEPA on NVFP4 baseline · SME review loop

<!--
Close on the reframe: this isn't "AI replaces translators". It's "AI produces a complete,
consistent first draft in hours and a rigorous workbench so experts spend their time on
judgement, not typing." Then take questions.
-->

---

# Thank you — questions?

<span class="small">
Code: <code>pipelines/</code> · Flows: <code>configs/flows/</code> · Models: <code>configs/models.json</code><br>
Optimisation: <code>scripts/optimization/run_gepa.py</code> · MCP: <code>mcp_server/server.py</code>
</span>
