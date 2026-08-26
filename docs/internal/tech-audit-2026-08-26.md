# Tech audit — 2026-08-26

**Auditor**: tech-audit skill, under user's direction
**Scope**: full project cut, D1–D16
**Repo HEAD**: `7f300f21f81f32c164a521274ea1f93de970ec6a` (`docs(audit): record findings disposition`)
**Findings source**: `.tech-audit/work/2026-08-26/findings.tsv`
**Previous mechanical baseline**: `.tech-audit/work/2026-08-24/findings.tsv`

> 审计期间保留了预先存在的未跟踪 `backups/`，没有纳入本次审计提交。审计只记录问题，没有修改业务代码。

## Executive summary

- 🔴 **Top risks**: no real disposable-stack E2E path; the OAuth gateway and nginx have no healthchecks; five production modules remain above the 1,500-line red line.
- 🟢 **Top strengths**: JWT issuer/expiry/refresh rotation and MCP account namespacing are explicit; pip-audit/npm audit and the repository secret scan are clean; the live backend, nginx, OAuth gateway, Redis, and worker are running, and the current database has zero FK violations.
- 🟡 **Biggest gap**: the default backend run is not green (37 failed tests), while mypy is non-blocking with 551 errors and the blocking line guard is currently red.

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---:|---:|---:|---:|
| D1 | Code essentiality | ❌ | 1 | 0 | 0 |
| D2 | Docs integrity | ⚠️ | 0 | 1 | 0 |
| D3 | Tests as adversaries | ❌ | 1 | 2 | 0 |
| D4 | Security posture | ⚠️ | 0 | 2 | 0 |
| D5 | Multi-tenant isolation | ⚠️ | 0 | 0 | 2 |
| D6 | Operational readiness | ❌ | 1 | 1 | 0 |
| D7 | Dependency hygiene | ⚠️ | 0 | 1 | 0 |
| D8 | Build / CI / dev-loop | ⚠️ | 0 | 2 | 0 |
| D9 | Data model integrity | ⚠️ | 0 | 1 | 0 |
| D10 | Performance & cost | — | 0 | 0 | 0 |
| D11 | Legal / compliance | ⚠️ | 0 | 1 | 0 |
| D12 | Admin surface consistency | ⚠️ | 0 | 1 | 0 |
| D13 | Setup replicability | ⚠️ | 0 | 0 | 1 |
| D14 | Correctness & robustness | ⚠️ | 0 | 1 | 0 |
| D15 | UX & interaction | ✅ | 0 | 0 | 0 |
| D16 | UI & design-system craft | ⚠️ | 0 | 0 | 1 |
| **Total** | | **❌** | **3** | **13** | **4** |

## Verification evidence

- `bash deploy/tests/*.sh`: all four storage/lifecycle contract tests passed.
- `ALL_PROXY= all_proxy= .venv/bin/pytest backend/tests -q --tb=no`: **37 failed, 2,799 passed, 4 skipped, 14 deselected, 29 warnings** in 13m27s. The first run without the override hit 23 collection errors because the local Python environment exposed `socks5h://127.0.0.1:7891`; the autouse cleanup in `backend/tests/conftest.py:25-34` runs after collection. The reported full-run count is from the no-proxy rerun.
- `.venv/bin/ruff check backend/app`: passed. `.venv/bin/mypy backend/app`: failed with **551 errors in 92 files**.
- `npm ci`: passed. `npm run build`: passed with large-chunk warnings. `npm run lint`: passed with 38 warnings. Default Playwright smoke: **1 passed**. The full mocked Playwright suite: **174 failed, 250 passed**; representative failures were stale mock response shapes and post-login selectors, and it is not counted as real full-stack evidence.
- `npm audit --registry=https://registry.npmjs.org --omit=dev`: no known production vulnerabilities. `.venv/bin/pip-audit`: no known vulnerabilities. `python3 backend/scripts/check_secrets.py`: no hardcoded secrets found.
- Runtime: backend `GET /api/health` returned 200, OAuth `/health` returned 200, and the database reported `PRAGMA foreign_key_check = 0` with schema version 117. Compose nevertheless reports empty health state for nginx and OAuth because those services have no healthcheck definition.

## Trend vs 2026-08-24

Mechanical mapping used here: severity 4 = 🔴, 3 = 🟡, 0–2 = 🟢.

| | This pass | 2026-08-24 | Delta |
|---|---:|---:|---:|
| 🔴 | 3 | 0 | +3 |
| 🟡 | 13 | 0 | +13 |
| 🟢 | 4 | 5 | -1 |
| Total | 20 | 5 | +15 |

The increase is not evidence of a new regression by itself: this is the first full project cut in the current work window, and it records risks previously visible only as notes or runtime observations. The comparison TSV contains five lower-severity rows; the current pass adds direct runtime and source evidence.

### Confirmed fixed or reduced since the previous TSV

