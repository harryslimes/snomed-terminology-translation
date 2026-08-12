# Providing access to the translation system — delivery options

**Status:** discussion paper for SNOMED International. Draft, 2026-08-12.
**Purpose:** set out the realistic ways to make this system available to member countries and
other adopters, and what each commits us to.

---

## 1. What is actually being offered

This matters more than the hosting question, because it determines what a customer is paying for
and what we would be liable for.

The system is a **translation drafting and quality-assurance pipeline**, not a translation engine.
The language model is the least distinctive part of it and is swappable — the system has been run
against local open-weight models, three commercial APIs, and an agent SDK, and the model can be
changed per node in a config file.

The parts that are hard to replicate, and that constitute the actual asset:

| Asset | Why it is hard to reproduce |
|---|---|
| **The QA detector family** | Rule validation, SNOMED is-a hierarchy consistency, contrast fidelity, transliteration, duplicate-rendering detection. Each was built in response to a defect found in real output. |
| **The repair loop** | detect → repair → verify in context → adopt selectively, with guards that refuse a change introducing a new defect, and that refuse to overwrite a row a human reviewer has adjudicated. |
| **Accumulated rulings per language** | The style guide and the machine-checkable rule file, built from expert review rounds. This is the compounding asset. |
| **Provenance** | Every number comes from a tracked run pinned to code shas and content-addressed inputs, so a result can be reproduced and a deliverable can be tied to the exact bytes a reviewer saw. |
| **The reviewer feedback loop** | Packaging, prioritisation, and the machinery for folding expert rulings back into the rules. |

**What it does not do:** produce publication-ready translations without expert review. On a
held-out set adjudicated by a clinical expert, exact agreement is in the mid-40% range, with most
of the remainder being acceptable-but-differently-worded rather than wrong. Any offer we make must
be framed as *reducing expert effort*, not replacing it. Overselling this is the fastest way to
damage trust in the standard itself.

---

## 2. The three options

### Option A — Open source, self-hosted

Publish the engine and the language plugins; adopters run everything on their own infrastructure
against their own model endpoints.

**For**

- **Data never leaves the member country.** This is decisive for several members. Some national
  authorities cannot send clinical terminology to a commercial API in another jurisdiction at all,
  which makes A the only viable option for them regardless of what else we build.
- **No model-cost liability for us**, and no need for a commercial billing function.
- **Aligns with our role.** We are a standards body. Publishing the tooling that helps members
  implement the standard is recognisably our job in a way that reselling inference is not.
- **The architecture already assumes it.** The engine and the language-specific plugin are
  separate; adding a language is a provisioning step, not a fork. A member country contributing
  its own language plugin is the natural contribution model.

**Against**

- **Setup burden is real**: a vector database, an embedding model, RF2 ingest, and a curated
  bilingual exemplar pool. This is a week of competent engineering time, not an afternoon.
- **Quality varies by deployment and still reflects on us.** A member running it against a weak
  model with a thin exemplar pool will get poor output and will reasonably associate that with
  SNOMED International.
- **Support burden does not disappear** — it converts into issues, questions, and forks.
- **We lose the cross-member learning** unless members choose to contribute rulings back.

### Option B — Hosted service, customer supplies their own API keys

We host and operate the pipeline; the customer configures their own model endpoints and keys.

**For**

- No model billing, credit risk, or cost exposure for us.
- The customer chooses which vendor sees their content and holds that contract directly.
- We still see usage patterns and can improve the shared pipeline.

**Against**

- **It carries the hosting liability without the revenue.** We operate, support, and take
  availability obligations, but the economics stay thin.
- **It does not solve data residency.** Terms still pass through our infrastructure, so members
  with hard residency constraints are not served by this — they need Option A. This is the flaw
  that most weakens B as a standalone offer.
- **Support becomes ambiguous.** "Is this our pipeline or your endpoint?" is an expensive question
  to answer repeatedly, especially across model vendors we do not control.
- Customer procurement burden: they need their own vendor relationship before they can start.

### Option C — Hosted service, our endpoints, usage billed

We host, we hold the model contracts, we meter and bill.

**For**

- **Simplest possible adoption.** A member with no ML infrastructure can start immediately. For
  most members this is the difference between adopting and not.
- **Volume leverage.** We can negotiate rates no single member could, and pass on or retain margin.
- **Consistent, measurable quality** across members, because everyone runs the same configuration.
- **Central learning.** With permission, rulings from one language's expert review can improve the
  shared rule and prompt machinery for everyone. This is the strongest strategic argument for
  centralising, and the one most worth deliberate governance.

**Against**

- **We become a data processor** for clinical terminology, with the contractual, DPA, and
  jurisdictional obligations that follow.
