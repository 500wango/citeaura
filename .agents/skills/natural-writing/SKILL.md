---
name: natural-writing
description: Create, rewrite, or edit Chinese and English text so it reads like deliberate human writing rather than default AI prose while preserving facts, intent, useful structure, technical precision, evidence-matched precision, and genre conventions. Use when the user asks to 去AI味, humanize text, write naturally, rewrite AI-generated content, create a new article/post/report/marketing piece or multi-article series with a human voice, reduce robotic or template-like phrasing, diagnose AI-writing signals, edit overly polished prose, audit factual precision/freshness, or imitate a supplied author style. Support Create, Light, Editorial, Strong, Diagnose, Style Clone, and Batch Generation workflows with the same final quality standard.
---

# Natural Writing V5.2.1

Produce deliberate human-quality writing whether starting from a blank page or editing an existing draft. Optimize for accuracy, usefulness, editorial judgment, evidence-matched precision, natural rhythm, and genre fit. Do not optimize for AI-detector evasion.

## Core Principle: Create and Rewrite Must Converge

Treat **Create** and **Rewrite** as different input paths that must converge on the same publication standard.

- **Create**: choose what deserves space before drafting; prevent default LLM macro-structure.
- **Rewrite**: preserve what already works; intervene only where the text earns intervention.
- **Batch**: plan the corpus before drafting individual pieces; prevent aggregate template convergence.
- **Shared finish**: all paths pass the same support, evidence identity, freshness, structure, repetition, voice, rhythm, over-humanization, and fact-claim checks.

A fresh draft does not get a lower naturalness standard because there is no source text. A rewrite does not get rewritten merely to prove the skill ran. A batch does not pass if individual articles are reasonable but share an identical hidden skeleton.

## Workflow

1. Identify language, audience, genre, and task: **Create**, **Rewrite/Edit**, **Diagnose**, **Style Clone**, or **Batch Generation**.
2. When creating **3 or more related pieces** (series, batch guides, topic cluster), consult `references/batch-generation.md` before drafting individual pieces.
3. If **Create**, follow `references/creation-mode.md` before drafting.
4. If **Rewrite/Edit**, choose the least aggressive mode:
   - **Light** — local cleanup.
   - **Editorial** — selective trimming, de-templating, and structural repair for competent prose.
   - **Strong** — substantial reconstruction for genuinely weak or synthetic drafts.
5. For long-form work, build an internal map:
   - Rewrite/Edit: **KEEP / LIGHT / EDITORIAL / STRONG / MERGE-DELETE**.
   - Create: **CORE / SUPPORT / OPTIONAL / OMIT / LINK-OUT**.
6. When content contains material quantitative claims, thresholds, platform/crawler behaviors, or opaque proprietary systems, consult `references/evidence-gate.md` (including the **Unverified Mechanism Gate** and **Verification Result ≠ Fact Result** rule).
7. For freshness-sensitive platform facts (search engines, crawlers, APIs), verify current primary sources when the environment supports research and when verification materially affects correctness.
8. For technical or SEO/GEO Create tasks, run the **Publication Boundary** test in `references/publication-boundary.md` before expanding edge cases, code, schemas, or implementation detail.
9. If same-brand or same-series content is available, run the **Corpus Fingerprint Audit** in `references/corpus-diversity.md`.
10. Draft or revise structurally before reaching for synonyms.
11. Apply the **Post-Fix Stopping Rule**: once the reader's primary task is satisfied and no BLOCKER or MATERIAL issues remain, stop editing.
12. Run the shared Quality Parity Gate in `references/quality-parity.md`.
13. When first-party product, company, customer, performance, credential, or implementation claims appear, run `references/fact-claims.md`.
14. Return the finished artifact directly unless the user asks for diagnosis, rationale, intervention mapping, fact-check flags, or editorial notes.

## Non-negotiable Rules

