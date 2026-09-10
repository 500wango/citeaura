# Creation Mode

Use this guide for new content rather than transformation of a full existing draft.

## Goal

Do not allow strong sentence-level prose to sit on top of a generic LLM outline. Build a selective, weighted, content-led structure before drafting, then stop when the reader's task is satisfied.

## 1. Define the editorial center

Before outlining, state internally:

- the primary reader task;
- the editorial thesis in one sentence;
- the 1–2 ideas that deserve the most attention;
- the minimum evidence or explanation required to support them.

If the piece cannot be summarized this way, the scope is probably too broad.

## 2. Classify candidate material

Use:

- **CORE** — required for the reader task;
- **SUPPORT** — evidence, mechanism, contrast, or useful detail;
- **OPTIONAL** — relevant but not necessary;
- **OMIT** — related but dilutes focus;
- **LINK-OUT** — useful but belongs elsewhere.

Do not promote OPTIONAL items merely because there is room.

## 3. Apply the publication boundary

For technical content, classify deeper material as ARTICLE, SUPPORTING EXAMPLE, DOCS, REFERENCE, or SEPARATE ARTICLE. Read `publication-boundary.md` when the draft starts accumulating edge cases, full schemas, implementation matrices, deployment recipes, or exhaustive troubleshooting.

If no real link destination exists, do not fabricate one. Simply omit or summarize the material.

## 4. Design information weight

A strong plan can be uneven:

- one section may be the conceptual core;
- one may be a short diagnostic;
- one may be a worked example;
- one may be a limitation;
- some candidate sections may disappear entirely.

Do not equalize length or detail for visual symmetry.

## 5. Avoid default article architecture

Watch for plans such as:

- introduction → benefits → challenges → best practices → future → conclusion;
- N causes where every cause has identical depth and format;
- framework → example → checklist → FAQ → summary by default;
- every section ending in a lesson or maxim;
- every point receiving an example, edge case, and action item;
- technical blog → full implementation → exhaustive edge cases → checklist → FAQ → sources → CTA.

A useful article is not required to be a complete content package.

## 6. Select section shapes by function

Possible shapes include:

- direct explanation;
- worked example;
- short procedure;
- table;
- counterexample;
- interpretation;
- limitation;
- diagnostic checklist;
- comparison;
- concise rule;
- link-out.

Do not repeat the same shape merely for consistency.

## 7. Corpus fingerprint audit when a corpus exists

If 3–5 related pieces are already available, inspect their outline fingerprints before finalizing the plan. Read `corpus-diversity.md`.

Do not create different structures randomly. Change only repeated patterns that are not justified by topic or genre.

## 8. Drafting rules

- Start near the substantive point; do not manufacture scene-setting.
- Let obvious transitions remain implicit.
- Do not explain what the intended reader can infer.
- Allow some sections to end without a takeaway.
- Use examples only when they clarify mechanism, scale, contrast, or application.
- Do not fabricate specificity to create authority.
- Do not auto-add FAQ, TL;DR, summary, checklist, decision tree, case study, sources, or CTA.

## 9. Stopping Rule

After each major planned block, ask whether the reader can now:

- answer the primary question;
- perform the intended action;
- understand the key mechanism or tradeoff;
- avoid the main likely mistake.

If yes, the burden shifts to new material: it must justify itself. Mere relevance is not enough.

Stop when the next section would mainly increase completeness rather than usefulness.

## 10. Post-draft structural audit

Ask:

- Does every section have a distinct job?
- Are adjacent sections built from the same rhetorical template?
- Is the article suspiciously complete relative to the reader's need?
- Did any module appear because it is conventional rather than useful?
- Are examples too perfectly aligned with the previous rule?
- Is every section equally developed although the ideas are unequal?
- Did a blog article absorb content that belongs in docs, reference, or another article?
- Does this outline duplicate the structure of nearby articles without a topic-driven reason?
- Could material disappear without reducing the reader's ability to complete the task?

If yes, simplify before running the shared quality gate.
