# Login Copy Refine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generic login-page copy with the approved concise Chinese copy style and remove redundant explanatory labels.

**Architecture:** Keep the existing `LoginPage.vue` and `LoginModal.vue` structure. Change only visible copy and remove redundant visual chips from the login page; no auth logic changes.

**Tech Stack:** Vue 3 `<script setup>`, Tailwind CSS, Vite build, Playwright browser assertions, Docker frontend deploy script.

---

## File Structure

- Modify: `frontend/src/components/business/LoginPage.vue`
  - Change card title to `欢迎回来`.
  - Remove subtitle `继续查看题库、面经和模拟面试记录`.
  - Change preview CTA to `免登录体验`.
  - Remove the three bottom chips: `高频题库` / `模拟面试` / `复盘进度`.
- Modify: `frontend/src/components/business/LoginModal.vue`
  - Change login tab copy from `邮箱验证码` to `验证码登录`.
  - Keep `密码登录`.
  - Change register prompt to `还没有账号？立即注册`.
- Modify: `frontend/src/components/business/CLAUDE.md`
  - Document current login page copy rules.
- Create: `docs/dev-log/2026-06-22-login-copy-refine.md`
  - Record design rationale and verification.

---

### Task 1: RED Browser Assertion

**Files:**
- Test only: Playwright one-off command.

- [ ] **Step 1: Run assertion against current deployed page**

Run:

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm ci && node --input-type=module - <<'JS'
import { chromium } from '@playwright/test'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
await page.goto('http://localhost/login', { waitUntil: 'networkidle' })
const text = await page.locator('body').innerText()
await browser.close()
const result = {
  hasNewTitle: text.includes('欢迎回来'),
  hasOldTitle: text.includes('登录你的面试工作台'),
  hasOldSubtitle: text.includes('继续查看题库、面经和模拟面试记录'),
  hasPasswordTab: text.includes('密码登录'),
  hasEmailTab: text.includes('验证码登录'),
  hasOldEmailTab: text.includes('邮箱验证码'),
  hasRegisterPrompt: text.includes('还没有账号？立即注册'),
  hasPreviewCta: text.includes('免登录体验'),
  hasOldPreviewCta: text.includes('无需登录，先体验工作台'),
  hasChips: ['高频题库', '模拟面试', '复盘进度'].some(t => text.includes(t)),
}
console.log(JSON.stringify(result))
if (!result.hasNewTitle) process.exit(1)
if (result.hasOldTitle || result.hasOldSubtitle) process.exit(2)
if (!result.hasPasswordTab || !result.hasEmailTab || result.hasOldEmailTab) process.exit(3)
if (!result.hasRegisterPrompt) process.exit(4)
if (!result.hasPreviewCta || result.hasOldPreviewCta) process.exit(5)
if (result.hasChips) process.exit(6)
JS
```

Expected before implementation: FAIL because old title/subtitle/tabs/CTA/chips are still present.

---

### Task 2: Implement Approved Copy

**Files:**
- Modify: `frontend/src/components/business/LoginPage.vue`
- Modify: `frontend/src/components/business/LoginModal.vue`

- [ ] **Step 1: Update LoginPage copy and remove chips**

In `LoginPage.vue`:

- Replace `登录你的面试工作台` with `欢迎回来`.
- Delete the subtitle paragraph containing `继续查看题库、面经和模拟面试记录`.
- Replace `无需登录，先体验工作台` with `免登录体验`.
- Delete the bottom chips block containing `高频题库` / `模拟面试` / `复盘进度`.

- [ ] **Step 2: Update LoginModal tab/register copy**

In `LoginModal.vue`:

- Replace the tab text `邮箱验证码` with `验证码登录`.
- Replace `没有账号？注册一个` with `还没有账号？立即注册`.

---

### Task 3: Verify, Deploy, Docs, Commit

**Files:**
- Modify: `frontend/src/components/business/CLAUDE.md`
- Create: `docs/dev-log/2026-06-22-login-copy-refine.md`

- [ ] **Step 1: Build frontend**

Run:

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build
```

Expected: pass.

- [ ] **Step 2: Deploy frontend**

Run:

```bash
/home/ubuntu/sj/interview-boss/deploy/docker-deploy.sh frontend
```

Expected: pass.

- [ ] **Step 3: Run GREEN browser assertion**

Run the same Playwright assertion from Task 1.

Expected: pass.

- [ ] **Step 4: Update docs and commit**

Update docs and commit:

```bash
git -C /home/ubuntu/sj/interview-boss add frontend/src/components/business/LoginPage.vue frontend/src/components/business/LoginModal.vue frontend/src/components/business/CLAUDE.md docs/dev-log/2026-06-22-login-copy-refine.md docs/superpowers/plans/2026-06-22-login-copy-refine.md
git -C /home/ubuntu/sj/interview-boss commit -m "fix(frontend): refine login copy" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: Covers approved Scheme C copy: `欢迎回来`, `密码登录`, `验证码登录`, `还没有账号？立即注册`, `免登录体验`, and deletion of redundant subtitle/chips.
- Placeholder scan: No placeholders or vague instructions remain.
- Type consistency: Only visible Vue template copy changes; no data/API changes.
