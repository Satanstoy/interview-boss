# Login Page Minimal Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the login page into a clean, viewport-fit, InterviewBoss-branded entry screen with a login card, a no-login preview button, and three short benefit chips.

**Architecture:** Keep authentication logic inside the existing `LoginModal.vue`; add a small `hideHeader` prop for embedded use so the page owns the brand/title hierarchy. Replace `LoginPage.vue`'s dense split dashboard preview with one centered layout that fits low-height viewports and preserves the existing `/master-bank?preview=1` preview route.

**Tech Stack:** Vue 3 `<script setup>`, Tailwind CSS, Playwright via `@playwright/test`, Vite build, Docker deploy script.

---

## File Structure

- Modify: `frontend/src/components/business/LoginModal.vue`
  - Add `hideHeader` prop for embedded mode only.
  - Use `v-if="!hideHeader"` on the embedded header block to reduce form height in `LoginPage.vue`.
- Modify: `frontend/src/components/business/LoginPage.vue`
  - Remove left-side marketing/dashboard preview.
  - Create centered brand/logo area, login card, preview CTA, and three short benefit chips.
  - Pass `hide-header` to `LoginModal embedded`.
- Modify: `frontend/src/components/business/CLAUDE.md`
  - Document minimal login-page rule and preview CTA naming.
- Create: `docs/dev-log/2026-06-22-login-page-minimal-redesign.md`
  - Record research/design rationale and verification.
- Create: `docs/superpowers/plans/2026-06-22-login-page-minimal-redesign.md`
  - This implementation plan.

---

### Task 1: Write RED Browser Assertions

**Files:**
- Test only: Playwright one-off command.

- [ ] **Step 1: Run failing assertion against current deployed page**

Run:

```bash
node --input-type=module - <<'JS'
import { chromium } from '@playwright/test'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
await page.goto('http://localhost/login', { waitUntil: 'networkidle' })
const result = await page.evaluate(() => ({
  hasVerticalScroll: document.scrollingElement.scrollHeight > document.scrollingElement.clientHeight,
  hasOldDashboardPreview: document.body.textContent.includes('AI Interview Copilot') || document.body.textContent.includes('题库规模'),
  hasPreviewCta: document.body.textContent.includes('无需登录，先体验工作台'),
  hasBenefitChips: ['高频题库', '模拟面试', '复盘进度'].every(text => document.body.textContent.includes(text)),
  formBottom: document.querySelector('section[data-testid="login-panel"]')?.getBoundingClientRect().bottom ?? null,
  viewportHeight: innerHeight,
}))
await browser.close()
console.log(JSON.stringify(result))
if (result.hasVerticalScroll) process.exit(1)
if (result.hasOldDashboardPreview) process.exit(2)
if (!result.hasPreviewCta) process.exit(3)
if (!result.hasBenefitChips) process.exit(4)
if (result.formBottom === null || result.formBottom > result.viewportHeight) process.exit(5)
JS
```

Expected before implementation: FAIL because the current page still contains old dashboard preview text and does not contain `无需登录，先体验工作台`.

---

### Task 2: Add Compact Header Support to LoginModal

**Files:**
- Modify: `frontend/src/components/business/LoginModal.vue:4-7`
- Modify: `frontend/src/components/business/LoginModal.vue:589-592`

- [ ] **Step 1: Add `hideHeader` prop**

In `frontend/src/components/business/LoginModal.vue`, replace:

```js
const props = defineProps({
  visible: Boolean,
  embedded: { type: Boolean, default: false }
})
```

with:

```js
const props = defineProps({
  visible: Boolean,
  embedded: { type: Boolean, default: false },
  hideHeader: { type: Boolean, default: false }
})
```

- [ ] **Step 2: Hide embedded header when requested**

In the embedded template at the top of `LoginModal.vue`, replace:

```vue
    <div class="mb-6">
      <h3 class="text-xl font-semibold text-foreground">{{ isRegister ? '创建账号' : '欢迎回来' }}</h3>
      <p class="text-sm text-muted-foreground mt-1">{{ isRegister ? '注册后即可使用全部功能' : '登录以访问你的面试题库' }}</p>
    </div>
```