- Preserve or respect factual claims, names, dates, numbers, citations, URLs, product details, technical terms, requirements, and intended stance.
- Never invent personal experiences, customer stories, quotations, statistics, sources, credentials, product capabilities, internal implementations, emotions, anecdotes, or author biographies to create human texture.
- Never introduce deliberate grammar mistakes, typos, slang, filler, randomness, fragments, or punctuation quirks as fake-humanization tactics.
- Never optimize for defeating AI detectors.
- Do not mechanically replace words with rarer synonyms.
- Do not reduce technical, legal, academic, or professional precision merely to sound conversational.
- Do not force asymmetry. Keep useful symmetry when it materially improves comparison, execution, comprehension, or navigation.
- Do not force completeness. Relevance alone does not earn a section.
- Do not automatically add FAQ, TL;DR, checklist, comparison table, case study, decision tree, summary, sources, CTA, “key takeaways,” or conclusion merely because articles often contain them.
- Do not remove functional repetition solely because the same concept appears in multiple surfaces.
- Preserve uncertainty and claim strength. Never silently change `may` to `will`, `can` to `does`, `helps` to `guarantees`, `some` to `most`, or an illustrative example into asserted implementation.
- Do not manufacture different personalities for different bylines. Without author samples, vary content architecture according to subject and reader task, not invented persona.
- The precision of wording must not exceed the precision of the evidence (`references/evidence-gate.md`).
- Repetition across a corpus never transforms an unverified assertion or product heuristic into an industry standard (`references/batch-generation.md`).
- Tool-access failure is not evidence of real-world resource failure (`references/evidence-gate.md`).
- Technical plausibility is not evidence of proprietary internal implementation (`references/evidence-gate.md`).

## Task Modes

### Create

Use when the user asks for new prose from a topic, brief, notes, research, outline, keywords, or source material.

Before drafting:
1. Define the **editorial thesis**: what the piece is actually trying to establish, explain, persuade, or help the reader do.
2. Identify the **primary reader task** and the 1–2 ideas worth the most space.
3. Decide what a competent reader can infer without explanation.
4. Decide which edge cases, implementation details, or adjacent topics do not deserve space here (`references/publication-boundary.md`).
5. Classify material precise claims into their evidence classes (`references/evidence-gate.md`).
6. Build a selective plan rather than an exhaustive topic map.
7. Vary section shape according to content function; do not give every section the same rhetorical skeleton.
8. If generating a series or batch (3+ pieces), plan the corpus matrix first (`references/batch-generation.md`).
9. Stop planning when the reader can complete the primary task without omitted material.

Then draft and run the same quality checks used for rewrites. See `references/creation-mode.md`.

### Light

Use for already natural prose, precision-sensitive text, or explicit minimal edits.
- Remove obvious boilerplate, awkward transitions, duplicate wording, inflated phrasing, or local rhythm problems.
- Keep paragraph order, examples, headings, and most wording intact.
- Prefer no change when a sentence is already strong.

### Editorial

Use for competent, professional, technical, published, or near-final prose that feels over-produced, over-complete, too uniformly polished, or mildly model-like.
- Trim genuine redundancy or over-explanation; do not chase a quota.
- Merge repeated conclusions or serial warnings.
- Reduce verdict density while preserving real requirements.
- Vary rhetorical shape where several sections repeat the same template.
- Keep useful headings, code, tables, formulas, schemas, checklists, FAQs, and procedures.
- Prefer local repair over whole-document reconstruction.
- Preserve the author's register.

### Strong

Use only when the draft is genuinely generic, repetitive, padded, synthetic, or structurally weak, or when explicitly requested.
- Reorder around the strongest idea.
- Merge thin sections and split overloaded ones.
- Replace generic framing with concrete claims.
- Remove explanation competent readers can infer.
- Let important sentences be short without manufacturing fragments.
- Keep technical artifacts unchanged unless simplification is requested.
- Break repeated verdict cadence, command stacking, and mechanically repeated section templates.

### Diagnose

Identify only patterns actually present:
- **Pattern** — point to specific wording or structure.
- **Impact** — clarity, rhythm, credibility, voice, concision, or usefulness.
- **Fix** — structural correction, not synonym swapping.
- **Intervention** — KEEP, LIGHT, EDITORIAL, STRONG, or MERGE-DELETE.
- **Evidence / Fact Flags** — label unverified material claims as `FACT-CHECK` (`references/fact-claims.md` and `references/evidence-gate.md`).

### Style Clone

When the user supplies at least 2 representative samples and asks to match them, consult `references/style-clone.md`. Infer observable stylistic features (rhythm, paragraph density, register, directness, hedging, transition habits, evidence style). Do not infer personal demographics or psychology.

## Creation & Batch Editorial Controls

### Authorial Selection
A human-feeling piece demonstrates deliberate selection, not exhaustive encyclopedic coverage:
- **CORE** — necessary to fulfill reader intent.
- **SUPPORT** — adds evidence, mechanism, contrast, or useful detail.
- **OPTIONAL** — relevant but not necessary (do not promote automatically).
- **OMIT** — related but weakens focus.
- **LINK-OUT** — useful but better handled in docs or sibling articles.

### Sufficiency and Stopping Rule
Continue only while new material materially improves the reader's outcome, mechanism understanding, or error prevention. Stop adding material when the next section is merely conventional or exhaustive. The ability to keep writing is not a reason to keep writing.

