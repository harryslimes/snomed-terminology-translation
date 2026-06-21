# RAG Analysis & Improvement Plan for SNOMED CT Translation Pipeline

## Part 1: Current State of RAG

### 1.1 Pipeline Overview

The translation pipeline is a LangGraph state machine that translates SNOMED CT preferred terms from English into Estonian. RAG is not used for the initial translation — it kicks in during the enrichment/reflection loop when the LLM lacks confidence.

```
START
  │
  ▼
prepare_initial_hints ─────► Fetches: SNOMED hierarchy, style guide, EN→EE paired translations
  │
  ▼
initial_translation ───────► Claude Sonnet translates using hierarchy context + paired hints
  │
  ├── confident=YES ───────► END
  │
  ▼ confident=NO
enrichment_step ───────────► RAG: dictionary, clinical docs, web search, EE→EN paired translations
  │
  ▼
reflection_step ───────────► Claude Opus refines translation using all retrieved evidence
  │
  ├── confident=YES ───────► END
  ├── max iterations (3) ──► END
  │
  ▼ confident=NO
forced_revision_step ──────► Claude Sonnet revises using SNOMED hierarchy only (NO RAG)
  │
  └──────────────────────────► loops back to enrichment_step
```

**Key files:**

| Component | File | Purpose |
|-----------|------|---------|
| Pipeline graph | `agent/agent.py` | LangGraph state machine, node functions, routing logic |
| Prompt templates | `agent/prompt_templates.py` | 3 templates: initial, reflection, forced revision |
| Retrieval endpoints | `agent/tools.py` | FastAPI server (port 8008) with all retrieval tools |
| Embedder + vector store | `agent/qdrant_store.py` | BGE-M3 embedder, Qdrant hybrid store client |
| Index builder | `scripts/build_qdrant_index.py` | Builds all 5 Qdrant collections from source data |
| Batch execution | `agent/main.py` | Runs pipeline over eval set, tracks cost/confidence |
| State definition | `agent/models.py` | TypedDict with all pipeline state fields |
| Utilities | `agent/utils.py` | Cost calculation, paired translation rendering, best translation selection |

### 1.2 The Five Retrieval Sources

#### Source 1: Paired Translations (EN→EE) — used at initial hints stage

- **Collection**: `paired_translations` (Qdrant), filtered by `direction=EN->EE`
- **Data**: 119,451 bilingual medical term pairs from ICD-10, ICD-11, LOINC, ATC, NOMESCO, WHO, Substances, ContSys (`data/EE-EN/all_bilingual_pairs.csv`)
- **Indexing**: Each row indexed twice (once per direction) using BGE-M3 dense + sparse vectors. Text field is the source-language term. Translation stored in payload.
- **Query strategy**: English preferred term → YAKE keyword extraction (up to 10 unigram keywords) → hybrid lookup per keyword → deduplicate by point ID keeping highest score → return top N
- **Max results**: 3 per keyword (configured in `agent.py:48`)
- **Reranking**: None — aggregated by max score heuristic
- **Prompt integration**: Rendered as a markdown table in the initial translation prompt (`prompt_templates.py:24-26`)

#### Source 2: Paired Translations (EE→EN) — used at enrichment stage

- **Collection**: Same as above, filtered by `direction=ET->EN`
- **Query strategy**: Current Estonian translation → same YAKE + hybrid pipeline as Source 1
- **Prompt integration**: Rendered as a markdown table in the reflection prompt (`prompt_templates.py:100-101`)

#### Source 3: Sonaveeb Clinical Dictionary — used at enrichment stage

- **Collection**: `sonaveeb` (Qdrant), filtered by `lang=et`
- **Data**: ~5,300 Estonian medical dictionary entries (term + definition) from `data/sonaveeb.csv`
- **Indexing**: Each entry indexed with text = `{term}: {definition}`
- **Query strategy**: Current Estonian translation → direct hybrid lookup
- **Max results**: 3 (`agent.py:84`)
- **Reranking**: None
- **Prompt integration**: Rendered as bullet points with term + definition in the reflection prompt (`prompt_templates.py:78-83`)

