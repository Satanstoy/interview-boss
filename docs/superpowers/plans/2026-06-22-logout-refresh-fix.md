# Logout Refresh Persistence Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure clicking logout invalidates the backend refresh token cookie so a browser refresh cannot automatically log the user back in.

**Architecture:** Centralize logout side effects in `useAuth.handleLogout()`: call `/api/auth/logout`, then always clear local access token and user state. Make cookie-aware fetches include the CSRF header expected by the backend, and make backend logout idempotently clear the refresh cookie even when the cookie is missing or invalid.

**Tech Stack:** Vue 3 composables/services, FastAPI, HttpOnly refresh cookie, pytest via Docker backend container, Vite build, Playwright/curl verification, Docker deploy script.

---

## File Structure

- Modify: `frontend/src/services/http.js`
  - Add `X-Requested-With: XMLHttpRequest` to `fetchWithCredentials()` so logout passes backend CSRF checks.
- Modify: `frontend/src/services/authApi.js`
  - Make `authLogout()` inspect non-2xx responses instead of silently treating 403 as success.
- Modify: `frontend/src/composables/useAuth.js`
  - Import `authLogout()` and centralize real logout in `handleLogout()`.
- Modify: `frontend/src/components/business/UserMenu.vue`
  - Remove duplicate API/local token clearing; emit logout and let the parent/composable run the unified flow.
- Modify: `backend/app/routers/auth.py`
  - Make `/api/auth/logout` read the refresh cookie directly and always clear the cookie after CSRF passes.
- Temporarily add backend tests under `backend/tests/` for RED/GREEN verification only
  - Cover logout CSRF behavior, idempotent no-cookie logout, logout invalidating refresh, and logout invalidating refresh-token family.
  - Remove the temporary test file before commit because this project does not commit test files.
- Modify docs:
  - `frontend/src/services/CLAUDE.md`
  - `frontend/src/composables/CLAUDE.md`
  - `backend/app/routers/CLAUDE.md`
  - `docs/dev-log/2026-06-22-logout-refresh-fix.md`

---

### Task 1: Backend RED Tests

**Files:**
- Test: `backend/tests/auth/test_logout_refresh.py`

- [ ] **Step 1: Write failing backend tests**

Create `backend/tests/auth/test_logout_refresh.py` with tests that:

```python
import pytest
from fastapi.testclient import TestClient


def test_logout_without_csrf_header_is_rejected(client: TestClient):
    response = client.post("/api/auth/logout", cookies={"refresh_token": "dummy"})

    assert response.status_code == 403


def test_logout_without_cookie_is_idempotent_when_csrf_header_present(client: TestClient):
    response = client.post(
        "/api/auth/logout",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert "refresh_token" in response.headers.get("set-cookie", "")
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_logout_clears_refresh_cookie_and_prevents_refresh(client: TestClient):
    email = "logout-refresh@example.com"
    password = "TestPassword123!"
    register_response = client.post(
        "/api/auth/register",
        json={"username": "logout_refresh_user", "password": password, "email": email},
    )
    assert register_response.status_code == 200
    assert client.cookies.get("refresh_token")

    logout_response = client.post(
        "/api/auth/logout",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    assert logout_response.status_code == 200
    assert client.cookies.get("refresh_token") is None

    refresh_response = client.post(
        "/api/auth/refresh",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert refresh_response.status_code == 401
```

- [ ] **Step 2: Run RED test**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/auth/test_logout_refresh.py -q
```

Expected before implementation: `test_logout_without_cookie_is_idempotent_when_csrf_header_present` fails with 401 because `get_refresh_token` runs before cookie clearing.

---

### Task 2: Backend GREEN Implementation

**Files:**
- Modify: `backend/app/routers/auth.py:355-366`

- [ ] **Step 1: Make logout idempotent**

Replace the logout route with:

```python
@router.post("/logout")
async def logout(request: Request, response: Response, _csrf: None = Depends(_require_custom_header)):
    """注销：删除 refresh token，清除 cookie。幂等：无 cookie 也返回成功。"""
    rt = request.cookies.get("refresh_token")
    if rt:
        try:
            payload = decode_token(rt, expected_type="refresh")
            jti = payload.get("jti")
            if jti:
                delete_refresh_token(jti)
        except HTTPException:
            pass  # Token 可能已过期或无效，仍需清除 cookie
    _clear_refresh_cookie(response, request)
    return {"status": "success"}
```

- [ ] **Step 2: Run backend logout tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/auth/test_logout_refresh.py -q
```

Expected: all tests pass.

---

### Task 3: Frontend RED Browser/API Check

**Files:**
- Test only: one-off browser/curl verification.

