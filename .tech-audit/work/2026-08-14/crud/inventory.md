# CRUD 排查 inventory — 2026-08-14

## 全仓 SQL 面
- 总 execute 调用：1589 处
- f-string SQL 拼接：108 处（主要模式：动态 WHERE/ORDER BY/列名片段）

## execute 密度 top 15（排查优先级）
- chat_service.py 127 | db/migrations/question_bank.py 114 | db/operations.py 68
- question_bank_sources.py 67 | migrations/data_repair.py 63 | migrations/chat.py 59
- routers/data.py 49 | migrations/auth.py 47 | migrations/clustering.py 47
- routers/coding.py 41 | question_variant_reconciliation.py 36 | clustering_maintenance.py 35
- cluster_review_lifecycle.py 34 | worker.py 33 | questions_pkg/mutations.py 33

## f-string SQL 热点文件
- insights.py（8 处：动态 scope/position 片段）
- practice_deck_service.py（4 处：动态 from/where/排序）
- questions.py / question_draw_service.py / interview_merge_service.py / admin_review.py

## 迁移破坏性语句（D9）
- auth.py:175-176 DROP master_question_bank/practice_history（012 遗留表）
- data_repair.py:355 DROP user_practice_history_old
- data_repair.py:49 DELETE user_profile 敏感 key 行
- practice_defaults.py:8 DELETE practice_decks 系统题单
- question_bank.py:464-467 DELETE 岗位级联

## DB 核心层
- db/operations.py（68 exec）/ queries.py / question_bank_sources.py（67 exec）/ connection.py（WAL + run_db）