#### Source 4: Monolingual Estonian Clinical Documents — used at enrichment stage

- **Collections**: `eesti_arst` (~100+ files), `kliinikum` (~4 files), `haiglateliit` (~8 files)
- **Data**: Medical journal abstracts (eesti_arst), university hospital clinical documents (kliinikum), hospital association resources (haiglateliit). Extracted from PDFs via Marker tool. Deduplicated versions in `data/cleaned/`.
- **Indexing**: Whole .txt files indexed as single vectors — no chunking
- **Query strategy**: Current Estonian translation → hybrid lookup per collection → results aggregated across all 3 collections → **Cohere rerank v3.5** → filter by `relevancy_score >= 0.4`
- **Max results**: 3 total after reranking (`main.py:17`)
- **Reranking**: Yes — Cohere rerank-v3.5. This is the only source that uses reranking.
- **Prompt integration**: Rendered as titled passages in the reflection prompt (`prompt_templates.py:85-91`)

#### Source 5: Web Search (Google Scholar) — used at enrichment stage

- **Source**: SerpAPI → Google Scholar (google.ee, Estonian language)
- **Query strategy**: Current Estonian translation → direct Google search
- **Max results**: 5 (`main.py:18`)
- **What's returned**: Title + snippet only — no full page content fetched
- **Prompt integration**: Rendered as titled snippets in the reflection prompt (`prompt_templates.py:93-98`)

### 1.3 Retrieval Mechanism

**Embedding model**: [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) — a multilingual bi-encoder that produces both dense vectors (semantic) and sparse vectors (lexical/BM25-like weights). Configured in `agent/qdrant_store.py:49-127`:
- Max token length: 2048
- Dense vector dimensions: ~1024 (detected at runtime)
- Sparse top-K: 512 lexical weights
- Batch size: 256 (configurable via `BGE_BATCH_SIZE` env var)
- GPU-aware: uses FP16 on CUDA

**Vector store**: Qdrant (Docker container, port 6333). Configured in `docker-compose.yml` with persistent storage at `./data/qdrant_storage`.

**Search strategy**: Hybrid search via `QdrantHybridStore.hybrid_query()` (`qdrant_store.py:162-214`):
- Two prefetch branches: dense (cosine similarity) and sparse (lexical matching)
- Prefetch limit: 4× the requested limit
- Fusion: Reciprocal Rank Fusion (RRF) combining both result sets
- Optional filters: direction filter (for paired translations), language filter (for Sonaveeb)

**Reranking**: Cohere rerank-v3.5 (`agent.py:108-118`) — applied only to monolingual document extracts after aggregation across the 3 document collections. Documents below relevancy 0.4 are filtered out.

### 1.4 Confidence Loop

The LLM self-reports confidence as YES/NO in its JSON output. The confidence rule (from `prompt_templates.py:118-119`):

> "You should ONLY be highly confident in your translation if the following is true: You have seen EACH of the clinical terms in the Estonian translation somewhere in the sources."

Routing logic (`agent.py:190-203`):
- After initial translation: confident=YES → END, else → enrichment
- After reflection: confident=YES OR `len(revised_translations) >= max_reflection_steps` → END, else → forced revision
- After forced revision: always → enrichment (loops back)

The `unverified_words` field tracks which words the LLM couldn't verify in sources. These are passed to the forced revision step.

### 1.5 Configuration Parameters

From `agent/main.py:17-20`:

| Parameter | Value | Controls |
|-----------|-------|----------|
| `MAX_EXTRACTS` | 3 | Max document passages after reranking |
| `MAX_SEARCH_RESULTS` | 5 | Google Scholar snippets |
| `MIN_EXTRACT_RELEVANCY_SCORE` | 0.4 | Cohere rerank threshold |
| `MAX_REFLECTION_STEPS` | 3 | Max enrichment→reflection iterations |

