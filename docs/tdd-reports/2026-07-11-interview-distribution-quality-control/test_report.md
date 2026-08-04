# Interview Distribution Quality Control — Verification Report

Date: 2026-07-11

## Passed deterministic verification

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_distribution_e2e.py backend/tests/chat/test_interview_distribution_e2e_verifier.py -q
```

Result: `2 passed`.

The deterministic E2E recomputes public linked facts, materializes the default, freezes a plan, runs the controller for the full target count, and asserts that the stats version, raw type counts, plan distribution, soft targets, and derived execution counts agree.

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ backend/tests/interview/ backend/tests/pipeline/ backend/tests/infra/test_worker.py -q
```

Result: 981 collected tests completed without a reported failure.

```bash
cd frontend && npm run build
```

Result: Vite production build succeeded.

## Live verifier status

The checked-in manual verifier is `backend/scripts/verify_interview_distribution_e2e.py`. It requires `RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1`, an authenticated token, and a deployed application; it writes a JSON report and exits nonzero when the canonical five types are absent or ratios are not normalized.

The deployment command was attempted:

```bash
./deploy/docker-deploy.sh update
```

It was deliberately refused by the deployment disk guard. The root filesystem had 3858MB free, below the required 4096MB build threshold. No deployment was forced and no destructive cleanup was performed. Therefore no live HTTP verdict is claimed in this report.

## Live E2E verification (2026-07-12)

After cleaning Docker images and build cache (~2.1GB reclaimed), deployment succeeded.

**Bug fix**: `init_db()` created a `sqlite3.connect()` without setting `row_factory = sqlite3.Row`, causing `TypeError: tuple indices must be integers or slices` when migration 042 accessed rows by column name. Fixed in `backend/app/db/connection.py`.

```bash
RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1 \
INTERVIEW_BOSS_E2E_TOKEN="$TOKEN" \
python3 backend/scripts/verify_interview_distribution_e2e.py \
  --report /tmp/interview_distribution_e2e_report.json
```

Result: **`verdict: "pass"`**

- `has_all_canonical_types: true` — all five types present (project_followup, knowledge_probe, algorithm_coding, system_design, behavioral)
- `ratio_sum: 1.0` — ratios normalized
- `confidence: "high"` — 33 sample interviews, 450 sample questions
- `recommended_total_count: 12`

All services healthy: backend, nginx, redis.

## Runtime distribution E2E (final, 2026-07-12)

The distribution verifier now uses `--exercise-runtime` to create a real
conversation with the current system default, send explicit next-question
requests through the production SSE endpoint, and read back persisted
conversation metadata.  It rejects any counted event that is not a
high-confidence, bank-bound question, as well as any mismatch between the
frozen plan and the execution read model.

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" \
  test /app/.venv/bin/python -m pytest \
  backend/tests/chat/test_interview_distribution_e2e.py \
  backend/tests/chat/test_interview_distribution_e2e_verifier.py -q
```

Result: **`12 passed`**.

```bash
RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1 \
INTERVIEW_BOSS_E2E_TOKEN="$TOKEN" \
docker compose exec backend uv run python \
  backend/scripts/verify_interview_distribution_e2e.py \
  --base-url http://localhost:8000 \
  --exercise-runtime \
  --max-turns 16 \
  --keep-conversation \
  --report /tmp/interview-distribution-runtime-e2e.json
```

Result: **`verdict: "pass"`**.  The session froze `stats_version: 1` from the
same public default and completed all 12 primary questions with exactly these
counts:

| Type | Frozen target | Actual |
| --- | ---: | ---: |
| algorithm_coding | 1 | 1 |
| behavioral | 1 | 1 |
| knowledge_probe | 5 | 5 |
| project_followup | 0 | 0 |
| system_design | 5 | 5 |

The verifier found 12 counted events, all high-confidence and bound to a
question-bank question; `alignment.passed` was `true` with no errors.

## Final post-review rerun (2026-07-12)

Three independent review rounds added regression coverage for negated
next-question requests, standalone `HR` matching, a 50-question frozen plan
crossing the 100-message context window, and the generic candidate-question
wrap-up state. Real candidate exit remains higher priority than the plan;
only the false-end and generic-stop paths are deferred while the plan is
incomplete.

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" \
  test /app/.venv/bin/python -m pytest \
  backend/tests/chat/test_interview_distribution_e2e.py \
  backend/tests/chat/test_interview_distribution_plan.py \
  backend/tests/chat/test_interview_distribution_e2e_verifier.py \
  backend/tests/interview/test_interview_distribution_storage.py \
  backend/tests/services/test_question_draw_service.py \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/chat/test_tools.py \
  backend/tests/chat/test_mcp_session.py \
  backend/tests/chat/test_chat_routing.py \
  backend/tests/chat/test_turn_contract.py -q
```

Result: **`139 passed`**.

After deploying the final commit, a fresh temporary account ran
`verify_interview_distribution_e2e.py --exercise-runtime`; both the account
and verifier-created conversation were removed after completion. Result:
**`verdict: "pass"`**, `stats_version: 1`, `turn_count: 13`, and exactly 12
counted, high-confidence bank-bound events.

| Type | Frozen target | Actual |
| --- | ---: | ---: |
| algorithm_coding | 1 | 1 |
| behavioral | 1 | 1 |
| knowledge_probe | 5 | 5 |
| project_followup | 0 | 0 |
| system_design | 5 | 5 |
