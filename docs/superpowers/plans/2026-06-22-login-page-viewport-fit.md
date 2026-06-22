# Login Page Viewport Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the login page fit the browser viewport without page-level vertical scrolling at common laptop heights, and use the existing `/favicon-b.png` logo on the login page.

**Architecture:** Fix the root cause in `LoginPage.vue`: it currently uses `min-h-[calc(100vh-56px)]` plus vertical padding, which can exceed the viewport because the login route has no 56px header. Use a viewport-height wrapper (`h-dvh overflow-hidden`) and an internal `h-full min-h-0` grid with responsive padding, preserving the existing two-column marketing/form layout.

**Tech Stack:** Vue 3 `<script setup>`, Tailwind CSS, Playwright via `@playwright/test`, Vite build, Docker deploy script.

---

## File Structure

- Modify: `frontend/src/components/business/LoginPage.vue`
  - Replace `min-h-[calc(100vh-56px)]` wrappers with viewport-fitting classes.
  - Replace the `IB` login mark with `/favicon-b.png`.
- Modify: `frontend/src/components/business/CLAUDE.md`
  - Document that `LoginPage.vue` is a viewport-fit login shell and should avoid `calc(100vh-56px)` because the login route has no header.
- Create: `docs/dev-log/2026-06-22-login-page-viewport-fit.md`
  - Record root cause, fix, and verification.
- Create: `docs/superpowers/plans/2026-06-22-login-page-viewport-fit.md`
  - This implementation plan.

---

### Task 1: Reproduce Login Page Scroll

**Files:**
- Test only: Playwright one-off command.

- [ ] **Step 1: Run failing browser measurement against current production page**

Run:

```bash
node --input-type=module - <<'JS'
import { chromium } from '@playwright/test'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
await page.goto('http://localhost/login', { waitUntil: 'networkidle' })
const metrics = await page.evaluate(() => ({
  scrollHeight: document.scrollingElement.scrollHeight,
  clientHeight: document.scrollingElement.clientHeight,
  hasVerticalScroll: document.scrollingElement.scrollHeight > document.scrollingElement.clientHeight,
}))
await browser.close()
console.log(JSON.stringify(metrics))
if (metrics.hasVerticalScroll) process.exit(1)
JS
```

Expected before implementation: FAIL with JSON similar to `{"scrollHeight":739,"clientHeight":720,"hasVerticalScroll":true}`.

---

### Task 2: Fix Login Page Viewport Sizing and Logo

**Files:**
- Modify: `frontend/src/components/business/LoginPage.vue:2-3`
- Modify: `frontend/src/components/business/LoginPage.vue:79-81`

- [ ] **Step 1: Replace viewport wrapper classes**

In `frontend/src/components/business/LoginPage.vue`, replace:

```vue
  <div class="min-h-[calc(100vh-56px)] bg-background">
    <div class="mx-auto grid min-h-[calc(100vh-56px)] max-w-6xl gap-8 px-4 py-8 lg:grid-cols-[minmax(0,1fr)_420px] lg:items-center lg:px-8">
```

with:

```vue
  <div data-testid="login-page" class="h-dvh overflow-hidden bg-background">
    <div class="mx-auto grid h-full min-h-0 max-w-6xl gap-6 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_420px] lg:items-center lg:px-8">
```

Rationale: `h-dvh` follows the actual browser viewport; `overflow-hidden` prevents page-level scroll; internal `h-full min-h-0` lets the content fit the wrapper instead of exceeding it with `min-height + padding`.

- [ ] **Step 2: Replace login page IB mark with favicon logo**

In `frontend/src/components/business/LoginPage.vue`, replace:

```vue
          <div class="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-lg bg-primary text-sm font-bold text-primary-foreground lg:mx-0">
            IB
          </div>
```

with:

```vue
          <div class="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-lg lg:mx-0">
            <img src="/favicon-b.png" alt="InterviewBoss" class="h-9 w-9 object-contain" />
          </div>
```

---

### Task 3: Verify Viewport Fit

**Files:**
- Test only: Playwright one-off command.

- [ ] **Step 1: Build frontend**