### 1.6 Cost Model

From `agent/utils.py`:
- Claude Sonnet: $3/1M input tokens, $15/1M output tokens (initial translation + forced revision)
- Claude Opus: $15/1M input tokens, $75/1M output tokens (reflection step)
- Token usage tracked per LLM call, aggregated per concept

---

## Part 2: Identified Improvement Areas

### A. Chunking & Indexing

#### A1. Document chunking for clinical texts
**Problem**: Whole .txt files are indexed as single vectors in the eesti_arst, kliinikum, and haiglateliit collections. Long documents produce diluted embeddings. Retrieved "passages" can be very long with the relevant sentence buried inside — wasting context tokens and making it harder for the LLM to find useful information.

**Improvement**: Chunk documents into paragraphs or sliding windows (256–512 tokens with 50-token overlap). Each chunk gets its own vector. Retrieved chunks are more focused and relevant.

**Files affected**: `scripts/build_qdrant_index.py` (indexing logic), `agent/tools.py` (retrieval may need adjustment for chunk-level results)

#### A2. Metadata enrichment on indexed documents
**Problem**: Documents lack structured metadata (medical specialty, document type, year). All documents are treated equally regardless of domain relevance.

**Improvement**: Add metadata fields during indexing (e.g., specialty tags, document type). Enable filtered retrieval — e.g., prefer cardiology documents when translating a cardiology concept. The SNOMED hierarchy could drive this filtering.

**Files affected**: `scripts/build_qdrant_index.py`, `agent/tools.py`

#### A3. N-gram keyword queries for paired translations
**Problem**: YAKE extracts up to 10 single-word keywords. For multi-word medical terms (e.g., "chronic obstructive pulmonary disease"), this fragments the semantic query into individual words like "chronic", "obstructive", etc. — losing the compound meaning.

**Improvement**: Also query with the full term and bi-gram/tri-gram phrases alongside unigrams. This preserves multi-word medical concepts.

**Files affected**: `agent/tools.py:252-290` (keyword extraction and lookup logic)

### B. Retrieval Strategy

#### B1. Rerank paired translations
**Problem**: Cohere reranking is only applied to monolingual document extracts. The 119K paired translations — the richest structured source — use a rough "max score across keyword queries" heuristic for ranking.

**Improvement**: Apply Cohere reranking to paired translation results too. The reranker can assess relevance to the original term better than score aggregation.

**Files affected**: `agent/tools.py:252-290` or `agent/agent.py:44-50, 86-93`

#### B2. Query with English terms too, not just Estonian translation
**Problem**: During enrichment, all sources are queried with the LLM's current Estonian translation. If the translation is wrong, the query is wrong, and retrieval drifts further from relevant evidence. This creates a negative feedback loop.

**Improvement**: Also query with: (a) the original English preferred term, (b) English synonyms, (c) parent/related concept terms. Merge results from both language queries. BGE-M3 is multilingual, so English queries against Estonian documents can still surface relevant results.

**Files affected**: `agent/agent.py:81-128` (enrichment_step), `agent/tools.py` (endpoints may need additional parameters)

#### B3. Cross-lingual retrieval on bilingual pairs
**Problem**: The paired translations collection is queried with direction filters (EN→EE or ET→EN), requiring the query language to match the source side. BGE-M3 is multilingual and could match across languages.

**Improvement**: Query the bilingual collection with the English term and retrieve Estonian translations directly, without relying on keyword extraction. This could be a simpler, more robust retrieval path.

**Files affected**: `agent/tools.py:252-308`

#### B4. Adaptive top-K retrieval
**Problem**: Fixed `max_results=3` for all sources regardless of concept complexity. Simple terms (e.g., "Knee") waste tokens on unnecessary context. Complex terms (e.g., "Chronic obstructive pulmonary disease with acute exacerbation") might benefit from more evidence.

