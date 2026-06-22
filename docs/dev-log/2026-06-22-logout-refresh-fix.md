# 2026-06-22 Logout Refresh Persistence Fix

## Root Cause

Logout only cleared frontend in-memory auth state in some paths. The HttpOnly `refresh_token` cookie could remain valid, so a browser refresh called `/api/auth/refresh` and restored `currentUser`.

Two issues caused this:

- `fetchWithCredentials()` did not send `X-Requested-With`, so backend CSRF protection rejected `/api/auth/logout` with 403 and did not clear the cookie.
- The settings-page logout path called `useAuth.handleLogout()` directly, and that function only cleared local state without calling the backend logout endpoint.

## Change

- `fetchWithCredentials()` now sends `X-Requested-With: XMLHttpRequest` by default.
- `authLogout()` returns whether the backend logout request succeeded instead of treating all HTTP responses as success.
- `useAuth.handleLogout()` now centralizes logout: it calls backend logout, then always clears local access token/current user state in `finally`.
- `UserMenu.vue` no longer duplicates logout API/token clearing; it emits logout and lets the shared auth flow handle it.
- Backend `/api/auth/logout` is idempotent after CSRF validation: missing/invalid refresh cookies still produce a success response with a clearing `Set-Cookie` header.
- Backend logout now invalidates the whole refresh-token family when `family_id` is present, preventing concurrent refresh/logout races from leaving a sibling refresh token usable.
- Frontend `authLogout()` has a 5s abort timeout so local logout cleanup cannot hang forever on a stalled network request.

## Verification

- Added a temporary TDD regression test in `backend/tests/security/test_logout_refresh.py` and watched it fail on the old backend behavior.
- Verified the backend tests pass after the backend logout change and review hardening: `4 passed`.
- Ran `cd frontend && npm run build` successfully.
- Deployed twice with `DEPLOY_MIN_FREE_MB=3500 DEPLOY_TARGET_FREE_MB=3500 ./deploy/docker-deploy.sh update`: first for the primary fix, then after code-review hardening for refresh-token family invalidation and logout timeout.
- Verified production behavior with curl: register a temporary user, refresh succeeds before logout, logout returns 200 and clears the `refresh_token` cookie, refresh returns 401 after logout, and no-cookie logout returns 200.
- Removed the temporary test file before commit because project rules say backend test files are not committed.
