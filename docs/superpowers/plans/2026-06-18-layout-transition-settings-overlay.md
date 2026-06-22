# Layout Transition and Settings Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. User explicitly requested no subagents and no commit.

**Goal:** Remove transient scrollbar flicker during main tab switches and render Settings as an overlay above the current workspace instead of replacing it.

**Architecture:** Keep the existing Vue Router layout in `AuthenticatedLayout.vue`. Use Vue Transition `mode="out-in"` and remove absolute-positioned leave layout so old and new route views do not compete for scroll geometry. Render `SettingsPage` as a fixed overlay after the workspace shell, preserving the current route and page state underneath.

**Tech Stack:** Vue 3 `<script setup>`, Vue Router, Tailwind CSS, Playwright, Vite, Docker nginx frontend deploy.

---

## File Structure

- Modify: `frontend/src/layouts/AuthenticatedLayout.vue`
  - Keep login gate unchanged.
  - Keep workspace shell rendered whenever authenticated.
  - Move `SettingsPage` out of the `v-else-if` replacement branch and into a fixed overlay.
  - Change route transition to `mode="out-in"` and remove absolute leave CSS.
- Temporary test only: `/tmp/playwright-test-layout-settings-overlay.js`
  - Proves current behavior fails first.
  - Then proves final behavior passes after implementation.

---

### Task 1: Write failing Playwright verification

**Files:**
- Create temporary: `/tmp/playwright-test-layout-settings-overlay.js`

- [ ] **Step 1: Write the failing test**

Create a Playwright script that:
1. Opens `http://localhost/jd?preview=1`.
2. Captures the current route and visible JD content.
3. Clicks the header settings button.
4. Asserts the URL remains `/jd?preview=1`.
5. Asserts the workspace shell still exists underneath the settings overlay.
6. Asserts the settings page is fixed-position overlay.
7. Switches between JD, Interview, and MasterBank and samples document scroll width/height to catch transient document overflow.

Expected before code changes: fail because `SettingsPage` replaces the workspace shell.

- [ ] **Step 2: Run failing test**

Run from actual Playwright skill directory:

```bash
cd /home/ubuntu/.claude/skills/playwright-skill/skills/playwright-skill
xvfb-run -a env TARGET_URL=http://localhost node run.js /tmp/playwright-test-layout-settings-overlay.js
```

Expected: FAIL with a message showing the workspace shell is not still rendered under settings.

---

### Task 2: Implement layout fix

**Files:**
- Modify: `frontend/src/layouts/AuthenticatedLayout.vue`

- [ ] **Step 1: Update settings rendering**

Change the top-level template so authenticated workspace shell is always rendered when `isAuthenticatedForUi` is true. Remove the `v-else-if="showSettingsPage"` branch that replaces the app shell. Add SettingsPage later as fixed overlay:

```vue
<SettingsPage
  v-if="showSettingsPage"
  class="fixed inset-0 z-[80]"
  :display-user="displayUser"
  :practice-stats="practiceStats"
  :master-bank="masterBank"
  :is-admin="displayUser?.is_admin"
  :active-season="activeSeason"
  :available-seasons="availableSeasons"
  :is-building="isBuilding"
  @close="showSettingsPage = false"
  @go-to-question="onGoToQuestion"
  @logout="handleLogout"
  @bank-mode-changed="handleBankModeChanged"
  @profile-updated="fetchTableData"
  @build-master-bank="triggerBuildMasterBank"
  @update:active-season="activeSeason = $event"
  @sidebar-collapsed-changed="sidebarCollapsed = $event"
/>
```

- [ ] **Step 2: Update route transition**

Change:

```vue
<Transition name="tab-fade" class="h-full">
```

to:

```vue
<Transition name="tab-fade" mode="out-in">
```

Keep component class as:

```vue
<component :is="Component" class="h-full min-h-0" />
```

- [ ] **Step 3: Simplify transition CSS**

Replace:

```css
.tab-fade-enter-active { transition: opacity 0.25s cubic-bezier(0.25, 0.46, 0.45, 0.94); }
.tab-fade-leave-active { transition: opacity 0.15s ease-in; position: absolute; width: 100%; }
.tab-fade-enter-from { opacity: 0; }
.tab-fade-leave-to { opacity: 0; }
```

with:

```css
.tab-fade-enter-active,
.tab-fade-leave-active { transition: opacity 0.16s ease; }
.tab-fade-enter-from,
.tab-fade-leave-to { opacity: 0; }
```

---

### Task 3: Verify

- [ ] **Step 1: Run Playwright test again**

```bash
cd /home/ubuntu/.claude/skills/playwright-skill/skills/playwright-skill
xvfb-run -a env TARGET_URL=http://localhost node run.js /tmp/playwright-test-layout-settings-overlay.js
```

Expected: PASS.

- [ ] **Step 2: Build frontend**

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build
```

Expected: `✓ built`.

- [ ] **Step 3: Deploy frontend to Docker nginx**

```bash
cd /home/ubuntu/sj/interview-boss && ./deploy/docker-deploy.sh frontend
```

Expected: frontend copied and chmod applied.

- [ ] **Step 4: Check Docker entry**

```bash
curl -I http://localhost/
```

Expected: `HTTP/1.1 200 OK`.

- [ ] **Step 5: Run final Playwright verification against Docker**

Run the same Playwright script against `http://localhost` after Docker deploy.

Expected: PASS.

---

## Self-Review

- Spec coverage: tab flicker and settings overlay both covered in `AuthenticatedLayout.vue`.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: uses existing `showSettingsPage`, `SettingsPage`, and existing event bindings unchanged.
- Scope: no route changes, no new components, no unrelated dirty files, no commit.
