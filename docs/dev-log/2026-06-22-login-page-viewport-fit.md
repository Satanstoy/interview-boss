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
