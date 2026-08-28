# SNOMED CT Translation Platform: Programme Brief

**Subtitle:** A concise guide to adapting, validating, and delivering a new language project  
**Audience:** programme leaders, terminology teams, potential customers, subject-matter experts, and service owners  
**Purpose:** summarise how the platform works, what a language project requires, and how the capability could be offered to users  
**Status:** draft for organisational review, 2026-08-28

## Executive summary

Every SNOMED CT language project starts from a different position. One country may have a substantial but incomplete national extension; another may have only glossaries, mappings, clinical writing, and a small group of experts. Language rules also differ across clinical domains. A prompt that works for Korean imaging is not automatically suitable for Norwegian findings or Spanish substances.

The platform is therefore built around a simple proposition:

> **What transfers between languages is not one fixed prompt. It is a measured, auditable process for finding and validating the right translation approach.**

Each language is treated as a small research programme followed by a controlled production run. Existing resources are imported and indexed for semantic search. A base translation guide seeds the agent. A representative subset is translated and reviewed by a terminology subject-matter expert (SME). The SME supplies canonical translations and quality ratings; those decisions become adjudicated gold data, rules, style-guide improvements, and better retrieval examples. GEPA can then optimise the remaining prompt-sensitive problems against separated training and held-out data.

The cycle repeats on fresh concepts until the agreed quality gate is met. Only then is the winning, version-pinned flow used at broader scale. The final output remains subject to SME review and sign-off.

The capability can be made available in two complementary ways:

- an **open-source, self-hosted edition**, where customers receive the project and connect their own local or API models; and
- a **managed service**, where we operate the platform and supply cloud inference, charging for onboarding, platform access, usage, optional optimisation, and any human services.

## 1. The capability in one view

The workbench combines six functions that would otherwise be separate pieces of work:

1. **Project setup** — the reusable `translation_process` template installs the plan, gates, flows, starter rules, source definitions, and methodological safeguards.
2. **Resource ingestion** — SNOMED CT content and available language resources are registered with their provenance and licence conditions.
3. **Semantic retrieval** — bilingual pairs and other approved contextual material are indexed so the translation agent sees relevant examples at translation time.
4. **Controlled translation experiments** — models, prompts, parameters, datasets, and flow designs are explicit and versioned.
5. **SME feedback and prompt evolution** — review creates canonical gold data and editorial rulings; GEPA optimises prompt-level residue when its evidence requirements are satisfied.
6. **Quality assurance and delivery** — automated detectors, blinded samples, audit trails, promotion gates, and SME sign-off protect the release.

Every material number should come from a tracked run. Every promoted result should identify the source data, code, model, prompt, style guide, and rules that produced it.

## 2. What is reusable and what each language supplies

| Reused for every language | Supplied or developed for each language |
|---|---|
| Project template, plans, gates, and workflow engine | Licensed SNOMED CT release and chosen hierarchy scope |
| Import and semantic-indexing machinery | Existing extension, translation pairs, glossaries, mappings, or suitable clinical narrative |
| Model registry for local and API endpoints | A base translation guide and target-language conventions |
| Translation, evaluation, QA, review, and repair flows | SME-adjudicated translations for optimisation and held-out evaluation |
| GEPA prompt-optimisation workflow | Terminology SME time and authority to set the quality bar |
| Run tracking, provenance, and audit trail | Language-specific rules, glossary, and curated retrieval pool as they mature |
| Tool interface through which an AI assistant can operate the research workflow | Decisions on licensing, ownership, residency, publication, and maintenance |

This separation is why the platform can scale. The engineering method is reused; the language receives the data and expert attention it genuinely needs.

Different parts of SNOMED CT may also be treated as separate research scopes. Procedures, findings, substances, and organisms follow different naming conventions. A smaller guide, exemplar pool, and gold set for one hierarchy section can outperform one oversized prompt covering every domain. Sections can be researched and promoted on different timetables, beginning where clinical value is highest.

## 3. The end-to-end language process

### Step 1 — Define and provision the project

Choose a coherent hierarchy section or clinical domain rather than beginning with the whole terminology. Record the SNOMED CT edition, release date, modules, relationships, target language, model configuration, and intended publication route.

Seed the project from `translation_process`. Its first gate remains blocked until the terminology, usable translation resources, SME commitment, and domain slice are available.

### Step 2 — Bring the available language resources

Useful starting material may include an incomplete national extension, approved translation pairs, terminology mappings, medical dictionaries, standard vocabularies, or representative clinical writing. Each source must have suitable reuse rights and clear provenance.

Translation pairs are curated and indexed semantically. When the agent receives an English concept term, it retrieves the closest approved examples and includes them with the style guide, applicable rules, and available SNOMED CT attributes. This gives the model language-specific context without treating the most frequent wording as automatically canonical.

A greenfield language needs an explicit seed-pool activity. An empty exemplar pool is an honest starting state, but it is not enough for a retrieval-assisted production run.

### Step 3 — Establish a baseline

Supply a draft translation guide. It can be short: script, spacing, abbreviations, format, and known terminology policy. Detailed rules should emerge from SME evidence rather than being guessed in advance.

