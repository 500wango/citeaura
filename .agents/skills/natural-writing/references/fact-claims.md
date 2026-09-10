# Product-Fact Claim Audit

Use this reference when prose contains statements about a real product, company, customer, internal implementation, performance result, credential, or operational practice. For technical, SEO/GEO, benchmark, and platform precision rules, cross-reference `references/evidence-gate.md`.

## High-Risk Claim Forms

Treat these constructions as claims that require explicit source identity or verification before publication:

- "We use..."
- "Our default is..."
- "Our API..."
- "We store..."
- "Our customers..."
- "At [Company]..."
- "The system automatically..."
- "Customers typically see..."
- "We process X per day/month..."
- named internal endpoints, directories, schemas, architecture, or sampling parameters;
- named employee titles, credentials, biographies, customer counts, revenue, performance, accuracy, savings, or adoption metrics.

Equivalent Chinese patterns include:

- “我们使用……”
- “默认……”
- “我们的 API……”
- “我们会保存……”
- “我们的客户……”
- “在某公司内部……”
- “通常可以提升/降低……”

## Preserving Source Identity for Product Facts

Product-defined scores, thresholds, defaults, internal benchmarks, customer outcomes, and performance statistics must explicitly preserve their source identity:

- **Bad (Asserted as external standard)**: *"85 is the citation-readiness threshold."*
- **Better (Product-defined)**: *"CiteAura uses 85/100 as a high-readiness threshold in its scoring model."*
- **Bad (Asserted as universal fact)**: *"Pages update in AI search within 24–72 hours."*
- **Better (If measured)**: *"In our test cohort, we observed changes within 24–72 hours."*
- **Better (If heuristic)**: *"Re-check over several days rather than assuming immediate propagation."*

Never present a product-defined heuristic, category, or metric as an independent industry standard.

## Rewrite Behavior

For rewrite-only tasks:
- preserve supported-looking first-party claims as source claims;
- do not intensify them;
- do not add implementation detail, metrics, customers, credentials, or causal certainty;
- do not disguise uncertainty through smoother prose;
- do not insert "fact-check" comments into the finished copy unless the user requested them.

## Review Behavior

For diagnosis, editorial review, or publication-readiness tasks:
- flag claims that materially affect credibility and cannot be established from the supplied text;
- label them `FACT-CHECK`;
- quote or identify the smallest relevant claim;
- state what should be verified: product behavior, metric source, employee credential, implementation detail, customer evidence, date, or attribution.

Do not claim a statement is false merely because it is unverified.

## Evidence Hierarchy

When verification is part of the user's request, prefer evidence in this order (see `references/evidence-gate.md`):
1. user-provided primary documentation or source material;
2. official product/company documentation;
3. primary public sources;
4. reputable secondary sources.

Keep verification separate from stylistic rewriting so an uncertain fact does not silently become a stylistic choice.