**Improvement**: Scale retrieval count based on signals like: number of words in the term, hierarchy depth, initial confidence level, number of unverified words.

**Files affected**: `agent/agent.py` (enrichment_step), `agent/main.py` (config)

#### B5. Full web page extraction
**Problem**: Google Scholar results only include title + snippet. Snippets may be too short to contain useful terminology. The full page content isn't fetched.

**Improvement**: For top-scoring search results, fetch the full page and extract relevant paragraphs (e.g., paragraphs containing the search term). Would need to handle rate limiting and content extraction.

**Files affected**: `agent/tools.py:399-415`

### C. Prompt & Context Integration

#### C1. Add SNOMED hierarchy context to reflection prompt
**Problem**: The initial translation prompt includes the full SNOMED context (hierarchy, synonyms, parents, related concepts). The reflection prompt — where the most critical reasoning happens — loses all of this. The LLM only has style guidelines + retrieved sources.

**Improvement**: Include the SNOMED hierarchy context in the reflection template. This is a simple template change.

**Files affected**: `agent/prompt_templates.py:51-124`, `agent/agent.py:137-167`

#### C2. Add RAG context to forced revision step
**Problem**: The forced revision step gets only SNOMED hierarchy + unverified words. It has zero retrieved evidence, despite being the step where the LLM most needs help finding alternative Estonian words.

**Improvement**: Either pass the most recent enrichment results into the forced revision prompt, or run a targeted retrieval for the unverified words specifically.

**Files affected**: `agent/prompt_templates.py:126-162`, `agent/agent.py:169-188`

#### C3. Include relevancy scores in prompts
**Problem**: All retrieved passages are presented equally in the prompt. The LLM doesn't know which extracts scored 0.95 relevancy vs 0.41 (barely above threshold). This can lead the LLM to weigh marginal evidence as heavily as strong evidence.

**Improvement**: Annotate each retrieved passage with its relevancy score. Order by relevance (highest first). This gives the LLM a signal about which sources to trust more.

**Files affected**: `agent/agent.py:137-167` (reflection_step formatting), `agent/prompt_templates.py`

#### C4. Deduplicate across sources
**Problem**: The same information can appear in paired translations AND in a clinical document extract AND in a Google Scholar snippet. Redundant context wastes tokens without adding value.

**Improvement**: Before constructing the reflection prompt, deduplicate or consolidate overlapping evidence across sources.

**Files affected**: `agent/agent.py:130-135` (enrichment return), or a new deduplication step

### D. Data Sources & Coverage

#### D1. Index existing Estonian SNOMED translations
**Problem**: The RF2 file `data/SNOMED_EE_national_extension/xsct2_Description_Snapshot-et_EE1000181_20250530.txt` contains ~22K existing official Estonian SNOMED translations. These are the most authoritative reference for medical terminology in Estonian, yet they are not indexed or used as a RAG source.

**Improvement**: Index the RF2 descriptions as a new Qdrant collection. When translating a concept, retrieve translations of related/sibling concepts to ensure terminological consistency.

**Files affected**: `scripts/build_qdrant_index.py` (new collection), `agent/tools.py` (new endpoint), `agent/agent.py` (use in enrichment)

#### D2. SNOMED hierarchy-based retrieval
**Problem**: When translating a concept, the system retrieves evidence by text similarity. It doesn't leverage the SNOMED hierarchy to retrieve translations of parent, sibling, or child concepts — which would ensure terminological consistency within the tree.

**Improvement**: For each concept being translated, look up parent and sibling concept SCTIDs from the graph, then retrieve their existing Estonian translations (from D1) or their paired translation matches. This ensures that "Acute bronchitis" is translated consistently with "Bronchitis" and "Acute respiratory disease".

**Files affected**: `agent/tools.py` (new endpoint using `SnomedGraph`), `agent/agent.py`

