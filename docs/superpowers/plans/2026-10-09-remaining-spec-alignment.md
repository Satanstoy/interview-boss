# Remaining question-bank specification alignment

Authorized scope: the four confirmed gaps in the October 9 audit. Baseline: 8693f2fb on codex/frontend-ui-hierarchy-cleanup. Preserve existing untracked files. Local commits only; no production deployment.

1. Add real JWT/FastAPI/SQLite regressions for merge-history visibility, pagination, cross-scope merge atomicity, and public-answer isolation. Record failing output before production edits.
2. Enforce historical and current ownership on merge-history reads, retain participant ownership before compaction deletes rows, reject cross-scope manual merge before writes, and keep private answers in immutable promotion history only. Run focused and related security tests; review and commit the validated unit.
3. Add review-detail revision and a server projection preview using the same projection builder as approval. Add route behavior tests and UI regressions before implementation. Implement detail editing, exclusions, explicit preview and revision-aware confirmation for interview/JD contributions, keeping legacy approval compatible.
4. Validate frontend tests/build and related backend regressions. Update real-stack review flow to exercise the UI. Run available isolated validation and report exact coverage and remaining unverified boundaries.