### Completeness Budget
Treat unexplained completeness as a warning signal. If a draft contains many modules simultaneously (framework, examples, code, tables, case study, checklist, decision tree, FAQ, sources, CTA, summary), verify each has a distinct reader job. Remove or integrate modules that exist only because "good articles usually have them."

### Publication Boundary
Classify technical material before drafting: **ARTICLE**, **SUPPORTING EXAMPLE**, **DOCS**, **REFERENCE**, or **SEPARATE ARTICLE**. A blog post should not become documentation merely because the model can enumerate every edge case. See `references/publication-boundary.md`.

### Section Shape Diversity
Let content function determine section structure (mechanism explanation, short diagnosis, worked example, comparison, procedure, limitation, counterexample, concise rule, or link-out). Avoid repeating the same internal rhetorical template across adjacent sections.

### Information Weighting
Do not equalize subsection length or detail for visual symmetry. Allocate space proportional to significance. Compress obvious material.

### Corpus Fingerprint & Batch Architecture
When generating 3+ pieces or working near an existing corpus:
- Compare observable architecture against nearby pieces (`references/corpus-diversity.md`).
- For 5+ piece batches, run the **Batch Fingerprint Hard Gate** (`references/batch-generation.md`) to catch systemic sameness (e.g., universal FAQ, identical scaffolding, identical heading grammar).
- Resolve repeated modules using the priority order: **OMIT → INTEGRATE → KEEP → RELOCATE**.
- Natural structural similarity is preferable to artificial diversity. Do not move modules to bizarre locations solely to look different.

## Evidence & Precision Controls

Cross-reference `references/evidence-gate.md`:

### The Six Evidence Classes
1. **OFFICIAL**: Supported by current vendor docs, specs, RFCs, or primary standards.
2. **MEASURED**: Supported by real experiments, benchmarks, or datasets (state context; do not over-generalize).
3. **PRODUCT-DEFINED**: Defined by the product/org (e.g., CiteAura thresholds). Explicitly state product ownership; never present as an external industry standard.
4. **ILLUSTRATIVE**: Hypothetical or walkthrough numbers. Label clearly as examples.
5. **HEURISTIC**: Practical rules of thumb without universal empirical status. Use transparent framing ("A useful starting point is...").
6. **UNSUPPORTED**: Appears specific/authoritative without adequate support. Remove precision, soften to qualitative clarity, or verify.

### Unsupported Precision Rule
Precise numbers create an evidence burden. Prefer qualitative clarity over invented numbers when evidence is unavailable.

### Verification Result ≠ Fact Result
Tool-access failure is not automatically evidence of real-world failure. Classify internal verification states as **VERIFIED-LIVE**, **VERIFIED-REDIRECT**, **BOT-BLOCKED** (e.g., WAF 403), **STALE-CACHE**, **UNVERIFIED**, or **VERIFIED-BROKEN**. Never assert a URL or site is dead or 404 merely because an automated tool was blocked or an index was stale.

### Unverified Mechanism Gate
Technical plausibility is not evidence of internal implementation. Do not assert inferred internal mechanisms of named AI models, crawlers, or search engines as fact without OFFICIAL or MEASURED support. Order of preference: **Observable Behavior → Engineering Consequence / Risk → Practical Heuristic → Explicit Hypothesis → Omit**.

### Platform Freshness Gate
For rapidly changing platforms (search engines, crawlers, APIs, robots behavior), verify against current primary documentation when available. Preserve real uncertainty when vendor behavior is changing or undocumented.

### Claim Source Identity
Always answer: *"Whose fact is this?"* (Vendor, Standard, Experiment, Product, Author Heuristic, Example, or Unknown). If unknown, revise.

## Post-Fix Stopping Discipline

After an editing or revision pass, classify remaining candidate issues:
- **BLOCKER**: Factual error, material misstatement, broken reader task, or structural failure.
- **MATERIAL**: Meaningful clarity problem, significant redundancy, or major credibility issue.
- **OPTIONAL**: Minor wording or transition polish, low-impact precision touchup.
- **PREFERENCE**: Alternative phrasing, stylistic taste, or equally good heading variant.

**Hard Rule:** If no **BLOCKER** or **MATERIAL** issue remains, **STOP**. Do not recommend or perform another full-document rewrite simply because OPTIONAL or PREFERENCE-level improvements exist. For mature drafts, keep strong text intact and make only justified local edits.

## Long-form Rewrite Intervention Map

Classify meaningful blocks before editing:
- **KEEP** — already natural, precise, and useful.
- **LIGHT** — wording or rhythm cleanup only.
- **EDITORIAL** — solid content but over-explained, over-structured, or mildly model-like.
- **STRONG** — generic or structurally weak enough to justify reconstruction.
- **MERGE-DELETE** — duplicated or low-value content with no distinct function.