#### D3. Re-enable ravimregister
**Problem**: There's a commented-out `/ravimregister` endpoint in `tools.py:364-374`. If this data (pharmaceutical register) is available, it would be valuable for substance/drug-related concepts.

**Improvement**: Re-enable and index the ravimregister data in Qdrant (it was previously using ChromaDB). Conditionally include it for substance/drug hierarchy concepts.

**Files affected**: `scripts/build_qdrant_index.py`, `agent/tools.py`, `agent/agent.py`

#### D4. Expand clinical document corpus
**Problem**: The monolingual Estonian corpus is relatively small — ~112 files across 3 sources. Coverage is uneven (eesti_arst has ~100 files, kliinikum has ~4, haiglateliit has ~8). Many medical concepts may have no relevant Estonian clinical text to retrieve.

**Improvement**: Identify and add more Estonian medical text sources — clinical guidelines, university textbooks, Ravijuhend guidelines, Tervisekassa documentation, etc.

**Files affected**: `scripts/build_qdrant_index.py`, `agent/tools.py`

### E. Evaluation & Feedback Loop

#### E1. Retrieval quality evaluation
**Problem**: The system tracks LLM confidence and iteration count, but doesn't measure whether retrieved passages actually contained the right terminology. There's no way to know if RAG is helping, hurting, or irrelevant for a given concept.

**Improvement**: For a sample of concepts, manually annotate whether retrieved passages contain correct Estonian terms. Compute retrieval precision/recall. Identify concept categories where RAG helps vs is noise.

**Outputs**: Retrieval quality report; identification of weak spots

#### E2. Confidence calibration
**Problem**: Confidence is self-reported by the LLM. There's no verification that confident=YES correlates with correct translations. The LLM might be overconfident (accepts bad translations) or underconfident (wastes iterations on good translations).

**Improvement**: Compare confident=YES translations against the existing RF2 Estonian translations (where overlap exists) and against expert review. Compute calibration curves. Adjust the confidence prompt instructions if miscalibrated.

**Files affected**: Analysis scripts; potentially `agent/prompt_templates.py` confidence instructions

#### E3. Retrieval feedback loop
**Problem**: When a translation succeeds or fails, that signal isn't used to improve future retrieval. Each concept is translated in isolation.

**Improvement**: Log which retrieved passages the LLM actually cited in its reasoning. Over time, use this to build a relevance dataset for fine-tuning the retrieval or adjusting reranking thresholds.

**Outputs**: Retrieval relevance dataset; threshold tuning data

### F. Architecture

#### F1. Parallelise monolingual source queries
**Problem**: eesti_arst, kliinikum, and haiglateliit are queried sequentially in a for-loop (`agent.py:98-105`). This adds unnecessary latency.

**Improvement**: Use `asyncio.gather()` or `concurrent.futures` to query all 3 in parallel. Alternatively, merge all monolingual documents into a single Qdrant collection with a `source` payload filter.

**Files affected**: `agent/agent.py:95-105`

#### F2. Replace HTTP intermediary with direct function calls
**Problem**: The agent calls `requests.get("http://localhost:8008/...")` for every retrieval. This adds HTTP serialisation/deserialisation overhead and makes the pipeline dependent on the FastAPI server running.

**Improvement**: Import the retrieval functions directly into the agent module. The FastAPI server can remain for interactive/debug use, but the batch pipeline shouldn't need HTTP.

**Files affected**: `agent/agent.py` (replace requests with direct imports from tools.py)

---

## Part 3: Investigation & Testing Plan

### Testing Methodology

**Eval dataset**: Use `data/evals/sample/100_concepts.csv` (100 concepts across multiple hierarchies).

**Baseline**: Current pipeline results in `data/evals/sample/100_translations_claude.csv`.

**Per-experiment process**:
1. Implement the change behind a feature flag or config parameter
2. Run the pipeline on the 100-concept eval set
3. Compare against baseline using:
   - **Quantitative metrics**: confidence rate (% YES), average iteration count, average cost per concept, total token usage
   - **Qualitative comparison**: Use the existing `scripts/subjective_compare.py` pattern — have a local LLM (Qwen 35B) compare baseline vs experimental translations side-by-side
