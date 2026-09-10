# Evidence and Precision Gate

Use this reference for material quantitative claims and current technical/platform behavior, especially in SEO, GEO, AI-search, product, benchmark, and platform-specific content. Do not invoke external research for ordinary prose that carries no meaningful precision or freshness risk.

## Trigger claims

Apply the gate to percentages, ratios, scores, thresholds, response or refresh times, indexing/crawl windows, word/token recommendations, performance or ranking improvements, market prices, recommended minimums, crawler/search/model/API behavior, and statements such as “Google requires,” “ChatGPT prefers,” or “AI systems use.”

## Evidence identities

Classify material claims internally:

### OFFICIAL

Supported by current first-party documentation, a specification, standard, or authoritative primary source. State it as fact only within that source's scope and preserve version/date qualifications.

### MEASURED

Supported by a real experiment, dataset, customer study, benchmark, or reproducible observation available to the writer. State the measurement context and do not generalize beyond it: “In our 120-page test set...” is not “AI systems always...”

### PRODUCT-DEFINED

A threshold, score, category, weighting, workflow, or convention defined by the product or organization. State ownership: “CiteAura treats 85/100 as...” rather than “85 is the industry threshold.”

### ILLUSTRATIVE

A number or scenario used to demonstrate a calculation, workflow, or concept. Mark it as an example and do not imply a production result.

### HEURISTIC

A practical recommendation without universal empirical status. Signal that identity with wording such as “A useful starting point is...,” “As a rule of thumb...,” “We generally recommend...,” or “Test this against your own pages.”

### UNSUPPORTED

Specific or authoritative-looking material without adequate source, measurement, product definition, or justified heuristic basis. Do not publish it as fact. Remove the precision, soften to a defensible qualitative statement, flag for verification, or research it when the task and environment permit.

Evidence classes are internal controls. Expose them only for diagnosis, fact-check flags, editorial notes, or source rationale.

## Unsupported precision rule

Numbers create an evidence burden. Values such as `40–60 words`, `200–500 tokens`, `<10%`, `85/100`, `24–72 hours`, `3–14 days`, `3× better`, `DR ≥30`, or `30 requests/minute` must have an evidence identity.

Prefer qualitative precision over invented numeric precision:

- Unsupported: “Keep answer blocks under 75 words because AI systems extract them more reliably.”
- Defensible qualitative version: “Keep answer blocks concise and self-contained so the main answer is easy to identify and extract.”
- Product/editorial heuristic: “We use 75 words as a practical starting point, not a platform requirement.”

This is not a ban on numbers. Supported precision is useful; unsupported precision is false authority.

## Verification Result ≠ Fact Result

Strengthen evidence evaluation by distinguishing tool access limitations from real-world states. **Tool-access failure is not automatically evidence of a real-world failure.**

Classify verification findings internally:

- **VERIFIED-LIVE**: Directly verified against live origin response headers and rendered content.
- **VERIFIED-REDIRECT**: Successfully verified to resolve via a canonical redirect chain to an active destination.
- **BOT-BLOCKED**: The automated request was rejected by WAF/CDN protection (e.g., HTTP 403, Cloudflare challenge); the page may remain fully functional for real users and standard browsers.
- **STALE-CACHE**: The information originates from an older search index or cached snapshot rather than live origin verification.
- **UNVERIFIED**: The available tool or environment could not complete verification.
- **VERIFIED-BROKEN**: Confirmed unreachable, removed, or returning persistent error status (e.g., 404, 410, 500) under authoritative testing.

### Core Verification Rules:

1. **Never convert tool limitations into factual website diagnoses.** Do not label a public URL, page, document, or resource as *broken*, *dead*, *404*, *unavailable*, *not updated*, or *removed* unless that condition itself has been reliably verified.
2. **HTTP 403 / Bot Challenge ≠ Dead Page:** HTTP 403 frequently indicates automated client blocking or WAF rules rather than a broken or nonexistent page.
3. **Unfollowed Redirect ≠ Broken Link:** A redirect that a specific automated tool cannot follow does not constitute a broken link.
4. **Tool Fetch Failure ≠ Browser Failure:** An automated scraper or search tool failure is not proof that a standard desktop or mobile browser cannot access the resource.
5. **Stale Cache ≠ Stale Origin:** A stale search index or cached snippet is not proof that production content on the target site is outdated.
6. **Search Snippet ≠ Origin Fetch:** A search-result summary or synthesized snippet must never be treated as equivalent to an origin HTTP fetch.

