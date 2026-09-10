# Publication Boundary

Use this guide when a blog, SEO/GEO article, technical article, or thought-leadership piece starts expanding into documentation or reference material.

## Core question

What publication surface best serves this information?

Classify candidate material:

### ARTICLE
Keep when the information is necessary to understand the thesis, make the decision, or complete the article's primary task.

### SUPPORTING EXAMPLE
Keep a limited example when it clarifies the mechanism or shows application. Do not turn one example into a full tutorial unless the tutorial is the article's purpose.

### DOCS
Move out of the article when the material is implementation detail that users will need to maintain, look up, copy, configure, or follow operationally. Examples include full deployment recipes, exhaustive configuration steps, long API setup flows, and environment-specific procedures.

### REFERENCE
Move out when the value comes from completeness rather than narrative understanding. Examples include exhaustive rule matrices, full schemas, long compatibility lists, every edge case, or all possible error conditions.

### SEPARATE ARTICLE
Separate when the material has its own search intent or reader question and would distort the current article if fully developed.

## Blog-vs-docs test

A blog article is drifting toward docs when several are true:

- it enumerates many implementation variants;
- it contains a complete validation or deployment suite unrelated to the core thesis;
- every edge case gets a subsection;
- examples become production-ready reference material;
- the reader must maintain the information over time;
- the article becomes useful mainly as something to look up rather than something to read through.

If comprehensive reference is explicitly the requested genre, do not apply this reduction.

## Link-out rule

When a real destination exists, summarize the point and link out instead of duplicating the full material.

When no destination exists, do not invent a link or pretend documentation exists. Either summarize the necessary part or omit the material.

## Boundary failure patterns

- `blog + docs + reference manual + product specification` in one page;
- technical SEO article that explains the core issue, then also includes every web-server configuration, full CI validator, log-analysis flow, all related crawlers, FAQ, and implementation appendix;
- conceptual article that becomes a complete API tutorial because code was available.

The goal is not shorter writing by default. The goal is correct placement of information.
