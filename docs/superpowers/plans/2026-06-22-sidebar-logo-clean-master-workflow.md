# Sidebar Logo Cleanup and Master Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the blue visual wrapper from the sidebar logo and document that routine project edits should be committed directly on `master` because the project is single-maintainer.

**Architecture:** Keep `AppSidebar.vue` structure and hover-to-toggle interaction unchanged. Change only the logo container classes to remove the primary gradient and primary shadow; update root `CLAUDE.md` to override the default branch-creation habit for this project.

**Tech Stack:** Vue 3 `<script setup>`, Tailwind CSS, Markdown project instructions, git.

---

## File Structure

- Modify: `frontend/src/components/AppSidebar.vue`
  - Remove blue gradient/shadow classes from both collapsed and expanded logo containers.
  - Preserve `/favicon-b.png`, dimensions, alt text, and hover `PanelLeft` behavior.
- Modify: `frontend/src/components/CLAUDE.md`
  - Adjust the logo rule to say the sidebar logo should use `/favicon-b.png` without a colored wrapper.
- Modify: `CLAUDE.md`
  - Add project-specific git workflow: routine edits go directly on `master`; only create branches/PRs/worktrees when explicitly requested.
- Create: `docs/dev-log/2026-06-22-sidebar-logo-cleanup-master-workflow.md`
  - Record what changed and how it was verified.

---

### Task 1: Bring Previous Sidebar Logo Commit Back to Master

**Files:**
- Git history only.

- [ ] **Step 1: Verify current branch**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss status --short --branch
```

Expected: current branch is `fix/sidebar-favicon-logo` and worktree has no tracked uncommitted changes.

- [ ] **Step 2: Switch to master**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss checkout master
```

Expected: branch switches to `master`.

- [ ] **Step 3: Cherry-pick previous sidebar logo commit**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss cherry-pick 7aeb0dc
```

Expected: commit applies cleanly to `master`.

---

### Task 2: Remove Blue Logo Wrapper

**Files:**
- Modify: `frontend/src/components/AppSidebar.vue:78-81`
- Modify: `frontend/src/components/AppSidebar.vue:144-146`

- [ ] **Step 1: Write failing assertion**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
s = Path('/home/ubuntu/sj/interview-boss/frontend/src/components/AppSidebar.vue').read_text()
assert '/favicon-b.png' in s, 'sidebar logo should still use /favicon-b.png'
assert 'bg-gradient-to-br from-primary to-primary-600' not in s, 'sidebar logo should not use blue gradient wrapper'
assert 'shadow-primary/20' not in s, 'sidebar logo should not use primary-colored shadow wrapper'
PY
```

Expected: FAIL because the current sidebar logo containers still include blue gradient/shadow classes.

- [ ] **Step 2: Update collapsed logo button classes**

In `frontend/src/components/AppSidebar.vue`, replace:

```vue
        class="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-all duration-300 mb-1 overflow-hidden"
        :class="logoHovered
          ? 'bg-sidebar-accent text-sidebar-foreground cursor-pointer'
          : 'bg-gradient-to-br from-primary to-primary-600 text-white shadow-lg shadow-primary/20'"
```

with:

```vue
        class="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-all duration-300 mb-1 overflow-hidden"
        :class="logoHovered
          ? 'bg-sidebar-accent text-sidebar-foreground cursor-pointer'
          : 'bg-transparent text-sidebar-foreground'"
```

- [ ] **Step 3: Update expanded logo container classes**

In `frontend/src/components/AppSidebar.vue`, replace:

```vue
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary-600 shadow-lg shadow-primary/20 transition-transform hover:scale-105 overflow-hidden">
          <img src="/favicon-b.png" alt="InterviewBoss" class="h-8 w-8 object-contain" />
        </div>
```

with:

```vue
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-transform hover:scale-105 overflow-hidden">
          <img src="/favicon-b.png" alt="InterviewBoss" class="h-8 w-8 object-contain" />
        </div>
```

- [ ] **Step 4: Run passing assertion**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
s = Path('/home/ubuntu/sj/interview-boss/frontend/src/components/AppSidebar.vue').read_text()
assert '/favicon-b.png' in s, 'sidebar logo should still use /favicon-b.png'
assert 'bg-gradient-to-br from-primary to-primary-600' not in s, 'sidebar logo should not use blue gradient wrapper'
assert 'shadow-primary/20' not in s, 'sidebar logo should not use primary-colored shadow wrapper'
PY
```

Expected: PASS with no output.

---

### Task 3: Document Master Workflow and Logo Rule

**Files:**
- Modify: `CLAUDE.md:37-44`
- Modify: `frontend/src/components/CLAUDE.md`

- [ ] **Step 1: Update root CLAUDE.md git workflow**

In `CLAUDE.md`, under `## 核心规范`, add this bullet after the existing Commit bullet:

```markdown
- **Git 工作流**：本项目由用户单人维护。除非用户明确要求创建分支、PR 或 worktree，日常修改直接在 `master` 上进行并提交；不要为了常规改动自动创建 feature branch。
```

- [ ] **Step 2: Update components CLAUDE.md logo rule**

In `frontend/src/components/CLAUDE.md`, replace:

```markdown
- 侧边栏品牌标识统一使用现有方形 favicon 资源 `/favicon-b.png`，不要再用文字 `IB` 作为主 logo。
```

with:

```markdown
- 侧边栏品牌标识统一使用现有方形 favicon 资源 `/favicon-b.png`，不要再用文字 `IB` 或蓝色背景包裹作为主 logo。
```

- [ ] **Step 3: Add development log**

Create `docs/dev-log/2026-06-22-sidebar-logo-cleanup-master-workflow.md` with:

```markdown
# 2026-06-22 Sidebar Logo Cleanup and Master Workflow

## Change

- Removed the blue gradient/shadow wrapper around the sidebar favicon logo.
- Documented that routine project edits should be committed directly on `master` because the project is single-maintainer.

## Verification

- Ran a grep-based assertion confirming `AppSidebar.vue` still references `/favicon-b.png` and no longer contains the primary gradient/shadow wrapper classes.
- Ran `cd frontend && npm run build`.
- Ran `./deploy/docker-deploy.sh frontend`.
```

---

### Task 4: Build, Deploy, and Commit on Master

**Files:**
- All modified files from prior tasks.

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

- [ ] **Step 3: Commit on master**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss status --short --branch
git -C /home/ubuntu/sj/interview-boss add CLAUDE.md frontend/src/components/AppSidebar.vue frontend/src/components/CLAUDE.md docs/dev-log/2026-06-22-sidebar-logo-cleanup-master-workflow.md docs/superpowers/plans/2026-06-22-sidebar-logo-cleanup-master-workflow.md
git -C /home/ubuntu/sj/interview-boss commit -m "fix(frontend): remove sidebar logo wrapper" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: commit succeeds on `master`.

---

## Self-Review

- Spec coverage: Covers logo wrapper removal, root CLAUDE.md master workflow instruction, component CLAUDE.md logo rule, build, deploy, and commit.
- Placeholder scan: No placeholders or vague instructions remain.
- Type consistency: No new functions, props, or types are introduced.
