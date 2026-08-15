# Round-3 inventory — 2026-08-15 (work dir .tech-audit/work/2026-08-15-r3)

Repo root: /opt/interview-boss  |  HEAD: c50e463  |  Worktree: dirty (docs/adr/chat-agent-quality-protection.md modified, experiment_reports/ untracked)
Stack: Python 3.12 + FastAPI + SQLite(WAL) + LangGraph + ARQ (backend/app), Vue3 + Vite + Tailwind + shadcn-vue (frontend/src), shell (scripts/, deploy/), Docker Compose (docker-compose.yml).
Constraints: pytest ONLY via docker compose --profile test run --rm test; prod backend container is app-runtime without dev deps; do NOT modify repo files; do NOT write to backend/data.
Prior round: .tech-audit/work/2026-08-15-r3/prior-round2.tsv (round-2 findings, 31 rows). No accepted.tsv / debt.tsv / extras in .tech-audit.
Round-2 red/major items ALREADY FIXED in HEAD (verify, don't re-report):
- bank_build.py:8 imports match_new_questions (was NameError)
- scripts/check.sh:151,164 define run_static_backend/run_static_frontend; called 178/179
- frontend/eslint.config.js:4,15-18 wires @typescript-eslint/parser (TS SFC lint restored)
- pip-audit now runs inside test-runtime (commit ea37f70)

STILL OPEN from round 2 (verify state, keep as finding if still true):
- D6: prod worker container runs unlabeled image 783f58123828 (30h up); check inside worker.py for scheduled_db_retention_task
- D9: prod DB had 178 FK violations (interview_asked_questions orphans) — D9 agent may query docker backend sqlite read-only
- D3: key-subset pytest had 127 failed + 14 errors (isolation + chat assertion failures)
- D6: backend/data 738MB, ~665MB backups/residue; disk / 82% used (31G/40G)
- D4: ADMIN_PASSWORD 8 chars in backend/.env; git history contains MiMo keys
- line_guard.sh does not scan backend/tests (test_react_loop.py 3728L, test_chat.py 2038L)

Top files by LOC (backend/app + frontend/src + scripts/deploy):
1498 frontend/src/components/business/ChatView.vue | 1388 backend/app/worker.py | 1343 backend/app/agents/chat/nodes.py | 1323 backend/app/services/llm.py | 1226 backend/app/services/clustering_maintenance.py | 1191 frontend/src/components/business/PracticeMode.vue | 1171 backend/app/agents/chat/react_loop.py | 1158 backend/app/services/fts_service.py | 1142 frontend/src/components/business/LoginModal.vue | 1142 backend/app/db/operations.py | 1025 backend/app/mcp_server/interview_tools.py | 1007 backend/app/services/memory_recall_service.py | 961 backend/app/agents/chat/question_plan.py | 947 backend/app/routers/data.py | 935 backend/app/routers/auth.py | 897 backend/app/routers/coding.py | 889 backend/app/agents/chat/pipeline.py | 865 backend/app/db/question_bank_sources.py | 839 backend/app/services/interview_import_service.py | 828 frontend/src/layouts/AuthenticatedLayout.vue | 778 backend/app/services/clustering/matcher.py | 761 backend/app/services/pipeline/compact.py | 748 backend/app/db/migrations/schema_hygiene.py | 730 backend/app/services/cluster_review_lifecycle.py | 724 backend/app/routers/chat.py | 715 deploy/docker-deploy.sh | 714 backend/app/services/question_variant_reconciliation.py | 694 backend/app/mcp_server/app.py | 691 backend/app/services/chat_turn_service.py | 648 backend/app/agents/chat/tools.py | 646 backend/app/services/practice_deck_service.py | 624 frontend/src/services/http.js | 619 backend/app/agents/chat/prompts.py | 615 backend/app/routers/admin_review.py
No backend/app or frontend/src file exceeds 1500 lines (redline OK).

Git churn top (commits/file since 2026-07-15): PracticeMode.vue 53 | services/CLAUDE.md 47 | CONTEXT.md 37 | business/CLAUDE.md 33 | migrations/__init__.py 31 | worker.py 24 | routers/CLAUDE.md 24 | today-review.spec.js 23 | AuthenticatedLayout.vue 20 | usePracticeDecks.js 19 | frontend/CLAUDE.md 17 | clustering_maintenance.py 17 | practice-flow.spec.js 16 | PracticeView.vue 16 | answer_enrichment.py 16 | CodingPractice.vue 15 | docker-compose.yml 15 | ChatView.vue 14 | test_answer_sources.py 14 | llm.py 14 | answers.py 14 | practice_deck_service.py 13 | quality_issue_ops.py 12 | prompts.py 12 | asgi.py 12 | SiteHeader.vue 11 | materials.css 11 | global.css 11 | api/index.js 11 | submit_service.py 11 | memory_labels.py 11 | questions.py 11

Runtime (docker): nginx/oauth-gateway/backend/worker/redis/redis-cache up 30h; backend healthy; interview-boss-app:local & nginx images 30h old; interview-boss-test:local built 2h ago. Disk / 82% used.
Key dirs: backend/app/{routers,services,agents,core,db,models,middleware,mcp_server}; frontend/src/{views,components,composables,services,router,layouts,utils,constants}; scripts/; deploy/; nginx/; docs/.
Line redline: 1500 (backend/app/**/*.py and frontend/src/**/*.{vue,js}); check.sh lineguard is blocking.
