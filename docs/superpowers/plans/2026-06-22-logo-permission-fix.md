# Logo Permission Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore `/favicon-b.png` in production and prevent future deploys from serving static assets with unreadable file permissions.

**Architecture:** Fix the source file mode for `frontend/public/favicon-b.png`, then harden the nginx Docker image build by running `chmod -R a+rX /usr/share/nginx/html` after copying frontend dist. Keep the existing deploy script chmod for fast frontend deploys; the Dockerfile hardening covers full `update` builds where the broken permission currently propagates.

**Tech Stack:** Vite public assets, Docker multi-stage build, nginx static hosting, curl verification, shell permission checks.

---

## File Structure

- Modify file mode: `frontend/public/favicon-b.png`
  - Change mode from `0600` to `0644` so it is world-readable when copied into nginx.
- Modify: `Dockerfile`
  - After copying frontend `dist` into nginx image, run `chmod -R a+rX /usr/share/nginx/html`.
- Modify: `deploy/CLAUDE.md`
  - Document that nginx image builds and fast frontend deploys must leave `/usr/share/nginx/html` readable by nginx.
- Create: `docs/dev-log/2026-06-22-logo-permission-fix.md`
  - Record root cause, fix, and verification.
- Create: `docs/superpowers/plans/2026-06-22-logo-permission-fix.md`
  - This plan.

---

### Task 1: RED Verification

**Files:**
- Test only: shell/curl checks.

- [ ] **Step 1: Verify deployed asset currently fails**

Run:

```bash
curl -s -o /tmp/favicon-b.out -w '%{http_code}\n' http://localhost/favicon-b.png
```

Expected before fix: `403`.

- [ ] **Step 2: Verify source permission is too strict**

Run:

```bash
stat -c '%a %n' /home/ubuntu/sj/interview-boss/frontend/public/favicon-b.png
```

Expected before fix: `600 /home/ubuntu/sj/interview-boss/frontend/public/favicon-b.png`.

---

### Task 2: GREEN Implementation

**Files:**
- Modify file mode: `frontend/public/favicon-b.png`
- Modify: `Dockerfile:115-119`

- [ ] **Step 1: Fix source file mode**

Run:

```bash
chmod 644 /home/ubuntu/sj/interview-boss/frontend/public/favicon-b.png
```

Expected:

```bash
stat -c '%a %n' /home/ubuntu/sj/interview-boss/frontend/public/favicon-b.png
# 644 /home/ubuntu/sj/interview-boss/frontend/public/favicon-b.png
```

- [ ] **Step 2: Harden nginx image permissions**

In `Dockerfile`, replace:

```dockerfile
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html
EXPOSE 80
```

with:

```dockerfile
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 80
```

---

### Task 3: Deploy and Verify

**Files:**
- Test/deploy only.

- [ ] **Step 1: Run full deploy through project script**

Run:

```bash
/home/ubuntu/sj/interview-boss/deploy/docker-deploy.sh update
```

If disk is below the default 4GB threshold after safe cleanup, use the documented threshold environment variables only after confirming enough space for this small build:

```bash
DEPLOY_MIN_FREE_MB=3500 DEPLOY_TARGET_FREE_MB=3500 /home/ubuntu/sj/interview-boss/deploy/docker-deploy.sh update
```

Expected: backend and nginx are rebuilt and healthy.

- [ ] **Step 2: Verify deployed logo returns 200**

Run:

```bash
curl -s -I http://localhost/favicon-b.png
```

Expected includes:

```text
HTTP/1.1 200 OK
Content-Type: image/png
```

- [ ] **Step 3: Verify nginx file permissions**

Run:

```bash
docker compose exec nginx sh -lc 'ls -l /usr/share/nginx/html/favicon-b.png'
```

Expected mode is readable by others, e.g. `-rw-r--r--`.

- [ ] **Step 4: Verify browser image loading**

Run a browser check against `/login` and assert the logo natural size is non-zero:

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm ci && node --input-type=module - <<'JS'
import { chromium } from '@playwright/test'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
await page.goto('http://localhost/login', { waitUntil: 'networkidle' })
const result = await page.evaluate(() => {
  const img = document.querySelector('img[src="/favicon-b.png"]')
  return { found: Boolean(img), complete: img?.complete ?? false, naturalWidth: img?.naturalWidth ?? 0 }
})
await browser.close()
console.log(JSON.stringify(result))
if (!result.found || !result.complete || result.naturalWidth <= 0) process.exit(1)
JS
```

Expected: command exits 0 and logs `naturalWidth` greater than 0.

---

### Task 4: Docs and Commit

**Files:**
- Modify: `deploy/CLAUDE.md`
- Create: `docs/dev-log/2026-06-22-logo-permission-fix.md`
- Commit all tracked source/docs changes.

- [ ] **Step 1: Update deploy docs**

Add/adjust the deploy rule to state:

```markdown
- Nginx 静态资源权限必须可被 worker 读取：Dockerfile 的 nginx-runtime 阶段在复制 dist 后执行 `chmod -R a+rX /usr/share/nginx/html`；`frontend` 快速部署也必须在 `docker cp` 后执行同样 chmod，避免宿主机 `0600` 图片进入容器后变成 403。
```

- [ ] **Step 2: Add dev log**

Create `docs/dev-log/2026-06-22-logo-permission-fix.md` describing root cause and verification.

- [ ] **Step 3: Commit**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss add Dockerfile deploy/CLAUDE.md frontend/public/favicon-b.png docs/dev-log/2026-06-22-logo-permission-fix.md docs/superpowers/plans/2026-06-22-logo-permission-fix.md
git -C /home/ubuntu/sj/interview-boss commit -m "fix(deploy): make nginx static assets readable" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: Covers current 403 logo root cause, source file mode, Docker full-build hardening, existing fast deploy chmod contract, deployment, HTTP/browser verification, docs, and commit.
- Placeholder scan: No placeholders or vague steps remain.
- Type consistency: File paths and commands match the current repo layout and Docker/nginx deployment model.