Prefer heterogeneous editing over uniform document-wide intensity.

## Content-Type Adaptation

- **Marketing / landing pages**: Lead with customer problems and differentiators; prefer observable behavior over slogans; audit first-party claims before strengthening them.
- **SEO / GEO / blog articles**: Search usefulness outranks template completeness; do not auto-append FAQ, checklist, or CTA; treat search terms as functional; apply Publication Boundary to crawler edge cases.
- **Technical / engineering guides**: Treat code, schemas, formulas, tables, and exact API parameters as precision-bearing artifacts; humanize prose around them; do not de-structure reference manuals.
- **Product Hunt / social / Reddit / X**: Use platform-appropriate density; prefer specific observations over announcement boilerplate; never fabricate personal backstories.
- **PRDs / reports / professional documents**: Preserve requirements, acceptance criteria, and measurable statements; remove ceremonial corporate filler; keep functional repetition that aids execution.

## Functional-Repetition Check

Distinguish:
- **Rhetorical repetition**: restates a point without adding function. Compress or delete.
- **Functional repetition**: repeats a concept because a different surface (FAQ, checklist, table, summary, search-intent block) serves a different reader task. Keep, but tighten.

## Shared Quality Parity Gate

Every Create, Rewrite, and Batch output must pass these checks (`references/quality-parity.md`):

1. **Fidelity / support** — no invented or strengthened claims; source facts preserved.
2. **Evidence identity & precision proportionality** — material precise claims are classified or softened; wording precision matches evidence precision (`references/evidence-gate.md`).
3. **Proprietary internal mechanisms** — opaque model/crawler scoring or chunking behaviors are not asserted as facts without OFFICIAL/MEASURED evidence.
4. **Tool-verification integrity** — tool-access failures (403, redirects, stale cache) are not converted into asserted site diagnoses.
5. **Platform freshness** — current search, crawler, API, and model behavior is not asserted from stale assumptions.
6. **Natural structure** — architecture reflects content and reader task, not a default article template.
7. **Authorial selection & sufficiency** — deliberate prioritization and stopping discipline when the reader task is met.
8. **Publication boundary** — blog, docs, reference, and separate-article boundaries are respected (`references/publication-boundary.md`).
9. **Rhythm & voice consistency** — no uniform cadence or manufactured irregularity; coherent register and terminology.
10. **Functional repetition** — repetition has a distinct reader job or is removed.
11. **Anti-overhumanization** — no fake anecdotes, forced fragments, slang, rhetorical questions, punctuation tricks, or reduced precision.
12. **Corpus diversity & batch architecture** — multi-piece batches pass the batch architecture check without forced module shifting (`references/batch-generation.md` & `references/corpus-diversity.md`).
13. **Product-fact safety** — first-party claims preserve their source identity and are never upgraded (`references/fact-claims.md`).
14. **Severity classification & stopping check** — remaining items classified by severity; if only OPTIONAL/PREFERENCE remain, editing stops.

## Non-Regression Rule

V5.2.1 must NOT make the skill overly cautious, generic, afraid of numbers, incapable of giving useful recommendations, dependent on web research for ordinary writing, structurally random, or full of visible evidence tags in finished prose. Evidence classes are internal reasoning controls. The goal is evidence-matched precision, not vagueness.

## Supporting References

- For detailed signal diagnosis, read [references/ai-writing-signals.md](references/ai-writing-signals.md).
- For intervention intensity, read [references/editorial-judgment.md](references/editorial-judgment.md).
- For worked transformations, read [references/examples.md](references/examples.md).
- For skill evaluation and non-regression, read [references/regression-benchmark.md](references/regression-benchmark.md).

## User Controls

Interpret these commands or natural-language equivalents:
- `Create` / `新写` / `从零写` — generate new content using Creation Mode.
- `Batch` / `批量生成` / `系列文章` — plan and generate a series using Batch Generation rules.
- `Light` / `轻度` — minimal intervention.
- `Editorial` / `编辑` / `编辑削脂` — moderate editing for competent prose.
- `Strong` / `强力` — substantial reconstruction.
- `Diagnose` / `诊断` — explain AI-writing signals.
- `Style Clone` / `模仿我的风格` — derive style from supplied samples.
- `Keep structure` / `保留结构` — do not reorder sections or paragraphs.
- `Keep length` / `保持篇幅` — stay near original length.
- `Shorter` / `精简` — cut low-value explanation aggressively.
- `Fact-check flags` / `事实核验标记` — surface claims that require verification.

If controls conflict, prioritize explicit user constraints over defaults.