- Public JD materialization now uses an explicit field whitelist at `backend/app/services/public_contributions.py:318-339`; the former whole-row snapshot exposure is closed.
- Admin public-contribution approval now delegates to `finalize_public_contribution_approval` at `backend/app/routers/public_contributions.py:148-160`; the former inline long-running cluster call is closed.
- The missing scan-tooling gap is reduced: CI has Gitleaks and Trivy, npm audit uses the official registry, and pip-audit is runnable locally.
- The two still-open lower-severity rows remain: `/mine` still filters after a full-table read, and active contribution requests still have no per-user cap.

### Accepted baseline and debt register

`.tech-audit/accepted.tsv` contains three owner-accepted items: weak admin-password length, dead historical provider-key material, and manual account deletion. They are not re-counted as current findings. At audit time no `.tech-audit/debt.tsv` debt register existed; the remediation follow-up now records open yellow items and expiry/verification ownership in that file.

## Findings — red items

### D1 — five production god-files remain over the line

`backend/app/routers/admin_evaluation.py` is 2,152 lines, `backend/app/services/llm.py` 1,950, `backend/app/worker.py` 1,935, `frontend/src/components/business/ChatView.vue` 1,654, and `backend/app/agents/chat/react_loop.py` 1,512. The documented 1,500-line rule in `scripts/line_guard.sh:1-8` treats these as shrink targets, not permanent exemptions. This is scored red because the project has five production modules above the source limit.

### D3 — no true full-stack E2E path

`frontend/tests/e2e/full-flow.spec.js:1-5` routes every API through Playwright mocks; `frontend/tests/playwright.config.js:8-16` starts only Vite. The backend pipeline E2E suite at `backend/tests/pipeline/test_pipeline_e2e.py:8-11` uses in-memory SQLite and mocked LLM calls. The many passing UI tests therefore validate UI contracts, not nginx → backend → Redis → persistence → rendered completion.

### D6 — mission-critical edge/auth services have no healthchecks

`docker-compose.yml:228-280` defines nginx and `oauth-gateway` with restart policies and dependencies but no `healthcheck`. OAuth does expose `/health` at `oauth-gateway/app.py:38-40`, so this is directly fixable. Runtime requests currently return 200, but `docker compose ps` shows blank health state for both services; a currently healthy process does not remove the monitoring gap.

## Findings — severity 3 items, each code-read and confirmed

### D2 — seed admin documentation disagrees with the clean-clone example

`README.md:196` and the migration fallback at `backend/app/db/migrations/auth.py:111-112` use `sj`, while copying `backend/.env.example:24` sets `ADMIN_USERNAME=admin`. A clean clone can therefore create a different first-login username from the one documented.

### D3 — backend regression suite is not green

The no-proxy full run produced 37 failures across bank, security, services, taxonomy, worker, and clustering tests. `scripts/check.sh:183-189` explicitly runs this suite through `run_nonblocking`, so the project can report a successful audit summary while the regression baseline is red.

The full mocked Playwright run also completed red: 174 failures and 250 passes. `frontend/tests/e2e/visual-quality.spec.js:167-322` shows representative post-login/login-page assertions failing after the current mocked API shape no longer matches the rendered contract; `frontend/tests/e2e/full-flow.spec.js:1-5` confirms the suite is mock-driven. This is scored as test-fixture/contract drift, separate from the real-stack E2E gap.

### D4 — outbound URL DNS validation has a rebinding window

`backend/app/core/outbound_url.py:99-107` resolves the hostname and returns the original URL. `backend/app/services/llm.py:451-465` then constructs an `httpx.AsyncClient`, and `backend/app/services/search_service.py:155-163` performs the request later. The connection-time resolution is not pinned to the validated address. Redirects are disabled, which is a useful mitigation, but it does not close DNS rebinding.

### D4 — app/nginx images do not declare their effective runtime user

`Dockerfile:91-116` creates `appuser` but leaves the image `USER` unset; `deploy/entrypoint.sh:4-11` starts as root to repair mounts and then calls `runuser`. The nginx stage at `Dockerfile:146-151` also has no `USER`. Runtime inspection confirms the app init process and nginx master start as root, while the OAuth image explicitly declares `USER oauthuser` at `oauth-gateway/Dockerfile:17-21`. This is a hardening gap, not evidence that app workers are necessarily root.

### D5 — low-severity tenant-scope inefficiency and queue abuse surface

`backend/app/routers/public_contributions.py:60-71` calls the service without a requester filter and filters the complete result in Python; the service query at `backend/app/services/public_contributions.py:183-201` has no `requester_id` predicate. Separately, `create_public_contribution_request` at `:138-180` deduplicates one source but does not cap a user's number of active requests. Existing authorization tests cover cross-user 404/isolation paths; these are boundedness and scaling gaps, scored green/minor rather than isolation breaches.

### D6 — operational runbooks do not cover common failure classes