- [ ] **Step 1: Confirm current logout without CSRF header fails**

Run:

```bash
curl -s -i -X POST http://localhost/api/auth/logout -H 'Cookie: refresh_token=dummy' | tr -d '\r' | sed -n '1,8p'
```

Expected before frontend implementation: `HTTP/1.1 403 Forbidden`.

---

### Task 4: Frontend GREEN Implementation

**Files:**
- Modify: `frontend/src/services/http.js:587-595`
- Modify: `frontend/src/services/authApi.js:11-15`
- Modify: `frontend/src/composables/useAuth.js:10-55`
- Modify: `frontend/src/components/business/UserMenu.vue:95-154`

- [ ] **Step 1: Add CSRF header to cookie-aware fetch**

In `frontend/src/services/http.js`, replace `fetchWithCredentials()` with:

```js
export async function fetchWithCredentials(url, options = {}) {
  const token = getAuthToken()
  const authHeaders = { 'X-Requested-With': 'XMLHttpRequest' }
  if (token) authHeaders['Authorization'] = `Bearer ${token}`
  return fetch(url, {
    ...options,
    credentials: 'include',
    headers: { ...authHeaders, ...(options.headers || {}) },
  })
}
```

- [ ] **Step 2: Make authLogout inspect non-2xx responses**

In `frontend/src/services/authApi.js`, replace `authLogout()` with:

```js
export const authLogout = async () => {
  try {
    const response = await fetchWithCredentials(`${API}/auth/logout`, { method: 'POST' })
    return response.ok
  } catch {
    return false
  }
}
```

- [ ] **Step 3: Centralize backend logout in useAuth**

In `frontend/src/composables/useAuth.js`, add `authLogout` import:

```js
import { authLogout } from '@/api/index.js'
```

Then replace `handleLogout()` with:

```js
const handleLogout = async () => {
  try {
    await authLogout()
  } finally {
    setAuthToken('')
    currentUser.value = null
    _onDataRefresh?.()
    pendingReviewCount.value = 0
  }
}
```

- [ ] **Step 4: Remove duplicate logout work from UserMenu**

In `frontend/src/components/business/UserMenu.vue`, remove these imports:

```js
import { authLogout } from '@/api/index.js'
import { setAuthToken } from '@/services/http.js'
```

Replace `handleLogout()` with:

```js
async function handleLogout() {
  showMenu.value = false
  emit('logout')
}
```

---

### Task 5: Verification, Deploy, Docs, Commit

**Files:**
- Modify docs listed in File Structure.

- [ ] **Step 1: Run backend tests**

Run:

```bash
docker compose exec backend uv run pytest backend/tests/auth/test_logout_refresh.py -q
```

Expected: pass.

- [ ] **Step 2: Run frontend build**

Run:

```bash
cd /home/ubuntu/sj/interview-boss/frontend && npm run build
```

Expected: pass.

- [ ] **Step 3: Deploy backend and frontend**

Run:

```bash
/home/ubuntu/sj/interview-boss/deploy/docker-deploy.sh update
```

Expected: backend and nginx update successfully.

- [ ] **Step 4: Verify production behavior**

Use browser automation or curl to verify:

1. Login/register in a fresh browser context.
2. Confirm `POST /api/auth/refresh` succeeds before logout.
3. Click logout from the user menu and/or settings logout.
4. Reload `/master-bank`.
5. Confirm app lands on `/login` and `POST /api/auth/refresh` returns 401.

- [ ] **Step 5: Update docs**

Update docs to record that all logout entry points must use `useAuth.handleLogout()` and that cookie-aware auth calls need `X-Requested-With`.

- [ ] **Step 6: Commit**

Run:

```bash
git -C /home/ubuntu/sj/interview-boss add backend/app/routers/auth.py backend/tests/auth/test_logout_refresh.py frontend/src/services/http.js frontend/src/services/authApi.js frontend/src/composables/useAuth.js frontend/src/components/business/UserMenu.vue frontend/src/services/CLAUDE.md frontend/src/composables/CLAUDE.md backend/app/routers/CLAUDE.md docs/dev-log/2026-06-22-logout-refresh-fix.md docs/superpowers/plans/2026-06-22-logout-refresh-fix.md
git -C /home/ubuntu/sj/interview-boss commit -m "fix(auth): clear refresh cookie on logout" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: Covers the diagnosed root causes: missing CSRF header on logout, split frontend logout paths, idempotent backend cookie clearing, refresh-after-logout verification, docs, deployment, and commit.
- Placeholder scan: No placeholders, TODOs, or vague instructions remain.
- Type consistency: `authLogout()` returns boolean; callers ignore the boolean and always clear local state in `finally`, preserving logout UX even if the network fails.