Translate a representative pilot subset spanning hierarchy positions, structural complexity, and expected difficulty. Run automated checks for rule violations, lost modifiers, suspicious transliteration, hierarchy inconsistency, and collisions where distinct concepts receive the same translation.

The model is swappable. A local open-weight model can perform the routine bulk work; uncertain concepts can be routed to a stronger commercial endpoint. Because every configuration is scored, the local/API choice is an evidence-based cost and quality decision rather than a fixed architectural assumption.

### Step 4 — Obtain structured SME feedback

Package a blinded, stratified sample—typically about 100–120 concepts—and ask the SME to provide:

- a rating such as perfect/canonical, acceptable, partial, or wrong;
- the canonical translation where correction is needed;
- accepted synonyms where useful; and
- answers to a small number of cross-cutting adjudication questions.

The SME remains the authority. Machine output never overwrites an adjudicated row. If a newer ruling changes an older decision, supersession is recorded and the affected rows are shown for confirmation.

### Step 5 — Turn review into reusable language assets

Ingest the returned review through a tracked flow. Feedback is encoded in the most durable form available:

1. canonical terms and accepted variants enter the adjudicated gold set;
2. deterministic requirements become hard rules and safe repairs;
3. editorial and word-order guidance updates the style guide;
4. unsuitable or superseded examples are removed from future retrieval; and
5. open questions and supersessions remain visible in the adjudication record.

Re-translating the reviewed concepts shows whether the system has absorbed the decisions. Generalisation is tested on fresh held-out concepts, not on the rows used to develop the changes.

### Step 6 — Optimise the prompt where appropriate

GEPA can propose and evaluate revised instructions using the growing set of trusted translations. The evolved guide remains a readable, versioned document that a human can accept, amend, or reject.

GEPA should be used after straightforward rules, glossary decisions, and pool corrections have been applied. Before a candidate prompt is promoted, the project needs:

- separated optimisation and held-out evaluation data;
- retrieval controls preventing a concept from seeing its own translation;
- a metric shown to align with SME judgement;
- frozen rules that candidates cannot trade away; and
- evidence that the candidate beats the current prompt on held-out concepts.

### Step 7 — Repeat, then run at scale

Translate a fresh subset and repeat the review–improvement cycle. Early rounds normally settle high-volume language conventions; later rounds concentrate on difficult structure, rare terminology, and ambiguity.

Once the agreed quality threshold is met, freeze the winning model, prompt, guide, rules, pool, and code versions. Run the broader scope, audit the output, resolve blockers, and obtain formal SME sign-off before publication.

## 4. Evidence from the Korean work

The presentation `snomed-translation-deck.html` records an accessible early result: in the first 100-term SME review, 47 translations were rated acceptable, 51 partial, and two wrong. This meant 98 were usable or near-usable, but the 51 partial terms still required expert correction. The result demonstrated drafting value, not publication readiness.

The later project work strengthened both the method and the evidence:

- a 5,012-concept imaging domain was translated through a confidence-routed cascade;
- approximately 45% of concepts were escalated to the stronger model;
- the full run completed without errors and the local sampling stage took about 23 minutes on one GPU workstation;
- systematic SME rulings were converted into guide changes and deterministic rules, sharply reducing recurring convention defects; and
- blinded review, leakage-safe evaluation, explicit supersession, pair-level collision checks, and held-out promotion gates were added after weaknesses were found in earlier experiments.

One early GEPA development result improved exact agreement from 28% to 42%, but later analysis found that the wider evaluation design allowed retrieval leakage. The correct lesson is not that optimisation automatically improves every language. It is that prompt evolution must be measured on a leak-free held-out set and promoted only when it beats the current guide under that stricter test.

## 5. Cost and resource shape

Compute is measurable and comparatively inexpensive. Expert review is the scarce resource.

### Machine cost

**Prompt caching is the main API cost control for this workload and must be included in the headline estimate.** The measured 5,012-concept production pass sent 16.87 million input tokens and about 33,000 output tokens to Qwen 3.8 Max, but approximately 55% of the input was served from the provider's prompt cache. The billable shape was therefore approximately:

| Billing class | Measured volume | Current Qwen 3.8 Max international list rate | Estimated cost |
|---|---:|---:|---:|
| Uncached input | 7.59M tokens | $2.00/M | $15.18 |
| Implicit-cache input | 9.28M tokens | $0.25/M | $2.32 |
| Output | 0.033M tokens | $6.00/M | $0.20 |
| **Measured full pass** |  |  | **about $17.70** |

Those rates were checked on 28 August 2026. Charging every input token at the ordinary rate would incorrectly estimate the same pass at about $33.94—almost twice the cache-aware figure. The measured deployment should therefore be presented as an approximately **$18 full pass**, not as a broad cross-provider price range.

Future quotations should use the run's recorded uncached, cache-read, cache-creation, and output tokens separately. They should also state the expected cache-hit ratio and prompt ordering. Stable material—system instructions, the style guide, rules, and other repeated context—belongs at the beginning of the prompt so that the provider can reuse the longest possible prefix. Explicit caching may reduce repeat-read cost further where the provider and workload support it; lower-cost models or local inference can reduce API spend again.