The repository has useful backup/restore, eval-worker, and secret-rotation runbooks. `docs/runbooks/backup-restore.md:19-44` even states RPO/RTO and a verify drill. The set still has no dedicated DB/Redis outage, upstream LLM 5xx/rate-limit, disk exhaustion, or OOM recipe, so operators lack a consistent symptom-to-verification path for those failures.

### D7 — OAuth gateway dependencies are outside the locked/audited dependency path

`oauth-gateway/requirements.txt:1-7` uses open lower bounds, and `oauth-gateway/Dockerfile:7-11` installs them directly. The root `uv.lock` and root `pip-audit` path do not lock or audit this separately built image. npm and root Python vulnerability scans being clean does not establish reproducibility for the gateway.

### D8 — blocking line guard has regressed beyond frozen caps

`scripts/line_guard.sh:35-41` fails when an override grows, and `scripts/line_guard_overrides.txt:10-14` freezes the known baselines. The current run fails for `admin_evaluation.py` (2,152 > 1,919), `worker.py` (1,935 > 1,927), and `ChatView.vue` (1,654 > 1,609). `scripts/check.sh:226-238` marks this path blocking, so current CI cannot be green on this gate.

### D8 — static typing is not a trustworthy gate

`scripts/check.sh:264-275` makes mypy and frontend ESLint non-blocking. `frontend/tsconfig.json:2-9` has no `strict` setting, and `frontend/package.json:6-13` has no type-check script. The direct mypy run reports 551 errors. Build success does not establish type safety for the TypeScript SFC surface.

### D9 — generated schema documentation is stale by 31 migration versions

`docs/architecture/schema.md:3-18` says it was generated from migration 001–086 and documents only the 081–086 hygiene block. The live registry at `backend/app/db/migrations/__init__.py:303-331` reaches migration 117; the current database also reports schema version 117. Runtime FK integrity is clean, but the migration/schema documentation is not current enough for safe review.

### D11 — configurable provider geography is not deployment-specific

`docs/compliance/sub-processors.md:5-17,23-27` records generic “provider region” / “SiliconFlow data center” language while the product accepts user-selected OpenAI-compatible endpoints. `docs/compliance/privacy-policy.md:52-64` documents third-party processing but delegates the deployment context to the operator. An instance-specific region, legal entity, transfer mechanism, and retention matrix is still needed before treating this as complete compliance evidence.

### D12 — destructive clear-db has no durable admin audit event

`backend/app/routers/analytics.py:322-395` checks a confirmation token and creates a backup, but only emits generic logger messages; it does not write the `admin` identity, affected scope, result, or backup metadata to a durable audit record. The separate `admin_assistant_log` table described by `backend/app/db/migrations/admin_assistant.py:11-30` is not used by this endpoint.

### D14 — JWT secret-file read errors are silently treated as absence

At `backend/app/core/auth.py:24-43`, any exception while reading `.env` is swallowed, after which a new signing key may be generated. A write failure is logged at `:54-56`, but a read/parse/permission failure is not distinguished before regeneration. This can invalidate every active session after a restart and makes the root cause hard to diagnose.

## Low-severity findings

- **D13**: the rough source-to-example scan found 62 referenced runtime variables absent from `backend/.env.example:1-48`, while `README.md:217` says the example is complete. Most are optional tuning knobs; document or generate the full reference, or narrow the claim. The deployment happy path itself is documented and `deploy/docker-deploy.sh` supplies runtime secrets idempotently.
- **D16**: `PracticeStarChart.vue:47-103` and `PracticeQuadChart.vue:33-123` duplicate porcelain light/dark literals even though `frontend/src/utils/chartTokens.js:1-47` exists. This is theme-drift risk, not a current rendering failure.

## Dimensions without current findings

- **D10** is release-only in this cut; no release tag or launch decision was being audited, so no performance/cost claim is made.
- **D15**: no current `window.confirm` usage was found; source scan found reduced-motion handling in eight UI locations, the login smoke passed, and a waited 1280×720 browser capture rendered the login page. Full UI E2E remains mocked and does not upgrade D3.

## Triage

1. **P0** — add OAuth/nginx healthchecks; split the five god-files and restore the blocking line guard; repair the 37 backend regressions.
2. **P1** — add a disposable-stack E2E path; close DNS rebinding; make type checks actionable; lock and audit the OAuth gateway; regenerate schema docs.
3. **P2** — complete failure runbooks and deployment-specific subprocessor records; add durable clear-db audit events; fix public-contribution query/cap; clarify `.env.example`; harden JWT read failures; centralize chart tokens.

## Conclusion

The project has a solid set of security and data-isolation controls, and its currently running core services are healthy. It is not yet a clean release candidate from a whole-project perspective: the test baseline is red, the real-stack E2E gap is structural, the edge/auth monitoring boundary is incomplete, and the source-size/type-quality controls are either exceeded or non-blocking.