4. Log retrieval diagnostics: what was retrieved, relevancy scores, what the LLM cited

**Comparison CSV format** (extending `scripts/build_translation_compare.py`):
```
sctid, preferred_term, baseline_translation, experiment_translation, baseline_confident, experiment_confident, baseline_iterations, experiment_iterations
```

### Phase 1 — Quick Wins (Low Effort, High Impact)

These are prompt/config changes that don't require re-indexing or new data sources.

#### Experiment 1.1: Add SNOMED context to reflection prompt (C1)
- **Hypothesis**: Including hierarchy, synonyms, parents, and related concepts in the reflection prompt will improve translation accuracy, especially for terms where SNOMED relationships disambiguate meaning.
- **What to measure**: Confidence rate, iteration count, subjective quality comparison.
- **Implementation**: Add SNOMED variables to `reflection_template`. Pass them from state in `reflection_step()`.
- **Effort**: ~30 minutes. Template edit + 2 lines in agent.py.
- **Dependencies**: None.

#### Experiment 1.2: Query enrichment sources with English term too (B2)
- **Hypothesis**: Querying with the English preferred term in addition to the Estonian translation will surface more relevant evidence, especially when the initial translation is poor.
- **What to measure**: Retrieval relevance (manual spot-check), confidence rate, iteration count.
- **Implementation**: In `enrichment_step()`, query each source twice (Estonian + English), merge and deduplicate results before reranking.
- **Effort**: ~1–2 hours. Changes to `agent.py` enrichment_step.
- **Dependencies**: None.

#### Experiment 1.3: Add RAG context to forced revision (C2)
- **Hypothesis**: Giving the forced revision step access to the most recent enrichment results will help it find better alternative words for unverified terms.
- **What to measure**: Rate at which forced revisions produce confident=YES on the next reflection, iteration count.
- **Implementation**: Pass `state["extracts"][-1]`, `state["dictionary_hints"][-1]` into forced_revision_template. Extend the template with a sources section.
- **Effort**: ~1 hour. Template edit + state passing.
- **Dependencies**: None.

#### Experiment 1.4: Rerank paired translations (B1)
- **Hypothesis**: Applying Cohere reranking to paired translation results will improve the quality of translation hints by filtering out keyword-matched but semantically irrelevant pairs.
- **What to measure**: Subjective quality of retrieved pairs (manual review on 20 concepts), translation quality.
- **Implementation**: After aggregating paired translation results, apply `cohere_client.rerank()` with the original preferred term as query.
- **Effort**: ~1 hour. Changes to `agent.py` or `tools.py`.
- **Dependencies**: None.

#### Experiment 1.5: Include relevancy scores in prompts (C3)
- **Hypothesis**: Annotating retrieved passages with their relevancy scores helps the LLM prioritise strong evidence over marginal evidence.
- **What to measure**: Subjective quality comparison, confidence calibration.
- **Implementation**: Modify extract rendering in `reflection_step()` to include `[relevancy: 0.87]` annotations. Order by score descending.
- **Effort**: ~30 minutes.
- **Dependencies**: None.

### Phase 2 — Core Retrieval Improvements (Medium Effort, High Impact)

These require re-indexing or new data sources.

#### Experiment 2.1: Chunk clinical documents (A1)
- **Hypothesis**: Chunking documents into 256–512 token paragraphs with overlap will improve retrieval precision. Retrieved chunks will be more focused, reducing noise in the reflection prompt.
- **What to measure**: Retrieval precision (manual review on 20 concepts), confidence rate, token usage (should decrease if passages are shorter).
- **Implementation**:
  1. Add a text chunking function to `build_qdrant_index.py` (sentence-aware splitting, ~400 tokens per chunk, 50-token overlap)
  2. Re-index eesti_arst, kliinikum, haiglateliit with chunked documents
  3. Adjust retrieval — may need to increase `max_results` per collection to 5 since chunks are smaller
