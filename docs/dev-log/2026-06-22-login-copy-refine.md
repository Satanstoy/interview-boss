# 2026-06-22 Login Copy Refine

## Rationale

The previous login copy stacked too many explanatory labels (`登录你的面试工作台`, `继续查看题库、面经和模拟面试记录`, feature chips). This felt generic and machine-written. The approved direction is Scheme C: familiar Chinese login copy with fewer explanations.

## Change

- Login card title changed to `欢迎回来`.
- Removed the subtitle `继续查看题库、面经和模拟面试记录`.
- Login tabs changed to `密码登录` / `验证码登录`.
- Register prompt changed to `还没有账号？立即注册`.
- Preview CTA changed to `免登录体验`.
- Removed bottom feature chips: `高频题库` / `模拟面试` / `复盘进度`.

## Verification

- RED Playwright assertion failed on the old deployed copy.
- Ran `cd frontend && npm run build` successfully.
- Ran `./deploy/docker-deploy.sh frontend` successfully.
- GREEN Playwright assertion passed: new copy is present, old title/subtitle/tab/CTA/chips are absent.
