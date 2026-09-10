# Quality Parity Gate

Use the same gate for newly created content and rewritten content. The input path may differ; the publication standard does not.

## 1. Claim Integrity

Check semantic-strength drift:

- may → will
- can → does
- helps → guarantees
- some → most/all
- associated with → caused by
- example → actual implementation
- recommendation → requirement
- estimate → measured result

Reject unsupported strengthening or weakening.

## 2. Evidence Identity & Precision Proportionality

Cross-reference `references/evidence-gate.md`:

- **Evidence Identity**: Material precise quantitative claims (scores, percentages, latencies, word counts, multiplier improvements) must be classified as OFFICIAL, MEASURED, PRODUCT-DEFINED, ILLUSTRATIVE, or HEURISTIC. Remove or flag UNSUPPORTED precision.
- **Precision Proportionality**: The precision of wording must not exceed the precision of the evidence. Prefer qualitative clarity over invented numbers.
- **Source Ownership**: Product-defined metrics (e.g., scoring thresholds) must explicitly state product ownership and never be framed as universal external standards.

## 3. Unverified Mechanism & Tool-Verification Integrity

- **Unverified Mechanism Gate**: Technical plausibility is not evidence of internal implementation. Do not assert unconfirmed internal scoring, chunking, crawling, or ranking mechanisms of named AI models or search engines as fact. Use observable behavior, engineering risks, or clearly labeled heuristics instead.
- **Verification Result ≠ Fact Result**: Tool-access failures (e.g., HTTP 403 bot challenges, unfollowed redirects, stale search cache snapshots) must not be converted into factual diagnoses that a page or URL is broken, dead, or outdated. Report tool limitations accurately.

## 4. Platform Freshness

For claims involving search engines, crawlers, AI models, and APIs:

- Current platform, crawler, API, or search behavior must not be asserted from stale assumptions when current verification is materially required and available.
- Where vendor documentation is incomplete or changing, preserve real uncertainty rather than inventing rules.

## 5. Structure Audit

Check that structure follows content rather than a default template.

Warning signs:

- adjacent sections repeat the same internal sequence;
- every section has definition + example + action + takeaway;
- every candidate subtopic becomes a section;
- FAQ/checklist/TL;DR/case study/decision tree are all present without separate reader jobs;
- every section has similar length and depth.

## 6. Authorial-Selection Audit

Ask:

- What was intentionally emphasized?
- What was intentionally omitted?
- What was left implicit?
- What was linked out or separated?
- Which examples earned their space?

If the answer is “everything relevant was included,” revisit the plan.

## 7. Sufficiency / Stopping Audit

The piece should stop when the primary reader task is satisfied.

Reject late sections that mainly add completeness, edge-case coverage, or conventional article modules without improving the reader's outcome.

## 8. Publication-Boundary Audit

For technical or SEO/GEO content, check whether the article has absorbed material better suited to docs, reference, specification, or a separate article (`references/publication-boundary.md`).

Do not reduce explicit documentation or specification tasks merely because they are comprehensive.

## 9. Voice Consistency

Check whole-document consistency for:

- register;
- point of view;
- terminology;
- certainty level;
- heading style;
- evidence style;
- sentence density.

Local improvements must not create a different author in one section.

## 10. Rhythm Audit

Look for both model uniformity and fake irregularity.

Reject:

- nearly identical sentence lengths across many paragraphs;
- repetitive punch-line endings;
- deliberate fragment spam;
- arbitrary one-line paragraphs;
- excessive rhetorical questions;
- punctuation tricks used to simulate voice.

## 11. Repetition Audit

Keep functional repetition only when it serves a different task such as navigation, scanning, search intent, compliance, execution, or summary.

Compress rhetorical repetition.

## 12. Over-Humanization Audit

Reject fake texture:

- invented personal experience;
- invented customers or mistakes;
- slang inconsistent with genre;
- unnecessary humor;
- fake conversational hooks;
- excessive dashes/ellipses/fragments;
- reduced precision.

## 13. Corpus Fingerprint & Batch Architecture Audit

When related pieces are available (see `references/corpus-diversity.md` and `references/batch-generation.md`):

- **Batch Architecture Check**: For batches of 3+ (and especially 5+) pieces, verify that individual pieces do not aggregate into an accidental dominant outline template.
- Reject unjustified repetition such as the same framework opening, section sequence, checklist/FAQ ending, or docs-like completeness across unrelated pieces.
- Reject **forced diversity**: moving FAQ, Sources, CTA, limitations, or other modules to odd positions solely to break a repeated pattern. Prefer omission, integration, or a conventional placement with a real reader function.
- Do not invent diversity or author personality simply to pass this check. Natural structural similarity is acceptable when topic, genre, or reader flow justifies it.

## 14. Product-Fact Audit

For claims such as `we use`, `our default`, `our API`, `we store`, `our customers`, performance claims, credentials, pricing, or internal process, preserve wording strength and flag for verification when diagnosis/publication-readiness is requested (`references/fact-claims.md`).

## 15. Post-Fix Stopping Rule & Maturity Assessment

After an edit or revision pass, classify all remaining candidate changes by severity:

### Severity Classes:
- **BLOCKER**: Factual error, materially misleading claim, unsupported high-impact assertion, incorrect evidence identity, broken reader task, or significant structural failure.
- **MATERIAL**: Meaningful clarity problem, significant redundancy, important structural weakness, substantial credibility issue, obvious corpus/template fingerprint, or materially unnatural prose.
- **OPTIONAL**: Small wording improvement, minor rhythm preference, technically smoother transition, low-impact precision improvement, or nonessential structural polish.
- **PREFERENCE**: Alternative valid phrasing, personal stylistic taste, equally good heading variant, or change with no meaningful reader benefit.

### Hard Stopping Rule:
**If no BLOCKER or MATERIAL issue remains: STOP.**

Do not recommend or execute another whole-document Natural Writing pass simply because OPTIONAL or PREFERENCE-level changes still exist.

For mature drafts:
- Prefer targeted, local fixes over broad rewrites.
- Preserve already strong passages intact.
- Do not repeatedly "humanize" or churn sentences.
- Do not manufacture new problems to justify another pass.
- Do not lower technical density or precision merely to create stylistic variation.

## Pass Condition

Creation and rewrite outputs should be indistinguishable in editorial quality when given equivalent source information. Neither path receives a lower standard because it started from a blank page or from a draft. When only OPTIONAL or PREFERENCE items remain, the artifact is considered complete.
