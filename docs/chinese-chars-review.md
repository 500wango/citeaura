# CiteAura Source-Language Review

Review date: 2026-08-15

## Current policy

- Python code, comments, docstrings, logs, exceptions, and default prompts use English.
- Engine enums and persisted field identifiers are language-independent.
- Chinese text is limited to `locales/zh-CN`, Chinese NLP rules, methodology references, and test fixtures.
- Sampling mode values remain part of the documented API contract: `API·参数化知识`, `API·联网检索`, and `人工·产品端`.
- `engine/` may be changed for generic defects while SaaS-specific tenant, billing, and authentication behavior remains in `api/adapters/`.

## Verified state

- `engine/scripts/*.py` contains no literal Han characters. Chinese NLP expressions are represented with Unicode escapes.
- The standalone Chinese interface is isolated under `engine/locales/zh-CN/`.
- Chinese test data remains in `engine/tests/` where multilingual matching behavior requires it.
- Product translations remain in the locale catalogs; they are not treated as source-language violations.
- No locale catalog was removed or emptied as part of this review.

## Verification commands

```bash
rg -n '[\p{Han}]' engine/scripts --glob '*.py'
ruff check engine/scripts engine/tests
cd engine && python3 -m unittest discover -s tests
```

The first command is expected to return no matches. Test fixtures and locale files are intentionally outside that scan.

## Historical note

Earlier versions of this document described `engine/` as read-only and stated that tests could not run in the review environment. Both statements are obsolete. `AGENTS.md` is the source of truth for the current ownership boundary and required verification commands.