Run:

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build
```

Expected: build exits 0.

- [ ] **Step 2: Deploy frontend**

Run:

```bash
/home/ubuntu/sj/interview-boss/deploy/docker-deploy.sh frontend
```

Expected: deploy exits 0 and reports frontend updated.

- [ ] **Step 3: Run browser measurement after deploy**

Run:

```bash
node --input-type=module - <<'JS'
import { chromium } from '@playwright/test'
const browser = await chromium.launch({ headless: true })
for (const size of [{ width: 1280, height: 720 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
  const page = await browser.newPage({ viewport: size })
  await page.goto('http://localhost/login', { waitUntil: 'networkidle' })
  const metrics = await page.evaluate(() => ({
    viewport: { width: innerWidth, height: innerHeight },
    scrollHeight: document.scrollingElement.scrollHeight,
    clientHeight: document.scrollingElement.clientHeight,
    hasVerticalScroll: document.scrollingElement.scrollHeight > document.scrollingElement.clientHeight,
    loginPageHeight: document.querySelector('[data-testid="login-page"]')?.getBoundingClientRect().height,
    loginLogoSrc: document.querySelector('[data-testid="login-page"] img[alt="InterviewBoss"]')?.getAttribute('src'),
  }))
  console.log(JSON.stringify(metrics))
  if (metrics.hasVerticalScroll) process.exit(1)
  if (metrics.loginLogoSrc !== '/favicon-b.png') process.exit(2)
  await page.close()
}
await browser.close()
JS
```

Expected: PASS with no vertical scroll for all listed viewport sizes and `loginLogoSrc` equal to `/favicon-b.png`.

---

### Task 4: Update Docs and Commit

**Files:**
- Modify: `frontend/src/components/business/CLAUDE.md`
- Create: `docs/dev-log/2026-06-22-login-page-viewport-fit.md`
- Commit all modified files.

- [ ] **Step 1: Update business component instructions**

In `frontend/src/components/business/CLAUDE.md`, add this bullet under `## 核心规则`:

```markdown
- `LoginPage.vue` 是无 header 的全屏登录壳，必须使用视口高度自适应（如 `h-dvh`/`h-full min-h-0`），不要使用 `calc(100vh-56px)` 这类为主界面 header 预留高度的写法。
```

- [ ] **Step 2: Add development log**

Create `docs/dev-log/2026-06-22-login-page-viewport-fit.md` with:

```markdown
# 2026-06-22 Login Page Viewport Fit

## Root Cause

`LoginPage.vue` used `min-h-[calc(100vh-56px)]` on both outer and inner wrappers while the login route has no 56px header. The inner wrapper also had `py-8`, so the actual rendered height could exceed the viewport at common laptop heights such as 1280×720.

## Change

- Replaced the login page wrappers with viewport-fit sizing: `h-dvh overflow-hidden` outside and `h-full min-h-0` inside.
- Reduced the login grid vertical padding from `py-8` to `py-4`.
- Replaced the login page `IB` mark with `/favicon-b.png`.

## Verification

- Reproduced the issue with Playwright at 1280×720 before the fix.
- Ran `cd frontend && npm run build`.
- Ran `./deploy/docker-deploy.sh frontend`.
- Verified with Playwright that `/login` has no page-level vertical scroll at 1280×720, 1366×768, and 390×844, and the login logo uses `/favicon-b.png`.
```

- [ ] **Step 3: Commit on master**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss status --short --branch
git -C /home/ubuntu/sj/interview-boss add frontend/src/components/business/LoginPage.vue frontend/src/components/business/CLAUDE.md docs/dev-log/2026-06-22-login-page-viewport-fit.md docs/superpowers/plans/2026-06-22-login-page-viewport-fit.md
git -C /home/ubuntu/sj/interview-boss commit -m "fix(frontend): fit login page to viewport" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: commit succeeds on `master`.

---

## Self-Review

- Spec coverage: Covers root cause reproduction, viewport fit fix, login favicon logo, docs, build, deploy, browser verification, and commit.
- Placeholder scan: No placeholders or vague instructions remain.
- Type consistency: No new functions, props, or types are introduced.