with:

```vue
    <div v-if="!hideHeader" class="mb-6">
      <h3 class="text-xl font-semibold text-foreground">{{ isRegister ? '创建账号' : '欢迎回来' }}</h3>
      <p class="text-sm text-muted-foreground mt-1">{{ isRegister ? '注册后即可使用全部功能' : '登录以访问你的面试题库' }}</p>
    </div>
```

---

### Task 3: Replace LoginPage with Minimal Centered Layout

**Files:**
- Modify: `frontend/src/components/business/LoginPage.vue`

- [ ] **Step 1: Replace the entire template**

In `frontend/src/components/business/LoginPage.vue`, replace the current `<template>...</template>` block with:

```vue
<template>
  <div data-testid="login-page" class="h-dvh overflow-hidden bg-background">
    <main class="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col items-center justify-center px-4 py-4 sm:px-6">
      <section data-testid="login-panel" class="flex w-full max-w-[400px] flex-col items-center">
        <div class="mb-5 flex flex-col items-center text-center">
          <img src="/favicon-b.png" alt="InterviewBoss" class="h-12 w-12 object-contain" />
          <h1 class="mt-3 text-2xl font-semibold tracking-tight text-foreground">InterviewBoss</h1>
          <p class="mt-1 text-sm text-muted-foreground">JD / 面经 / 模拟面试，一处管理</p>
        </div>

        <div class="w-full rounded-xl border border-border bg-card p-5 shadow-sm sm:p-6">
          <div class="mb-5 text-center">
            <h2 class="text-lg font-semibold tracking-tight text-foreground">登录你的面试工作台</h2>
            <p class="mt-1 text-sm text-muted-foreground">继续查看题库、面经和模拟面试记录</p>
          </div>
          <LoginModal embedded hide-header @login-success="$emit('login-success', $event)" />
        </div>

        <a
          href="/master-bank?preview=1"
          class="mt-3 inline-flex h-10 w-full items-center justify-center rounded-md border border-border bg-background text-sm font-medium text-foreground shadow-sm transition hover:bg-muted"
        >
          无需登录，先体验工作台
        </a>

        <div class="mt-4 grid w-full grid-cols-3 gap-2 text-center text-[11px] text-muted-foreground">
          <span class="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">高频题库</span>
          <span class="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">模拟面试</span>
          <span class="rounded-md border border-border/60 bg-muted/40 px-2 py-1.5">复盘进度</span>
        </div>
      </section>
    </main>
  </div>
</template>
```

Keep the existing `<script setup>` block:

```vue
<script setup>
import LoginModal from '@/components/business/LoginModal.vue'

defineEmits(['login-success'])
</script>
```

---

### Task 4: GREEN Verification, Build, and Deploy

**Files:**
- Test/build/deploy only.

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

- [ ] **Step 3: Run browser assertions after deploy**

Run:

```bash
node --input-type=module - <<'JS'
import { chromium } from '@playwright/test'
const browser = await chromium.launch({ headless: true })
for (const size of [{ width: 1280, height: 720 }, { width: 1366, height: 768 }, { width: 390, height: 844 }]) {
  const page = await browser.newPage({ viewport: size })
  await page.goto('http://localhost/login', { waitUntil: 'networkidle' })
  const result = await page.evaluate(() => ({
    viewport: { width: innerWidth, height: innerHeight },
    hasVerticalScroll: document.scrollingElement.scrollHeight > document.scrollingElement.clientHeight,
    hasOldDashboardPreview: document.body.textContent.includes('AI Interview Copilot') || document.body.textContent.includes('题库规模'),
    hasPreviewCta: document.body.textContent.includes('无需登录，先体验工作台'),
    hasBenefitChips: ['高频题库', '模拟面试', '复盘进度'].every(text => document.body.textContent.includes(text)),
    formBottom: document.querySelector('section[data-testid="login-panel"]')?.getBoundingClientRect().bottom ?? null,
    viewportHeight: innerHeight,
    logoSrc: document.querySelector('section[data-testid="login-panel"] img[alt="InterviewBoss"]')?.getAttribute('src'),
  }))
  console.log(JSON.stringify(result))
  if (result.hasVerticalScroll) process.exit(1)
  if (result.hasOldDashboardPreview) process.exit(2)
  if (!result.hasPreviewCta) process.exit(3)
  if (!result.hasBenefitChips) process.exit(4)
  if (result.formBottom === null || result.formBottom > result.viewportHeight) process.exit(5)
  if (result.logoSrc !== '/favicon-b.png') process.exit(6)
  await page.close()
}
await browser.close()
JS
```

