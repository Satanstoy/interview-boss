# 2026-06-22 Sidebar Logo Cleanup and Master Workflow

## Change

- Removed the blue gradient/shadow wrapper around the sidebar favicon logo.
- Documented that routine project edits should be committed directly on `master` because the project is single-maintainer.

## Verification

- Ran a grep-based assertion confirming `AppSidebar.vue` still references `/favicon-b.png` and no longer contains the primary gradient/shadow wrapper classes.
- Ran `cd frontend && npm run build`.
- Ran `./deploy/docker-deploy.sh frontend`.
