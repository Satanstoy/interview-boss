# Daily Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily quality gate for InterviewBoss behind `./deploy/docker-deploy.sh check`.

**Architecture:** Keep the user-facing command in `deploy/docker-deploy.sh`, but put the check orchestration in a new root-level `scripts/check.sh`. Repair the Docker test runtime and portable test paths first, then add frontend npm scripts and a self-starting Playwright smoke test, then wire the unified gate and document it.

**Tech Stack:** Bash, Docker Compose, Python 3.10, pytest, uv, Vue 3, Vite, Playwright, npm audit, pip-audit.

## Global Constraints

- Backend pytest must run through Docker test-runtime, not directly on the host and not inside the production `backend` container.
- `./deploy/docker-deploy.sh check` is a development verification command, not a deployment command.
- Audit is non-blocking in this phase: npm and pip-audit findings must be reported as WARN or SKIPPED, not fail the daily gate.
- Do not fix npm or Python dependency vulnerabilities in this implementation.
- Do not introduce TypeScript, ESLint, Vitest, or a new frontend test runner.
- Do not refactor backend router/service boundaries or frontend state flow.
- Do not make all 1419 backend tests part of the default daily gate.
- Update the relevant `CLAUDE.md` files and README when the command behavior changes.
- The current worktree has pre-existing `CLAUDE.md` edits. Preserve them. Stage only the hunks created by this implementation when committing documentation.

---

## File Structure

- Modify `Dockerfile`: include root deployment/config files in the `test-runtime` image so infra tests can read them inside Docker.
- Modify `backend/tests/bank/test_master_bank_syntax.py`: make source path resolution portable in Docker and local checkouts.
- Create `frontend/tests/smoke/quality-gate.spec.js`: a minimal mocked Playwright smoke test for `npm run test`.
- Modify `frontend/tests/playwright.config.js`: add `webServer` so Playwright tests can start Vite automatically.
- Modify `frontend/package.json`: add `test`, `test:e2e`, and `audit:prod` scripts.
- Create `scripts/check.sh`: orchestrate backend, frontend, and audit checks with an aggregate summary.
- Modify `deploy/docker-deploy.sh`: add `check` command that delegates to `scripts/check.sh`.
- Modify `CLAUDE.md`, `backend/CLAUDE.md`, `backend/tests/CLAUDE.md`, `frontend/CLAUDE.md`, and `README.md`: document the new daily gate.

---

### Task 1: Repair Docker Test Runtime And Backend Structure Tests

**Files:**
- Modify: `Dockerfile`
- Modify: `backend/tests/bank/test_master_bank_syntax.py`

**Interfaces:**
- Consumes: Existing Docker test service from `docker-compose.yml`.
- Produces: A test-runtime image where `/app/Dockerfile`, `/app/docker-compose.yml`, `/app/.dockerignore`, `/app/nginx/`, and `/app/deploy/` exist; portable `BACKEND_ROOT` path resolution for syntax tests.

- [ ] **Step 1: Run the existing failing backend structure tests**

Run:

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/bank/test_master_bank_syntax.py \
  backend/tests/infra/test_docker_config.py \
  backend/tests/services/test_router_refactor.py \
  -q
```

Expected: FAIL. The current failures should include missing files under `/app/Dockerfile`, `/app/docker-compose.yml`, or paths under `backend/tests/app/routers`.

- [ ] **Step 2: Add root deployment files to the test-runtime image**

In `Dockerfile`, in the `test-runtime` stage after:

```dockerfile
COPY --chown=appuser backend/ ./backend/
COPY --chown=appuser backend/tests/ ./backend/tests/
```

insert:

```dockerfile
COPY --chown=appuser Dockerfile docker-compose.yml .dockerignore ./
COPY --chown=appuser nginx/ ./nginx/
COPY --chown=appuser deploy/ ./deploy/
```

This gives `backend/tests/infra/test_docker_config.py` the files it already expects at `PROJECT_ROOT`.

- [ ] **Step 3: Make `test_master_bank_syntax.py` locate `backend/app` portably**

Replace the top path constants in `backend/tests/bank/test_master_bank_syntax.py` with this code:

```python
import pytest
import ast
import sys
from pathlib import Path