- **Effort**: ~3–4 hours.
- **Dependencies**: None.

#### Experiment 2.2: Index existing RF2 Estonian translations (D1)
- **Hypothesis**: Retrieving existing official Estonian translations of related SNOMED concepts provides the most authoritative evidence for terminological consistency.
- **What to measure**: Confidence rate, iteration count, terminology consistency with existing SNOMED translations.
- **Implementation**:
  1. Parse `xsct2_Description_Snapshot-et_EE1000181_20250530.txt` (tab-delimited RF2)
  2. Index active descriptions as a new `snomed_et_descriptions` collection in Qdrant
  3. Create a `/snomed_et_translations` endpoint in tools.py
  4. Add to enrichment_step: query with English preferred term, retrieve Estonian translations of similar concepts
  5. Add to reflection prompt as a new source section
- **Effort**: ~4–6 hours.
- **Dependencies**: None.

#### Experiment 2.3: SNOMED hierarchy-based retrieval (D2)
- **Hypothesis**: Retrieving Estonian translations of parent/sibling concepts ensures terminological consistency within the SNOMED hierarchy tree.
- **What to measure**: Consistency of translation patterns within concept families, subjective quality.
- **Implementation**:
  1. In enrichment_step, get parent and sibling SCTIDs from `SnomedGraph`
  2. Look up their Estonian translations in the RF2 collection (from 2.2)
  3. Present these as "translations of related SNOMED concepts" in the reflection prompt
- **Effort**: ~2–3 hours.
- **Dependencies**: Experiment 2.2 (RF2 index).

#### Experiment 2.4: N-gram keyword queries for paired translations (A3)
- **Hypothesis**: Querying with bi-gram and tri-gram phrases in addition to unigrams will improve recall for multi-word medical terms.
- **What to measure**: Number and relevance of paired translation hits, translation quality for multi-word terms specifically.
- **Implementation**: Modify YAKE config to extract n=1,2,3 keywords. Add full-term query alongside keyword queries.
- **Effort**: ~1–2 hours.
- **Dependencies**: None.

### Phase 3 — Evaluation Infrastructure (Medium Effort, Foundational)

#### Experiment 3.1: Retrieval quality evaluation (E1)
- **Hypothesis**: Measuring retrieval quality will identify which sources help vs hurt for which concept types, enabling targeted improvements.
- **What to measure**: Retrieval precision@K, recall of correct Estonian terms in retrieved passages.
- **Implementation**:
  1. For 50 concepts where the RF2 translation exists, check if retrieved passages contain the official Estonian term or close variants
  2. Log all retrieved passages per concept with scores
  3. Compute precision by source (paired translations, dictionary, documents, web)
  4. Identify concept categories (by hierarchy) where each source is most/least useful
- **Effort**: ~4–6 hours (mostly analysis scripting).
- **Dependencies**: Good to run before Phase 2 changes to establish a retrieval baseline.

#### Experiment 3.2: Confidence calibration (E2)
- **Hypothesis**: LLM confidence may not correlate well with actual translation correctness. Calibrating this could reduce wasted iterations (overconfident) or unnecessary loops (underconfident).
- **What to measure**: Correlation between confident=YES and match with RF2 translations or expert judgement.
- **Implementation**:
  1. Run pipeline on concepts that have existing RF2 Estonian translations
  2. Compare pipeline output vs RF2 translation (exact match, fuzzy match, expert review)
  3. Stratify by confident=YES vs NO
  4. If miscalibrated, adjust confidence instructions in prompts
- **Effort**: ~3–4 hours.
- **Dependencies**: Access to RF2 translations (available in data/).

### Phase 4 — Advanced Improvements (Higher Effort, Experimental)

