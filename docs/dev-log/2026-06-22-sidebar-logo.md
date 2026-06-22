# 2026-06-22 Sidebar Logo

## Change

- Replaced the sidebar top-left text mark `IB` with the existing square favicon asset `/favicon-b.png`.

## Verification

- Ran a grep-based assertion confirming `AppSidebar.vue` references `/favicon-b.png` and no longer renders the old logo text in the sidebar logo containers.
- Ran `cd frontend && npm run build` after installing missing frontend dependencies with `npm ci`.
