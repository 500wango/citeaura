# Corpus Fingerprint Audit

Use this guide when related articles, posts, guides, or documents are available in the conversation, workspace, or user-supplied corpus. When generating 3 or more related pieces, consult `references/batch-generation.md` before drafting.

## Goal

Prevent individually polished pieces from revealing a repeated site-wide LLM template when read together, while preserving legitimate editorial consistency and genre requirements.

Do not invent unseen corpus patterns. Do not browse merely to satisfy this audit unless the user's task already includes external research.

## Distinguishing Three Types of Corpus Patterns

The Corpus Fingerprint Audit must clearly distinguish:

1. **Legitimate editorial consistency**: shared brand voice, standard documentation navigation, consistent typography, required compliance disclosures, or shared domain terminology. This should be preserved.
2. **Accidental structure convergence**: independent pieces defaulting to the exact same hidden outline generator (e.g., summary bullets → numbered sections → checklist → FAQ → sources → CTA). This is a planning defect and must be resolved.
3. **Artificial diversity**: randomizing module placement, creating bizarre section sequences, or fabricating forced asymmetry merely to make articles look superficially different. This is an anti-pattern and must be avoided.

Do not solve batch sameness through random structure mutation.

## Build a Lightweight Fingerprint

For the current piece and 3–5 nearby pieces, compare observable architecture:

- opening move: direct claim, question, framework, definition, diagnostic result, or problem statement;
- number and depth of major sections;
- heading grammar and recurring heading prefixes;
- dominant section sequence;
- use and ordering of tables, code, cases, checklists, FAQs, sources, CTAs;
- paragraph density and verdict cadence;
- proportion of explanation vs procedure vs reference detail;
- endings: summary, CTA, FAQ, limitation, open question, direct stop.

## Repetition That Deserves Attention

Flag repeated patterns when they recur across multiple pieces without a strong content reason, especially:

- every article opens with a numbered framework or callout box;
- every article follows `problem → diagnosis → fix → verify` for all sections;
- every article ends `checklist → FAQ → sources → CTA`;
- every technical piece expands into exhaustive edge cases;
- different bylines produce nearly identical sentence rhythm and section architecture;
- the same number of sections or same rhetorical balance appears across unrelated topics.

## Correction Rules

- Change architecture only when the repetition is not required by topic or genre.
- Prefer different **editorial choices**, not cosmetic randomness.
- Let one article be mechanism-led, another workflow-led, another comparison-led, if their subjects support those shapes.
- Omit modules that do not serve the current reader task.
- Move deep reference material to docs or separate content when appropriate.
- Do not force every article to be different; consistency can be useful for a real documentation series.
- Do not relocate FAQ, Sources, CTA, limitations, examples, or other conventional modules merely to make the corpus look less templated.
- Natural similarity with a clear reader function is better than conspicuous structural novelty.

## Module Placement Rule

When a repeated module contributes to a weak corpus fingerprint, resolve it in this order:

1. **OMIT** the module if it has no independent reader function.
2. **INTEGRATE** its useful content into the section where the question, evidence, limitation, or action naturally belongs.
3. **KEEP** the module in a conventional location if it still has a legitimate standalone purpose.
4. **RELOCATE** only when the new position improves reader flow for a concrete reason.

Examples:

- If FAQ answers simply repeat four existing sections, integrate those answers into the relevant sections instead of moving the FAQ into the middle of the article.
- If Sources support the whole article, an end reference section may remain appropriate even if neighboring articles also use one. If only one claim needs a source, cite it near that claim instead of moving a generic Sources block to an arbitrary position.
- Place a CTA where the reader has enough context to evaluate the action. Do not move it merely because nearby articles end with CTAs.

The goal is not maximum outline difference. The goal is absence of unjustified repeated structure.

## Multiple Authors

Different bylines do not justify invented personalities.

Without real author samples:

- keep a coherent brand/editorial register;
- allow structural variation from topic and reader task;
- do not fabricate biography, anecdotes, favorite phrases, attitudes, or personal quirks.

With representative samples for each author, use Style Clone (`references/style-clone.md`) to reproduce observable style differences.

## Pass Condition

A reader should be able to read several pieces from the same site without feeling that the same hidden outline generator produced all of them, while still recognizing a coherent editorial standard.