A project may need two or three broad passes, but small pilot and absorption runs cost a fraction of a full pass and deterministic repair requires no model call. API inference should therefore be presented as a small, measured operating cost; SME and service effort remain the material costs.

An open model can handle bulk sampling on owned or cloud GPU capacity. Semantic indexing is mainly an onboarding cost, and unchanged embeddings can be reused when the pool is updated. Deterministic QA and repair often require no model call.

GEPA evaluates many prompt candidates and should have a separate capped budget. Its proposed maximum should be calculated from candidate count, evaluation-set size, model routing, and cache-aware token rates before the run begins. Start with the smallest useful experiment, record actual cache performance and spend, and expand only when the quality gain justifies it.

### Human resource

| Activity | Planning assumption for a roughly 5,000-concept domain |
|---|---|
| One standard SME round | about 2–4 hours for a 100–120-term sample and adjudication questions |
| Number of rounds | commonly 3–5 |
| Total SME effort | about 10–20 hours with useful existing reference data |
| Greenfield allowance | roughly 50% more SME effort and one or two additional rounds |
| Operator effort | approximately one setup week, then 1–2 days per round |

These are planning anchors from one language and domain, not fixed quotations. A customer price must also recover hosting, storage, indexing, monitoring, support, security, data governance, failed runs, provider-price changes, invoicing, and service margin.

## 6. Ways to make it available

### Open-source, self-hosted

Customers receive the complete engine, project template, plugin interfaces, and deployment guidance. They provide their licensed terminology and language assets, deploy the vector database and storage, and connect any compatible local or API models.

This option supports strict residency and maximum technical control. We avoid inference-cost and credit exposure, but still need documentation, release management, compatibility testing, and a support model. Paid onboarding or enterprise support can sit around the open-source edition.

### Managed service with our inference

We host and operate the workbench, semantic index, storage, monitoring, and approved model endpoints. The customer supplies its licensed content and SME access. We pay cloud and inference providers, meter usage, and bill the customer.

A practical charging structure is:

```text
onboarding fee
+ platform subscription with an included usage allowance
+ translated-concept or project-round overage
+ optional capped GEPA optimisation
+ professional or SME services where supplied
```

Raw tokens should be metered internally, but a concept- or round-based customer unit is easier to budget and better reflects the value of the workflow, QA, provenance, and support. Pricing needs contingency for model-price volatility and failed or repeated runs.

A managed customer could alternatively connect its own approved model endpoint. This helps with procurement or cloud policy but requires a clear shared-support boundary.

### Recommended approach

Offer **open core with an optional managed service**. The same maintained method supports customers that must self-host and those that need rapid adoption without ML infrastructure. The managed service should be priced for curation and assurance, not presented merely as token resale.

Before launch, legal and governance teams must settle SNOMED CT licensing, bilingual-data ownership, generated-translation ownership, data residency, model-provider terms, retention, and whether language assets may be contributed back across projects.

## 7. Recommended rollout

1. **Package a reference self-hosted edition.** Document one supported deployment, model interface, data-import path, and security baseline.
2. **Run a managed-service pilot.** Capture real onboarding, infrastructure, support, SME, and inference costs rather than setting prices from token estimates alone.
3. **Benchmark against a mature translation.** The deck proposes Spanish SNOMED CT as a useful case because a broad human translation already exists; legal access and an evaluation-safe split would need to be confirmed.
4. **Compare total effort.** Evaluate one self-hosted and one managed adopter using the same quality gates, including customer and SME time.
5. **Set the product boundary.** Decide supported territories, residency options, service levels, pricing units, open-source licence, contribution rules, and the quality claims the organisation is willing to publish.

The immediate readiness test for any first customer is simple: a defined SNOMED CT scope, licensed source data, a usable seed pool or seeding plan, a draft guide, reserved SME time, approved model infrastructure, leakage-safe evaluation, and an agreed sign-off route.

## 8. Sources and notes

This brief combines the implemented `translation_process` method, the longer organisation guide, the project handover, and the shared-drive presentation **“SNOMED CT, in any language — translation workbench”** (`snomed-translation-deck.html`). Where early presentation claims conflicted with later project evidence, the later tracked findings and safeguards take precedence.

External prices and licensing terms change. References checked for the detailed guide on 26 August 2026 include:

- [OpenAI API pricing](https://platform.openai.com/pricing)
- [Anthropic model pricing](https://www-cdn.anthropic.com/files/4zrzovbb/website/5678bc2f5978e5bcd4f1fe7c14b2c72284dcf9f8.pdf)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [Alibaba Cloud Qwen 3.8 Max pricing](https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max)
- [Alibaba Cloud context-cache billing](https://www.alibabacloud.com/help/en/model-studio/context-cache)
- [SNOMED International vendor licensing guidance](https://docs.snomed.org/snomed-ct-practical-guides/vendor-introduction-to-snomed-ct/7-licensing)
- [SNOMED International: Get SNOMED CT](https://www.snomed.org/get-snomed)

Any customer proposal must refresh these inputs and receive commercial, legal, security, and information-governance review.