def _find_backend_root(start: Path) -> Path:
    """Return the backend directory containing app/ and tests/."""
    for candidate in (start, *start.parents):
        if (candidate / "app" / "routers").is_dir() and (candidate / "tests").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate backend root from {start}")


BACKEND_ROOT = _find_backend_root(Path(__file__).resolve())
```

Then update the class constants:

```python
class TestMasterBankSyntax:
    """测试 master_bank.py 的 Python 语法正确性"""

    MODULE_PATH = BACKEND_ROOT / "app" / "routers" / "questions.py"
    ANSWERS_PATH = BACKEND_ROOT / "app" / "routers" / "answers.py"
```

Update both import tests to use `BACKEND_ROOT`:

```python
backend_dir = BACKEND_ROOT
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
```

- [ ] **Step 4: Rebuild the test image and verify the backend structure tests**

Run:

```bash
docker compose --profile test build test
docker compose --profile test run --rm test uv run pytest \
  backend/tests/bank/test_master_bank_syntax.py \
  backend/tests/infra/test_docker_config.py \
  backend/tests/services/test_router_refactor.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Verify backend collect and compile still work**

Run:

```bash
docker compose --profile test run --rm test uv run pytest --collect-only -q
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
```

Expected: `pytest --collect-only` reports collected tests and exits 0. `compileall` exits 0 with no output.

- [ ] **Step 6: Commit Task 1**

Run:

```bash
git add Dockerfile backend/tests/bank/test_master_bank_syntax.py
git commit -m "test(backend): make docker structure tests portable"
```

---

### Task 2: Add Frontend Daily Test Scripts And Smoke Test

**Files:**
- Create: `frontend/tests/smoke/quality-gate.spec.js`
- Modify: `frontend/tests/playwright.config.js`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: Existing Vite app and Playwright dependency.
- Produces: `npm run test`, `npm run test:e2e`, and `npm run audit:prod`; a smoke test that does not require the real backend.

- [ ] **Step 1: Confirm the missing frontend script failure**

Run:

```bash
cd frontend
npm run test
```

Expected: FAIL with a missing `test` script.

- [ ] **Step 2: Create the quality gate smoke test**

Create `frontend/tests/smoke/quality-gate.spec.js` with:

```javascript
import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async route => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'mocked unauthorized' }),
    })
  })
})

test('quality gate smoke: login route renders without real backend', async ({ page }) => {
  await page.goto('/login')

  await expect(page.getByTestId('login-page')).toBeVisible()
  await expect(page.getByTestId('login-brand')).toContainText('InterviewBoss')
  await expect(page.getByTestId('login-panel')).toBeVisible()
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
})
```

- [ ] **Step 3: Make Playwright start Vite automatically**

Replace `frontend/tests/playwright.config.js` with:

```javascript
import { defineConfig } from '@playwright/test'

const isCI = Boolean(process.env.CI)

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.js',
  timeout: 30000,
  retries: 0,
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:3000',
    reuseExistingServer: !isCI,
    timeout: 120000,
  },
  use: {
    baseURL: 'http://127.0.0.1:3000',
    headless: true,
    channel: 'chrome',
    screenshot: 'off',
    trace: 'off',
    launchOptions: {
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
      timeout: 30000,
    },
  },
  reporter: [
    ['list'],
    ['json', { outputFile: 'test-results.json' }],
  ],
})
```

- [ ] **Step 4: Add frontend package scripts**

In `frontend/package.json`, replace the `scripts` object with:

```json
"scripts": {
  "dev": "vite",
  "build": "vite build",
  "preview": "vite preview",
  "test": "playwright test tests/smoke/quality-gate.spec.js",
  "test:e2e": "playwright test tests/e2e",
  "audit:prod": "npm audit --registry=https://registry.npmjs.org --omit=dev"
}
```

- [ ] **Step 5: Verify frontend blocking scripts**

Run:

```bash
cd frontend
npm run build
npm run test
```

