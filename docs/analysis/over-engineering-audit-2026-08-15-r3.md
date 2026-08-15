# Over-engineering audit — 2026-08-15 (round 3)

**Source**: D1 code-essentiality pass of tech-audit round 3; every symbol below was cross-checked for callers across `backend/app`, `frontend/src`, `backend/tests`, `scripts/`, `deploy/` before being marked dead.
**Taxonomy**: essentiality ladder from `dimensions/D01-code-essentiality.md` — `delete:` / `stdlib:` / `native:` / `yagni:` / `shrink:`.
**Repo HEAD**: c50e463.

## Ranked by safe-deletion value (biggest win first)

### 1. delete: 5 orphaned shadcn-vue sidebar template components (326 lines, 0 imports) — safest win

`frontend/src/components/NavMain.vue` (57L), `NavUser.vue` (114L), `NavSecondary.vue` (41L), `NavDocuments.vue` (91L), `DragHandle.vue` (23L).

- Zero references anywhere in `src/` (verified: only self-references + `AppSidebar.vue:662` / `AuthenticatedLayout.vue:9` import the real `AppSidebar.vue`, which uses custom inline nav).
- Leftover from the shadcn-vue sidebar template; ship as build cruft today.
- **Fix**: delete the 5 files. No test, no behavior, no import chain is affected. 30 min.

### 2. delete: `backend/app/services/pipeline/batch_v2.py` (383 lines / 13.6 KB) — dead module kept as regression fixture

- `compact_singletons_in_db_v2` re-implements compact.py's singleton-match step; zero production imports.
- Sole references: `backend/tests/services/clustering/test_clustering_compaction_bugs.py:102,119,195` and `test_clustering_quality_audit.py:96-101` via `inspect.getsource`, plus `backend/scripts/verify_compaction_real.py:83`.
- `services/pipeline/CLAUDE.md` documents it as "v2 版本（死代码已清理，仅保留源码级回归测试参考）" — standing dead weight by policy.
- **Fix**: delete the module; re-point the three `inspect.getsource` regression tests at the live `compact.py`/`_do_merge_to_existing` path (mutate-and-fail verification stays intact); drop the `verify_compaction_real.py:83` reference. ~1 h incl. test adjustments.

### 3. delete: 8 standalone evaluation harnesses under `backend/app/services/clustering/experiments/` (~2275 lines, no caller)

`draw_questions_eval.py`, `embedding_recompute_eval.py`, `hybrid_search_eval.py`, `mock_incremental_eval.py`, `representative_quality_eval.py`, `reranker_cross_encoder_eval.py`, `vector_rerank_eval.py`, `review_islands.py`.

- Zero grep hits in `backend/tests/`, `scripts/`, `deploy/`; self-documenting "run via `python -m ...`" one-offs.
- **Keep**: `memory_labels.py` (imported by `unmerged_quality.py:17`), `prompts.py` (`memory_labels.py:14`), `evaluate.py` (entry point for the semantic-label experiment that is still being evaluated).
- **Fix**: delete the 8 files. If any experiment needs to be re-run, it lives in git history. ~1 h.

### 4. yagni: `validate_writer_output` fully tested but never wired into production (`structured_turn.py:234`)

- References: definition + `test_p1_p2_structured_turn.py:136,155-156`. No call site in `backend/app`; the metadata path (`pipeline.py:596`) produces `turn_contract_v2` but never validates writer text.
- Either call it from the contract-writer path (so the P2 validator actually gates output — this is a *correctness* improvement, not just deletion), or delete it together with its two test assertions.
- **Decision needed**: wire (M) vs delete (S). The feature was built to be a quality gate; if the gate is desired, wiring it in is the better outcome.

### 5. shrink: `WriterBrief` defined twice under the same name (`turn_intent.py:24` dataclass vs `structured_turn.py:150` Pydantic BaseModel)

- The `turn_intent.py` dataclass does runtime intent routing (6 call sites); the `structured_turn.py` model is only consumed inside `TurnContractV2` persistence. Same name, different shape, different layer — a reading-cost trap.
- `TurnContract` (turn_contract.py:61) and `TurnContractV2` (structured_turn.py:158) run in parallel; `turn_contract_v2_from_legacy` is called only at `pipeline.py:596`.
- **Fix**: rename the structured_turn one to `StructuredWriterBrief` (or inline it into `TurnContractV2`); add a one-paragraph note documenting the TurnContract→V2 derivation. ~1 h.

## Not findings (checked, cleared)

- No file exceeds the 1500-line redline (largest: ChatView.vue 1498, worker.py 1388, nodes.py 1343).
- TODO/FIXME count = 4 (threshold 20). Zero orphan migrations (all `_migration_*` registered; migration 020 is a documented commented-out entry). No ABC/single-impl Repository/Manager/Factory over-abstraction — the codebase uses module-level functions throughout.
- `experiment_reports/` at repo root is untracked (`??`) — generated eval output; either commit or gitignore it.