- **Cost volatility.** Model pricing changes under us; we would be quoting against a moving input
  cost. Mitigate with a local open-weight model for the bulk pass (see §4).
- **Vendor concentration risk** and terms-of-service exposure — commercial model providers'
  terms are not written with health terminology in mind.
- **Requires a commercial function** — metering, invoicing, credit control, support SLAs — that
  may not exist today.

---

## 3. Recommendation: open core, with a managed service on top

These options are not exclusive, and the sequencing matters more than the choice.

1. **Open-source the engine and plugins (A) as the foundation.** It is the only option that serves
   residency-constrained members, it matches our institutional role, and the codebase is already
   structured for it.
2. **Offer the managed service (C) for members who want to start tomorrow.** Bundle the model
   cost; do not itemise inference. Members are not equipped to reason about token pricing and
   should not have to.
3. **Treat B as a configuration of C, not a separate product.** "Bring your own endpoint" should be
   a setting available to hosted customers who ask for it — typically those with an existing vendor
   relationship or a specific model requirement — rather than a distinct tier with its own
   pricing, contract, and support pathway.

What we should charge for is **curation and assurance**, not compute: the maintained rule sets, the
QA gates, the reviewer packaging, provenance suitable for audit, and the expert-review loop. That
is where the durable value is, it is defensible as models commoditise, and it is honest about what
the system does.

---

## 4. Cost shape (relevant to any pricing decision)

The production configuration uses a **confidence-routed cascade**: a local open-weight model
samples each concept several times; only concepts where those samples disagree are escalated to a
frontier model. On a recent 5,012-concept batch this escalated roughly 45% of concepts.

Consequences:

- The **bulk pass can run on self-hosted open-weight models**, so the marginal cost of the largest
  component is infrastructure, not per-token fees. This materially de-risks Option C's cost
  volatility and is worth preserving as a design constraint.
- Cost scales with **concept count and escalation rate**, and escalation rate is a function of how
  well the language is supported — a mature language with a good exemplar pool is cheaper per
  concept as well as better.
- The QA and repair passes are cheap; several detectors involve no model call at all.

---

## 5. Two constraints that shape everything

### 5.1 Licensing and ownership

This needs a definitive answer from our legal function before any offer is made, and it may
constrain the options more than the technical considerations do:

- The **bilingual exemplar pool** — existing national translations — is the single biggest
  determinant of quality. These are frequently owned or licensed by national release centres. Who
  may use them, and whether a pool contributed by one member may improve output for another, is a
  governance question, not a technical one.
- **Ownership of generated translations**, and their status if a member later contributes them
  back as an extension.
- **Whether terminology content may be sent to third-party model providers**, and under what terms.
  This alone may make Option A mandatory for some members.

### 5.2 The cold-start problem

Quality depends heavily on retrieval from existing translated pairs. A language with a substantial
existing extension gets markedly better results than one starting from nothing. Any offer must be
honest about this, and pricing should probably reflect it — a greenfield language needs more expert
review, not less, and the early rounds are where expert effort is most concentrated.

---

## 6. Decisions needed, in order

1. **Legal position on exemplar pools and generated content** (§5.1). Blocks everything else.
2. **Do we accept data-processor obligations?** If not, Option C is off the table and A is the
   whole offer.
3. **Is there an appetite to run a commercial function** — metering, billing, support SLAs?
4. **What licence** for the open-source component, and what governance for contributed language
   plugins.
5. **What quality claim we are willing to publish.** We have measured numbers on adjudicated data;
   we should publish them with their limitations rather than let adopters infer better.

---

## 7. Suggested next step

Run one member country end-to-end as a pilot under Option C, with a second evaluating Option A in
parallel, and compare the *total* effort — including expert review time, which dominates. That
answers the pricing question with evidence rather than estimate, and would surface the licensing
questions in a concrete case rather than in the abstract.

---

### Appendix — what an adopter needs under each option

| | A: self-hosted | B: hosted, own keys | C: hosted, managed |
|---|---|---|---|
| Infrastructure | Vector DB, embedding model, GPU or API budget | None | None |
| Model contract | Their own | Their own | Ours |
| SNOMED RF2 release | Their own licensed copy | Their own licensed copy | Their own licensed copy |
| Bilingual exemplar pool | Theirs to supply and curate | Theirs to supply | Theirs to supply |
| Clinical expert time | Substantial, unavoidable | Substantial, unavoidable | Substantial, unavoidable |
| Data leaves jurisdiction | No | Yes (to us and their vendor) | Yes (to us and our vendor) |
| Setup effort | ~1 engineer-week | Low | Low |

Expert review time is the largest cost in every column, and it is the one the system is designed to
reduce. That should be the headline of whatever we offer.