Expected: both commands exit 0. `npm run test` starts Vite through Playwright `webServer` and runs only `frontend/tests/smoke/quality-gate.spec.js`.

- [ ] **Step 6: Verify frontend audit script reports without changing policy**

Run:

```bash
cd frontend
npm run audit:prod
```

Expected: command may exit nonzero if vulnerabilities exist. Do not fix vulnerabilities in this task. The unified gate will treat this command as non-blocking in Task 3.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add frontend/package.json frontend/tests/playwright.config.js frontend/tests/smoke/quality-gate.spec.js
git commit -m "test(frontend): add daily smoke gate scripts"
```

---

### Task 3: Add Unified Check Orchestration

**Files:**
- Create: `scripts/check.sh`
- Modify: `deploy/docker-deploy.sh`

**Interfaces:**
- Consumes: Task 1 backend commands and Task 2 frontend npm scripts.
- Produces: `./deploy/docker-deploy.sh check`, `check backend`, `check frontend`, and `check audit` with aggregated PASS/FAIL/WARN/SKIPPED output.

- [ ] **Step 1: Create `scripts/check.sh`**

Create `scripts/check.sh` with:

```bash
#!/bin/bash
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
blocking_failed=0
declare -a RESULTS=()

record() {
  local status="$1"
  local name="$2"
  local message="${3:-}"
  RESULTS+=("${status}|${name}|${message}")
  if [ -n "$message" ]; then
    printf "%s %s: %s\n" "$status" "$name" "$message"
  else
    printf "%s %s\n" "$status" "$name"
  fi
}

require_blocking_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    record "FAIL" "tool ${cmd}" "command not found"
    blocking_failed=1
    return 1
  fi
  return 0
}

run_blocking() {
  local name="$1"
  shift
  if "$@"; then
    record "PASS" "$name"
  else
    local rc=$?
    record "FAIL" "$name" "exit ${rc}"
    blocking_failed=1
  fi
}

run_nonblocking() {
  local name="$1"
  shift
  if "$@"; then
    record "PASS" "$name"
  else
    local rc=$?
    record "WARN" "$name" "reported issues or could not complete, exit ${rc}"
  fi
}

check_docker_access() {
  if ! docker info >/dev/null 2>&1; then
    record "FAIL" "tool docker" "Docker unavailable or permission denied"
    blocking_failed=1
    return 1
  fi
  return 0
}

run_backend() {
  require_blocking_cmd docker || return
  check_docker_access || return

  run_blocking "backend collect" \
    "$PROJECT_DIR/deploy/docker-deploy.sh" test --collect-only -q

  run_blocking "backend compile" \
    docker compose --profile test run --rm test uv run python -m compileall -q backend/app

  run_blocking "backend structure tests" \
    docker compose --profile test run --rm test uv run pytest \
      backend/tests/bank/test_master_bank_syntax.py \
      backend/tests/infra/test_docker_config.py \
      backend/tests/services/test_router_refactor.py \
      -q
}

run_frontend() {
  require_blocking_cmd npm || return

  run_blocking "frontend build" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run build"

  run_blocking "frontend tests" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run test"
}

run_frontend_audit() {
  if ! command -v npm >/dev/null 2>&1; then
    record "SKIP" "frontend audit" "npm command not found"
    return
  fi

  run_nonblocking "frontend audit" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run audit:prod"
}

run_backend_audit() {
  if ! command -v uv >/dev/null 2>&1; then
    record "SKIP" "backend audit" "uv command not found; run uv tool run pip-audit manually"
    return
  fi

  run_nonblocking "backend audit" \
    bash -lc "cd '$PROJECT_DIR' && uv tool run pip-audit -r <(uv export --frozen --no-dev --format requirements-txt --no-hashes) --no-deps --disable-pip --progress-spinner off"
}

run_audit() {
  echo "AUDIT: reported only, non-blocking in this phase"
  run_frontend_audit
  run_backend_audit
}

