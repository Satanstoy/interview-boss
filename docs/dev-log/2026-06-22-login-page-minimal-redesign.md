# 2026-06-22 Login Page Minimal Redesign

## Research Summary

Light Exa research on AI interview and SaaS login/entry pages showed that comparable products emphasize a clear product name/logo, a short value statement, low-friction login, and a free/no-login trial or preview CTA. Dense dashboard previews are better suited to marketing pages than compact auth screens.

## Change

- Replaced the dense split login page with a compact login card, no-login preview CTA, and three short benefit chips.
- Moved the favicon logo and `InterviewBoss` name to a top-left brand anchor so the logo remains visible at 100% browser zoom.
- Removed the `JD / 面经 / 模拟面试，一处管理` subtitle to reduce visual clutter.
- Added `hideHeader` to `LoginModal` embedded mode so the login page controls the visual hierarchy and keeps the form compact.
- Kept existing password/email login behavior and the `/master-bank?preview=1` preview route.

## Verification

- Ran a Playwright RED assertion against the old deployed page to confirm it still had dashboard preview text and lacked the new CTA.
- Ran `cd frontend && npm run build`.
- Ran `./deploy/docker-deploy.sh frontend`.
- Verified with Playwright that `/login` has no vertical scroll at 1280×720, 1366×768, and 390×844; old dashboard preview text is gone; the preview CTA and benefit chips are present.
