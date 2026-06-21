# Speaker runbook — SNOMED translation talk (30 min)

Companion to `snomed_translation_talk.md`. Timing, talk track, the live MCP demo, and
the honesty caveats to keep you out of trouble.

## Audience
Mixed technical ability, varying AI/LLM familiarity. Every technical idea needs a
one-line plain-language analogy (they're written into the speaker notes in the deck).

---

## Timing plan (30 min, leaves ~4 min Q&A)

| Min | Section | Slides | Goal |
|----:|---------|--------|------|
| 0–1 | Title + agenda | 1–2 | Frame: 350k concepts, years of manual work → hours |
| 1–5 | Core idea: template prompt | 3–5 | Mail-merge analogy; show the real template |
| 5–7 | The task: SNOMED + Korean | 6 | Why it's hard (conventions) |
| 7–12 | The app: flows + import | 7–10 | Flow = reproducible recipe; SNOMED in/out |
| 12–15 | The hierarchy trick | 10 | Reuse approved translations as context |
| 15–18 | Capturing variables + eval | 11–12 | The real contribution; honesty caveat |
| 18–21 | Model + speed | 13–15 | MoE in plain terms; "all SNOMED in ~3 hrs" |
| 21–25 | GEPA | 16–18 | Self-improving rules; show the diff |
| 25–28 | **Live MCP demo** | 19–20 | Temperature sweep by conversation |
| 28–30 | Recap + Q&A | 21–23 | Reframe; questions |

If running long, the compressible sections are slides 8 (the JSON flow) and 17 (GEPA-as-flow) —
mention and move on. **Protect the demo and the speed slides** — those are what the room remembers.

---

## Talk track — the four moments that must land

1. **Template = mail-merge** (slide 4). "The instructions are written once. We swap in
   the term and its context for each of 350,000 concepts. That's all batch translation is."
2. **Hierarchy trick** (slide 10). "We don't invent translations — we hand the model the
   related terms already approved in the official Korean release and ask it to stay consistent."
3. **All of SNOMED in ~3 hours** (slide 15). "This reframes the problem from *years of
   manual work* to *an afternoon of compute plus focused expert review of a complete draft*."
4. **GEPA reads its own mistakes** (slide 18). "Like a style sheet that updates itself every
   time an editor flags an error — and a human approves the diff before it's adopted."

---

## ⚠️ Honesty caveats (do not over-claim)

- **Do NOT present a headline quality % (e.g. "78% exact match").** Those figures came from
  runs affected by an embedding-cache leakage bug that inflated exact-match by ~35pp. Honest
  long-tail acceptable-rate is in the 40s%. If pushed for a number: *"we're re-validating the
  magnitudes; the framework's job is to move that number up measurably and prove it."*
- **Speed numbers are fine.** Throughput (~32 req/s) is a timing measurement, unaffected by
  the cache bug. The full-SNOMED estimates extrapolate it; call them estimates.
- **Always say "first draft for expert review,"** never "finished translation."
- These are *prior* ablation numbers (April 2026), not measured live for this talk — say so.

---

## Live MCP demo — runbook

**What it shows:** an AI assistant driving the app's API to run the same flow at three
temperatures and compare — an experiment launched by one instruction.

### Pre-flight (do before the talk)
1. MCP server reachable (it's configured in `.mcp.json`; tools appear as `mcp__snomed__*`).
2. The Gemma vLLM endpoint is **up** (the runs actually translate). Confirm with a tiny run.
3. Keep the wizard **Runs** page open in a browser tab as the visual: `/runs`.
4. Use a **small `limit`** on the translate node (e.g. 20–30 terms) so each run finishes in
   seconds, not minutes — set it once on the base flow before duplicating.

### Live sequence (the assistant runs these tools)
```
list_flows()                                    # show the baseline exists
for t in [0.0, 0.5, 1.0]:
    duplicate_flow("ko_baseline", new_name=f"temp {t}")     # -> new flow id
    set_node_params(<new_id>, "translate_full", {"temperature": t})
    run_flow(<new_id>)                          # -> {job_id, state}
list_runs()                                     # the three jobs queue (one GPU at a time)
get_run(<job_id>)                               # poll until succeeded; read headline_score
```
- **Temperature lives at** `translate_full` node → `params.temperature` (read at
  `pipelines/graph.py:314`; merged into the LLM call in `pipelines/stages/translate.py`).
  Setting the key genuinely changes behavior — verified.
- Talking point while it runs: "temperature 0 = same answer every time (what you want for a
  reproducible terminology run); higher = variation, useful when you want to sample
  alternatives and let a judge pick the best."

### Fallback (if the endpoint or demo is flaky)
Pre-built flows already exist — **don't build live, just show their results:**
`temp-0-0`, `temp-0-5`, `temp-1-0` (project `compare_temperature_on_translation_mcp`).
Open their finished runs in the wizard `/runs` page and compare scores. Same story, zero risk.

---

## Rendering the deck

Marp Markdown. Options:

- **VS Code:** install the *Marp for VS Code* extension, open `snomed_translation_talk.md`,
  use the preview / "Export slide deck…" (PDF, PPTX, HTML).
- **CLI:**
  ```bash
  npx @marp-team/marp-cli docs/presentation/snomed_translation_talk.md -o talk.pdf
  npx @marp-team/marp-cli docs/presentation/snomed_translation_talk.md --pptx -o talk.pptx
  npx @marp-team/marp-cli docs/presentation/snomed_translation_talk.md --html -o talk.html
  ```
- Speaker notes are in `<!-- ... -->` comments; Marp shows them in presenter mode
  (and exports them to PPTX notes).

---

## Optional live extras (only if confident)
- **Wizard graph editor** (slide 7): open a flow's graph view to show the visual DAG —
  much more compelling than the JSON for a mixed audience.
- **Diff view** (slide 18): open a style-guide diff in the wizard to show word-level
  highlighting of what GEPA changed (`wizard/diffview.py` renders it).