print_summary() {
  echo ""
  echo "InterviewBoss daily check"
  echo ""

  local entry status name message
  for entry in "${RESULTS[@]}"; do
    IFS='|' read -r status name message <<< "$entry"
    if [ -n "$message" ]; then
      printf "%s %s: %s\n" "$status" "$name" "$message"
    else
      printf "%s %s\n" "$status" "$name"
    fi
  done

  echo ""
  if [ "$blocking_failed" -eq 0 ]; then
    echo "Blocking checks: PASS"
  else
    echo "Blocking checks: FAIL"
  fi
  echo "Audit checks: WARN only"
}

cd "$PROJECT_DIR" || exit 1

case "$MODE" in
  all)
    run_backend
    run_frontend
    run_audit
    ;;
  backend)
    run_backend
    ;;
  frontend)
    run_frontend
    ;;
  audit)
    run_audit
    ;;
  *)
    record "FAIL" "check mode" "unknown mode: ${MODE}"
    blocking_failed=1
    ;;
esac

print_summary
exit "$blocking_failed"
```

- [ ] **Step 2: Make the script executable and syntax-check it**

Run:

```bash
chmod +x scripts/check.sh
bash -n scripts/check.sh
./scripts/check.sh invalid-mode
```

Expected: `bash -n` exits 0. `invalid-mode` exits nonzero and prints `FAIL check mode`.

- [ ] **Step 3: Add `check` forwarding to `deploy/docker-deploy.sh`**

Update the usage comment at the top to include `check`:

```bash
# 用法：./docker-deploy.sh [build|up|down|restart|status|logs|update|frontend|worker-up|worker-down|worker-restart|worker-logs|test|check|backup|cleanup|diagnose]
```

Add this function after `do_test()`:

```bash
# ── 运行日常质量门禁 ──
do_check() {
  "$PROJECT_DIR/scripts/check.sh" "$@"
}
```

Add this case entry after `test)`:

```bash
  check)           check_docker; do_check "${@:2}" ;;
```

Add this help line near the existing `test` help:

```bash
    echo "  check [backend|frontend|audit]  运行日常质量门禁（audit 只报告不拦截）"
```

Add these examples near the existing `test` examples:

```bash
    echo "  ./docker-deploy.sh check"
    echo "  ./docker-deploy.sh check backend"
```

- [ ] **Step 4: Verify check modes**

Run:

```bash
./deploy/docker-deploy.sh check backend
./deploy/docker-deploy.sh check frontend
./deploy/docker-deploy.sh check audit
```

Expected:

- `check backend` exits 0 after backend collect, compile, and structure tests pass.
- `check frontend` exits 0 after frontend build and smoke test pass.
- `check audit` exits 0 even when npm or pip-audit reports vulnerabilities, and prints `AUDIT: reported only, non-blocking in this phase`.

- [ ] **Step 5: Verify default check**

Run:

```bash
./deploy/docker-deploy.sh check
```

Expected: exits 0 when blocking checks pass. Summary includes backend checks, frontend checks, audit WARN/SKIPPED lines, `Blocking checks: PASS`, and `Audit checks: WARN only`.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add scripts/check.sh deploy/docker-deploy.sh
git commit -m "feat: add daily quality gate command"
```

---

### Task 4: Document The Daily Gate And Run Final Verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `backend/CLAUDE.md`
- Modify: `backend/tests/CLAUDE.md`
- Modify: `frontend/CLAUDE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Final command behavior from Task 3.
- Produces: Project docs that match the implemented gate and preserve existing dirty user changes.

- [ ] **Step 1: Inspect existing documentation changes before editing**

Run:

```bash
git diff -- CLAUDE.md backend/CLAUDE.md backend/tests/CLAUDE.md frontend/CLAUDE.md README.md
```

Expected: review output before editing. If any of these files contain unrelated pre-existing edits, preserve them and stage only your new hunks with `git add -p`.

- [ ] **Step 2: Update root `CLAUDE.md` commands**

In `CLAUDE.md`, add this command in the development/test command block:

```bash
./deploy/docker-deploy.sh check                                  # 日常质量门禁（后端 Docker + 前端 build/test + audit 报告）
```

Add this rule under the testing infrastructure section:

```markdown
- **日常门禁**：开发收尾优先跑 `./deploy/docker-deploy.sh check`；audit 第一阶段只报告不拦截。
```

- [ ] **Step 3: Update `backend/CLAUDE.md`**

In the backend command block, add:

```bash
./deploy/docker-deploy.sh check backend                                           # 后端日常门禁（Docker test-runtime）
```

In the testing guidance, add:

```markdown
后端日常门禁由 `./deploy/docker-deploy.sh check backend` 统一执行，包含 pytest collect、`compileall backend/app` 和关键结构测试。仍然禁止在宿主机直接跑 pytest。
```

- [ ] **Step 4: Update `backend/tests/CLAUDE.md`**

Add this section after the command block:

```markdown
## 路径定位规则

