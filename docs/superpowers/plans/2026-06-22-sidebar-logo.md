# Sidebar Logo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the main workspace sidebar top-left text logo (`IB`) with the existing square favicon image at `/favicon-b.png`.

**Architecture:** Keep the current sidebar component structure and collapse/expand behavior. Only change the visual content inside the two existing logo containers in `AppSidebar.vue`; do not introduce new components, new assets, or new navigation behavior.

**Tech Stack:** Vue 3 `<script setup>`, Tailwind CSS utility classes, Vite public asset serving (`frontend/public/favicon-b.png` is served as `/favicon-b.png`).

---

## File Structure

- Modify: `frontend/src/components/AppSidebar.vue`
  - Responsibility: sidebar navigation, collapsed/expanded header, user menu.
  - Change: replace the visible `IB` text in both collapsed and expanded logo blocks with an `<img>` that points to `/favicon-b.png`.
- No new files.
- No `README.md` update required because this does not add a route, service, business component, API endpoint, dependency, environment variable, or deployment behavior.
- No `frontend/src/components/CLAUDE.md` update required because component inventory and responsibilities do not change.

---

### Task 1: Replace Sidebar Logo Mark

**Files:**
- Modify: `frontend/src/components/AppSidebar.vue:83-94`
- Modify: `frontend/src/components/AppSidebar.vue:141-144`

- [ ] **Step 1: Write the smallest visual assertion before implementation**

Create a temporary grep-based check that describes the desired state: the sidebar component should reference `/favicon-b.png` and should not render the old `IB` text inside the logo mark containers.

Run:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path('frontend/src/components/AppSidebar.vue')
s = p.read_text()
assert '/favicon-b.png' in s, 'expected AppSidebar.vue to use /favicon-b.png for the sidebar logo'
assert '>IB</span>' not in s, 'expected collapsed logo not to render IB text'
assert '>IB\n        </div>' not in s, 'expected expanded logo not to render IB text'
PY
```

Expected: FAIL with `AssertionError: expected AppSidebar.vue to use /favicon-b.png for the sidebar logo`.

- [ ] **Step 2: Replace the collapsed logo text**

In `frontend/src/components/AppSidebar.vue`, replace the collapsed logo `<span>` inside the button with this image:

```vue
        <img
          src="/favicon-b.png"
          alt="InterviewBoss"
          class="h-7 w-7 object-contain transition-all duration-300 ease-out"
          :class="logoHovered ? 'opacity-0 scale-75' : 'opacity-100 scale-100'"
        />
```

Keep the existing hover behavior where the logo fades out and the `PanelLeft` icon fades in.

- [ ] **Step 3: Replace the expanded logo text**

In `frontend/src/components/AppSidebar.vue`, replace the expanded logo container content:

```vue
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary-600 text-sm font-bold text-white shadow-lg shadow-primary/20 transition-transform hover:scale-105">
          IB
        </div>
```

with:

```vue
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary-600 shadow-lg shadow-primary/20 transition-transform hover:scale-105 overflow-hidden">
          <img src="/favicon-b.png" alt="InterviewBoss" class="h-8 w-8 object-contain" />
        </div>
```

- [ ] **Step 4: Run the visual assertion again**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path('frontend/src/components/AppSidebar.vue')
s = p.read_text()
assert '/favicon-b.png' in s, 'expected AppSidebar.vue to use /favicon-b.png for the sidebar logo'
assert '>IB</span>' not in s, 'expected collapsed logo not to render IB text'
assert '>IB\n        </div>' not in s, 'expected expanded logo not to render IB text'
PY
```

Expected: PASS with no output.

- [ ] **Step 5: Build frontend**

Run:

```bash
cd frontend && npm run build
```

Expected: command exits 0 and Vite reports a successful production build.

- [ ] **Step 6: Update development log**

Create a dated dev log file because user memory requires every development session to be recorded under `docs/dev-log/`.

File: `docs/dev-log/2026-06-22-sidebar-logo.md`

Content:

```markdown
# 2026-06-22 Sidebar Logo

## Change

- Replaced the sidebar top-left text mark `IB` with the existing square favicon asset `/favicon-b.png`.

## Verification

- Ran a grep-based assertion confirming `AppSidebar.vue` references `/favicon-b.png` and no longer renders the old logo text in the sidebar logo containers.
- Ran `cd frontend && npm run build`.
```

- [ ] **Step 7: Deploy frontend and verify production**

Run:

```bash
./deploy/docker-deploy.sh frontend
```

Expected: frontend deploy script exits 0.

Then verify in the browser or with the project verification flow that the main workspace sidebar top-left logo displays the same square logo as the browser tab.

- [ ] **Step 8: Commit**

After deploy and production verification succeed, commit the logical change immediately.

Run:

```bash
git add frontend/src/components/AppSidebar.vue docs/dev-log/2026-06-22-sidebar-logo.md
git commit -m "fix(frontend): use favicon asset for sidebar logo"
```

Expected: commit succeeds with a Conventional Commit message.

---

## Self-Review

- Spec coverage: The plan covers only the confirmed requirement: use the current browser tab square logo (`/favicon-b.png`) as the main workspace sidebar top-left logo.
- Placeholder scan: No placeholders, TBDs, or vague implementation steps remain.
- Type/property consistency: The plan only uses existing Vue/Tailwind patterns and does not introduce new props, methods, or imports.