Expected: PASS for all three viewports; no old dashboard preview; no vertical scroll; preview CTA and three benefit chips present.

---

### Task 5: Update Docs and Commit

**Files:**
- Modify: `frontend/src/components/business/CLAUDE.md`
- Create: `docs/dev-log/2026-06-22-login-page-minimal-redesign.md`
- Commit all modified files.

- [ ] **Step 1: Update business component instructions**

In `frontend/src/components/business/CLAUDE.md`, replace the existing `LoginPage.vue` viewport bullet:

```markdown
- `LoginPage.vue` 是无 header 的全屏登录壳，必须使用视口高度自适应（如 `h-dvh`/`h-full min-h-0`），不要使用 `calc(100vh-56px)` 这类为主界面 header 预留高度的写法。
```

with:

```markdown
- `LoginPage.vue` 是无 header 的全屏登录壳，使用极简居中品牌区 + 登录卡片 + “无需登录，先体验工作台”入口 + 三个短卖点；必须视口高度自适应（如 `h-dvh`/`h-full min-h-0`），不要使用 `calc(100vh-56px)` 或复杂 dashboard preview。
```

- [ ] **Step 2: Add development log**

Create `docs/dev-log/2026-06-22-login-page-minimal-redesign.md` with:

```markdown
# 2026-06-22 Login Page Minimal Redesign

## Research Summary

Light Exa research on AI interview and SaaS login/entry pages showed that comparable products emphasize a clear product name/logo, a short value statement, low-friction login, and a free/no-login trial or preview CTA. Dense dashboard previews are better suited to marketing pages than compact auth screens.

## Change

- Replaced the dense split login page with a centered InterviewBoss brand area, login card, no-login preview CTA, and three short benefit chips.
- Added `hideHeader` to `LoginModal` embedded mode so the login page controls the visual hierarchy and keeps the form compact.
- Kept existing password/email login behavior and the `/master-bank?preview=1` preview route.

## Verification

- Ran a Playwright RED assertion against the old deployed page to confirm it still had dashboard preview text and lacked the new CTA.
- Ran `cd frontend && npm run build`.
- Ran `./deploy/docker-deploy.sh frontend`.
- Verified with Playwright that `/login` has no vertical scroll at 1280×720, 1366×768, and 390×844; old dashboard preview text is gone; the preview CTA and benefit chips are present.
```

- [ ] **Step 3: Commit on master**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss status --short --branch
git -C /home/ubuntu/sj/interview-boss add frontend/src/components/business/LoginPage.vue frontend/src/components/business/LoginModal.vue frontend/src/components/business/CLAUDE.md docs/dev-log/2026-06-22-login-page-minimal-redesign.md docs/superpowers/plans/2026-06-22-login-page-minimal-redesign.md
git -C /home/ubuntu/sj/interview-boss commit -m "fix(frontend): simplify login page layout" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: commit succeeds on `master`.

---

## Self-Review

- Spec coverage: Covers simplified visual design, no-login preview CTA, three benefit chips, compact LoginModal header, viewport verification, docs, deploy, and commit.
- Placeholder scan: No placeholders or vague instructions remain.
- Type consistency: New prop is named `hideHeader` in code and used as `hide-header` in template, matching Vue prop casing conventions.