结构测试必须从 repo root 或 `backend/app` 根定位文件，禁止使用脆弱的 `Path(__file__).parent.parent / "app"`。推荐通过向上查找同时包含 `backend/app` 和 `docker-compose.yml` 的目录来确定项目根，或通过向上查找包含 `app/routers` 与 `tests` 的目录来确定 backend 根。
```

Add this command:

```bash
./deploy/docker-deploy.sh check backend                                           # 后端日常质量门禁
```

- [ ] **Step 5: Update `frontend/CLAUDE.md`**

In the command block, add:

```bash
npm run test         # 日常 smoke 测试（Playwright 自动启动 Vite）
npm run test:e2e     # 完整 E2E 测试
npm run audit:prod   # 生产依赖 audit（统一门禁中只报告不拦截）
```

Add this testing note:

```markdown
`./deploy/docker-deploy.sh check frontend` 会执行 `npm run build` 和 `npm run test`。`npm run audit:prod` 使用官方 npm registry；在统一门禁中 audit 结果只报告不拦截。
```

- [ ] **Step 6: Update README quick start**

In README under "4. 本地开发（可选）", after the frontend dev command block, add:

````markdown
日常开发收尾可运行统一质量门禁：

```bash
./deploy/docker-deploy.sh check
```

该命令会执行后端 Docker 测试基础检查、前端 build/smoke 测试，并汇总 npm/pip audit 报告。audit 第一阶段只报告不拦截。
````

Ensure the nested fenced block is valid Markdown by closing the outer prose before the command block.

- [ ] **Step 7: Run final verification commands**

Run:

```bash
./deploy/docker-deploy.sh check backend
./deploy/docker-deploy.sh check frontend
./deploy/docker-deploy.sh check audit
./deploy/docker-deploy.sh check
```

Expected: backend and frontend modes exit 0. Audit mode exits 0 while reporting WARN/SKIPPED as needed. Default check exits 0 if all blocking checks pass.

- [ ] **Step 8: Run documentation and shell sanity checks**

Run:

```bash
bash -n scripts/check.sh
bash -n deploy/docker-deploy.sh
git diff --check
```

Expected: all exit 0.

- [ ] **Step 9: Commit Task 4**

If documentation files had pre-existing unrelated changes, stage only this task's hunks:

```bash
git add -p CLAUDE.md backend/CLAUDE.md backend/tests/CLAUDE.md frontend/CLAUDE.md README.md
git commit -m "docs: document daily quality gate"
```

If the documentation files contain only this task's intended changes, this exact staging command is acceptable:

```bash
git add CLAUDE.md backend/CLAUDE.md backend/tests/CLAUDE.md frontend/CLAUDE.md README.md
git commit -m "docs: document daily quality gate"
```

---

## Final Completion Checklist

- [ ] `./deploy/docker-deploy.sh check backend` exits 0.
- [ ] `./deploy/docker-deploy.sh check frontend` exits 0.
- [ ] `./deploy/docker-deploy.sh check audit` exits 0 and treats audit as non-blocking.
- [ ] `./deploy/docker-deploy.sh check` exits 0 when blocking checks pass.
- [ ] `bash -n scripts/check.sh` exits 0.
- [ ] `bash -n deploy/docker-deploy.sh` exits 0.
- [ ] `git diff --check` exits 0.
- [ ] Commits are split by task and do not include unrelated pre-existing worktree changes.
