# Regression Benchmark

Use this reference when changing the skill or evaluating a family of outputs. The purpose is to prevent one fix from causing regressions elsewhere.

## Required Benchmark Families

### A. Existing strong technical article
Expected behavior:
- mostly KEEP / Light;
- preserve formulas, code, tables, and useful checklists;
- do not rewrite for visible change;
- flag product facts separately when review is requested.

### B. Existing over-produced AI draft
Expected behavior:
- Editorial or Strong only where justified;
- reduce verdict stacking, redundant explanation, and repeated section templates;
- preserve information and claim strength.

### C. New diagnostic blog article
Expected behavior:
- answer the reader's core diagnostic question;
- avoid giving every cause the same `diagnosis → fix → verification` treatment unless functionally necessary;
- stop after sufficient coverage;
- do not auto-add FAQ/checklist/sources/CTA.

### D. New technical SEO/GEO article
Expected behavior:
- explain the central mechanism and actionable path;
- distinguish article content from docs/reference content;
- avoid exhaustive server variants, schemas, CI flows, and edge cases unless explicitly requested;
- separate adjacent search intents rather than collapsing them into one page.

### E. Explicit documentation or technical specification
Expected behavior:
- preserve systematic structure and completeness when the genre requires it;
- do not de-structure schemas, state machines, acceptance criteria, or reference tables merely to look human;
- humanize only narrative prose where useful.

### F. Same-brand corpus
Expected behavior:
- coherent editorial standard without identical outline fingerprints;
- no repeated `framework → implementation → checklist → FAQ → sources → CTA` architecture across unrelated pieces;
- no fake author-personality differentiation without samples;
- no arbitrary relocation of FAQ, Sources, CTA, or other modules merely to create visible variety;
- when a repeated module is weak, prefer omit → integrate → conventional keep → justified relocate, in that order.

### G. Corpus with legitimate structural similarity
Expected behavior:
- preserve conventional placement when reader function or genre justifies it;
- allow several articles to end with Sources, limitations, or another conventional module when that is editorially natural;
- distinguish legitimate consistency from a hidden outline template;
- do not make the corpus worse by manufacturing unusual section order.

### H. Batch of 10–20 related articles (V5.2)
Expected behavior:
- coherent editorial standard across the entire batch;
- meaningful structural variation driven strictly by each piece's reader task;
- no dominant non-functional article skeleton across the series;
- FAQ, checklist, key-takeaways, comparison tables, and CTA modules are selective rather than universally present;
- no random module relocation merely for superficial diversity;
- batch amplification protection prevents unverified thresholds from propagating into "industry standards."

### I. Precision-heavy SEO/GEO article (V5.2)
Include candidate claims such as:
- 40-word answer blocks;
- 85/100 threshold;
- 24–72 hour propagation window;
- 3× extraction improvement;
- DR ≥ 30 directory filter.
Expected behavior:
- each claim is internally classified into its evidence class (OFFICIAL, MEASURED, PRODUCT-DEFINED, ILLUSTRATIVE, HEURISTIC);
- product heuristics and scoring rules are explicitly labeled as product-defined;
- unsupported precision is removed, softened to qualitative clarity, or verified;
- walkthrough numbers are labeled illustrative.

### J. Fresh platform / crawler article (V5.2)
Include claims about Google, OpenAI, Perplexity, Gemini, Anthropic, crawler names, robots behavior, schema support, or AI-search behavior.
Expected behavior:
- current official vendor documentation and standards preferred where available;
- no stale crawler taxonomy or obsolete bot user-agent rules;
- no unsupported "platform prefers X" assertions without evidence;
- real uncertainty retained where vendor documentation is incomplete.

### K. Single strong existing article (V5.2 Non-Regression)
Expected behavior:
- ensure new batch and evidence rules do NOT cause unnecessary rewriting, hesitation, vagueness, or web research when editing a single strong standalone article with no batch or precision risk.

### L. Link inaccessible to automated tool (V5.2.1)
Scenario:
- A source URL returns 403, a redirect failure, or cannot be fetched by the current automated tool, while it may still function normally in a user browser.
Expected behavior:
- do not diagnose the URL or target site as broken or 404 without authoritative verification;
- distinguish bot protection (WAF 403), unfollowed redirects, stale cache, and unknown tool limitations;
- accurately report tool limitations rather than asserting external real-world failures.

### M. Plausible proprietary mechanism (V5.2.1)
Input includes claims such as:
- “Gemini scores passages by factual density.”
- “Perplexity is optimized for SSR.”
- “The response came from base training weights.”
Expected behavior:
- demand OFFICIAL vendor documentation or MEASURED empirical benchmarks before stating mechanisms as facts;
- otherwise describe observable behavior, engineering risks, heuristics, or explicitly labeled working hypotheses;
- do not preserve confident mechanism speculation merely because it sounds technically reasonable.

### N. Mature article after several revisions (V5.2.1)
Input is already publication-ready and contains no BLOCKER or MATERIAL issues.
Expected behavior:
- KEEP most of the article;
- make only clearly justified local changes;
- do not recommend another whole-document rewrite pass;
- explicitly apply the stopping rule once only OPTIONAL or PREFERENCE-level items remain.

## Evaluation Dimensions

For each case, judge:

1. factual / semantic fidelity;
2. usefulness;
3. correct genre boundary;
4. authorial selection;
5. macro-structure naturalness;
6. sentence/paragraph rhythm;
7. functional repetition;
8. over-humanization;
9. product-fact safety;
10. evidence identity & precision proportionality (V5.2);
11. platform freshness & claim source identity (V5.2);
12. cross-piece structural diversity & batch architecture (V5.2);
13. unverified mechanism gate & verification result integrity (V5.2.1);
14. post-fix maturity classification & stopping discipline (V5.2.1);
15. absence of forced asymmetry or arbitrary module relocation.

## Regression Rule

Do not keep a new instruction merely because it improves one case. Keep it only if it improves representative Create and Rewrite cases without material regressions in accuracy, usefulness, genre fit, or naturalness.
