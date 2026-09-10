# AI-writing Signals

Use this checklist diagnostically, not mechanically. A feature is not bad merely because models often use it; flag it only when it makes the specific text more generic, repetitive, over-structured, or less credible.

## Structural signals

- Generic opening that delays the actual claim.
- Every section follows the same internal pattern.
- **Synthetic completeness**: the piece tries to cover every definition, caveat, edge case, warning, takeaway, FAQ, and conclusion even when the reader does not need all of them.
- Paragraphs have suspiciously uniform length.
- Repeated three-part lists without semantic need.
- Conclusion restates the introduction rather than adding a decision or implication.
- Excessive headings for a short piece.
- One-sentence bridge paragraphs whose only job is to announce the next section.

## Sentence-level signals

- Repeated transition scaffolding: “首先/其次/此外/最后”, “firstly/moreover/furthermore/in conclusion”.
- Excessive balanced constructions: “不仅……而且……”, “not only…but also…”.
- Repeated sentence openings or syntactic templates.
- Uniform medium-length sentences with few natural short or long deviations.
- Unnecessary explanation after an already clear statement.
- Parenthetical clarification of obvious points.
- **Verdict stacking**: many consecutive sentences framed as maxims, warnings, or categorical verdicts.
- **Command stacking**: repeated “Never”, “Do not”, “Rule:”, “必须”, “不要”, or “切勿” where one explanation would suffice.
- **Quotable-line saturation**: too many sentences seem engineered to stand alone as punchy aphorisms.

## Lexical signals

- Empty intensifiers: 显著、极大、至关重要、全面、强大、无缝; significant, crucial, robust, seamless, comprehensive.
- Abstract nouns instead of direct verbs: “实现对效率的提升” versus “提高效率”.
- Generic business phrases that could describe any product: “赋能用户”, “unlock potential”, “streamline workflows”.
- Decorative adjectives unsupported by evidence.
- Synonym cycling that makes prose less precise.

## Rhetorical signals

- Explaining both sides when the task calls for a decision.
- Repeated reassurance or throat-clearing before making a point.
- Treating obvious implications as separate insights.
- Artificially polished symmetry that suppresses emphasis.
- Generic future-facing ending with no concrete next step.
- **Uniform certainty**: every claim has the same maximal confidence despite differing evidence quality.
- **Perfectly convenient examples**: examples fit the immediately preceding rule too neatly and add no independent realism or complexity.
- **Exhaustive edge-case coverage**: a normal article behaves like a specification or test suite without a reader need for that coverage.

## Repetition test

Before removing repeated content, determine whether it is:
- rhetorical repetition with no new function; or
- functional repetition serving FAQ retrieval, checklist execution, summary scanning, definitions, compliance, navigation, or SEO/GEO intent.

Only the first category is presumptively removable.

## Correction hierarchy

Fix in this order:
1. Delete low-value material.
2. Merge duplicated ideas.
3. Reorder around the strongest point.
4. Rebuild weak sentences.
5. Replace abstract or inflated wording.
6. Adjust rhythm and punctuation.
7. Only then consider individual synonym changes.

Do not manufacture irregularity for its own sake. After correction, run the Over-Humanization Check in the main skill.

## Corpus-level and publication-boundary signals

These signals matter mainly for Create workflows and multi-article review:

- **Outline fingerprint repetition**: multiple related articles reuse the same opening move, section sequence, module order, and ending despite different reader tasks.
- **Blog-to-docs drift**: an article keeps expanding into exhaustive implementation, deployment, compatibility, schema, or edge-case reference material without an explicit documentation purpose.
- **Failure to stop**: the piece already answers the primary question but continues adding relevant modules for completeness.
- **Byline sameness**: different named authors produce nearly identical architecture and rhythm. Treat this as a corpus signal, but do not invent personalities to correct it.
- **Module accretion**: framework + code + table + case study + checklist + decision tree + FAQ + sources + CTA accumulate because each is individually relevant, not because each earns a distinct reader function.

Correction should come from scope, selection, publication boundary, and topic-led architecture—not random stylistic variation.