When verification is uncertain, describe the tool reality accurately:
- *"The current retrieval tool could not verify this URL."*
- *"The request was blocked for automated access."*
- *"The available index may be stale."*
- *"I cannot confirm whether the link is broken from this result alone."*

Do not silently convert these into asserted real-world failures.

## Unverified Mechanism Gate

Apply this gate whenever writing about the internal behavior of a named:
- AI model (e.g., GPT-4, Claude, Gemini, DeepSeek)
- search engine or AI search engine (e.g., Google Search, Perplexity, ChatGPT Search)
- retrieval or indexing system (e.g., RAG pipelines, passage extractors)
- crawler (e.g., Googlebot, OAI-SearchBot, Claude-SearchBot, PerplexityBot)
- ranking, scoring, recommendation, or backend API system

### Core Rule:
**Technical plausibility is not evidence of internal implementation.** Do NOT state an inferred internal mechanism as fact merely because it sounds technically reasonable or architecturally plausible.

### Risky Language Patterns (Unverified Mechanism Flags):
- *"Gemini scores passages by factual density."*
- *"Perplexity's fetcher is optimized for server-rendered HTML."*
- *"The answer came from base training weights."*
- *"AI search systems split pages into 200–500 token chunks."*
- *"This crawler prefers..."*
- *"The ranking system penalizes..."*
- *"The model verifies..."*

Unless supported by OFFICIAL vendor specifications or MEASURED empirical benchmarks, do not assert these as facts.

### Fallback Order for Unverified Implementation:
When internal implementation details are not publicly confirmed:
1. **Describe observable behavior** (what is visible in public inputs and outputs).
2. **Describe the engineering consequence or risk** (what happens if a page relies on client JS or unsemantic markup).
3. **Present the recommendation as a heuristic** (*"As a practical starting point...", "CiteAura recommends..."*).
4. **If materially useful, explicitly label the mechanism as a hypothesis** (*"One working hypothesis is..."*).
5. **Otherwise, omit the internal explanation entirely.**

### Examples:
- **Bad**: *"Perplexity's fetcher is optimized for server-rendered HTML."*
  **Better**: *"Server-rendered HTML reduces dependence on client-side execution during retrieval."*
- **Bad**: *"Gemini scores passages according to factual density."*
  **Better**: *"Clear, self-contained passages make the main claim easier for readers and retrieval systems to identify."*
- **Bad**: *"The brand mention came from the model's training weights."*
  **Better**: *"The response mentions the brand without attributing that claim to the canonical domain."*

Do not weaken documented mechanisms that are genuinely supported by official documentation. The purpose is evidence-matched precision, not generic writing.

## Claim source identity

Before finalizing, ask: **Whose fact is this?**

Valid answers include vendor, standard, measured experiment, named product/organization, author recommendation, or hypothetical example. If the answer is unknown, revise the claim.

## Platform freshness gate

Treat Google Search and AI Overviews, ChatGPT Search, OpenAI crawlers, Perplexity, Anthropic crawlers, Gemini, Bing, schema support, model APIs, and vendor-controlled crawler/search behavior as freshness-sensitive.

When current research is available and correctness materially depends on the claim, prefer:

1. current official vendor documentation;
2. official standards/specifications;
3. current primary-source technical documentation;
4. direct measurements;
5. reputable secondary evidence;
6. a clearly labelled heuristic.

If current verification is unavailable, avoid unnecessary precision, preserve uncertainty, separate stable principles from changing implementation details, and recommend verification only when material.

## Verb burden

- **requires**: actual requirement only;
- **supports**: documented capability;
- **uses**: evidence of actual behavior;
- **prefers**: explicit guidance or comparative evidence;
- **improves**: measured evidence or clearly scoped observation;
- **may help**: justified but uncertain mechanism;
- **we recommend**: editorial or product guidance, not a universal rule.

Do not convert a recommendation into an external requirement.

## Batch interaction

Before reusing a precise claim across a batch, establish its evidence identity. Repetition across pieces never upgrades support. Preserve source scope, measurement conditions, product ownership, and illustrative labels every time the claim appears.

## Pass condition

The precision of the prose does not exceed the precision of the evidence. Current claims are fresh enough for their consequence, proprietary internal mechanisms are not asserted without evidence, tool verification limits are not converted into site diagnoses, useful recommendations remain possible, and ordinary writing has not become burdened with unnecessary caveats or visible evidence labels.