#### Experiment 4.1: Cross-lingual retrieval on bilingual pairs (B3)
- **Hypothesis**: BGE-M3's multilingual embeddings can match English queries against Estonian text directly, bypassing the YAKE keyword extraction pipeline entirely.
- **What to measure**: Retrieval quality comparison: YAKE + hybrid vs direct cross-lingual query.
- **Implementation**: Query the paired_translations collection with the English term, no direction filter, using hybrid search. Compare retrieved results with current YAKE-based approach.
- **Effort**: ~2 hours.
- **Dependencies**: None, but should be informed by Phase 3 retrieval evaluation.

#### Experiment 4.2: Adaptive top-K retrieval (B4)
- **Hypothesis**: Scaling retrieval count based on concept complexity will reduce noise for simple terms and improve evidence for complex terms.
- **What to measure**: Token usage, confidence rate, cost per concept.
- **Implementation**: Use heuristics (term word count, hierarchy depth, initial confidence) to set `max_results` dynamically per source.
- **Effort**: ~2–3 hours.
- **Dependencies**: Phase 3 evaluation to understand which concepts need more evidence.

#### Experiment 4.3: Expand clinical document corpus (D4)
- **Hypothesis**: A larger Estonian medical text corpus will improve retrieval coverage, especially for concepts where current sources return nothing relevant.
- **What to measure**: Retrieval hit rate (% of concepts with at least one passage above relevancy threshold), confidence rate.
- **Implementation**: Source additional Estonian medical texts (clinical guidelines, Ravijuhend, Tervisekassa docs). Process, deduplicate, chunk, and index.
- **Effort**: Variable — depends on data sourcing. Index building is straightforward once data is obtained.
- **Dependencies**: Experiment 2.1 (chunking) should be done first so new data is indexed properly.

#### Experiment 4.4: Re-enable ravimregister (D3)
- **Hypothesis**: Pharmaceutical register data improves translations for substance/drug-related concepts.
- **What to measure**: Translation quality for substance hierarchy concepts specifically.
- **Implementation**: Index ravimregister data in Qdrant (previously used ChromaDB). Add conditional retrieval for substance/drug hierarchies.
- **Effort**: ~2–3 hours (if data is available).
- **Dependencies**: None.

---

## Part 4: Recommended Execution Order

```
Phase 3.1 (Retrieval evaluation)     ← Do first to establish baseline
    │
    ├── Phase 1.1 (SNOMED in reflection prompt)     ← Quick, independent
    ├── Phase 1.2 (English term queries)             ← Quick, independent
    ├── Phase 1.3 (RAG in forced revision)           ← Quick, independent
    ├── Phase 1.4 (Rerank paired translations)       ← Quick, independent
    └── Phase 1.5 (Relevancy scores in prompts)      ← Quick, independent
    │
    ▼ Re-evaluate after Phase 1 changes
    │
    ├── Phase 2.1 (Document chunking)                ← Re-index required
    ├── Phase 2.2 (Index RF2 translations)           ← New collection
    │       └── Phase 2.3 (Hierarchy retrieval)      ← Depends on 2.2
    └── Phase 2.4 (N-gram queries)                   ← Independent
    │
    ▼ Re-evaluate after Phase 2 changes
    │
    ├── Phase 3.2 (Confidence calibration)
    │
    ▼ Re-evaluate, then selectively pursue Phase 4
    │
    ├── Phase 4.1 (Cross-lingual retrieval)
    ├── Phase 4.2 (Adaptive top-K)
    ├── Phase 4.3 (Corpus expansion)
    └── Phase 4.4 (Ravimregister)
```

**Key principle**: Measure before optimising. Phase 3.1 (retrieval evaluation) should come first or in parallel with Phase 1, so we understand where RAG is currently helping and where it's failing. This focuses subsequent efforts on the areas with the biggest gaps.

**After each phase**: Re-run the 100-concept eval set and compare against baseline using the quantitative metrics + subjective LLM comparison. Only proceed to the next phase after reviewing results.
