# Schema inventory — 2026-08-14（生产库 interview-boss.db 快照）

## PRAGMAs
- journal_mode=wal / user_version=0（迁移用 schema_version 表）/ auto_vacuum=0 / page_size=4096 / freelist=0
- 运行时连接恒 PRAGMA foreign_keys=ON（connection.py:35）；init_db 迁移连接不开 FK
- migration runner: migrations/__init__.py _MIGRATIONS 1..80，run_migrations() 逐版本 BEGIN/COMMIT，schema_version 记录

## 已核实的结构性事实（父进程已验证，直接采纳为 findings 或转给对应 agent 深化）
1. FK 孤儿数据（PRAGMA foreign_key_check = 1319）：
   - chat_messages 1316 行 → 已删除的 chat_conversations（e3936da 启用 FK 前硬删对话遗留；delete_conversation 现在手动清 chat_tool_traces/interview_asked_questions 并依赖 CASCADE）
   - question_sources 1 + question_original_items 1 → question_bank 6018（已硬删）
   - question_position 1 → question_bank 5877（已硬删）
2. 0 行表：chat_turns / chat_side_effect_jobs / assistant_generations / chat_candidate_sets / chat_tool_traces / interview_events / pipeline_metrics / user_practice_history / practice_deck_items / merge_feedback / coding_playlist_items / coding_problem_favorites / user_interview_distribution_preferences / coding_submissions(9行) —— 新架构表在产线未被使用（或已废弃）
3. 无 schema 文档：docs/ 无 architecture/schema.md，最后迁移 080
4. user_profile 是全局 KV 单例（active_season、embedding_* 等），非用户级
5. question_bank.vector TEXT 已死（仅迁移触碰；现役是 embedding BLOB）
6. 时间戳格式混杂：TEXT datetime('now') / TIMESTAMP CURRENT_TIMESTAMP / INTEGER epoch（mcp_sessions.updated_at）/ REAL（login_failures.locked_until）/ TEXT DEFAULT '' 哨兵（jobs.available_at）
7. 重复唯一索引：practice_decks.deck_key UNIQUE + idx_practice_deck_key；user_question_review UNIQUE(user_id,question_bank_id) + idx_uqr_user_question
8. 缺 FK 声明的表/列：interview_asked_questions（user_id/conversation_id/question_id 全缺）、chat_tool_traces（conversation_id/message_id 缺）、quality_issue.qb_id、email_verification_codes.user_id、coding_problems.owner_id、analysis_queue.owner_id/question_detail_id、pipeline_metrics.owner_id、jobs.parent_job_id、refresh_tokens.family_id、users.current_position_id（无 ON DELETE）
9. 双写体系（文档化设计）：question_bank JSON 列（sources/original_questions/original_question_sources/answer_sources）+ 规范化表（question_sources/question_original_items/question_original_item_sources/question_variant_owners）；source_health.py 周期校验
10. 多套任务队列并存：jobs+job_payloads（+ARQ 投递）/ analysis_queue / cluster_review_tasks / interview_distribution_refresh_jobs / chat_side_effect_jobs / task_logs

## 索引要点（见 indexes.sql）
- idx_interview_url / idx_jd_url 与 (url,owner_id,deleted_at) 复合索引及 url_signature 系列索引存在重叠
- idx_email_codes_email(email,purpose,used) 无 expires_at → 清理全表扫描；refresh_tokens 无 expires_at 索引（auth.py:310 定期清理）
- idx_qp_position 与 idx_qp_position_question 冗余（前缀覆盖）
- question_sources/qoi 的 FK 由 UNIQUE(qb_id,…) 自动索引覆盖；chat_side_effect_jobs 的 source_turn_id FK 未被 (kind,source_turn_id) 前缀覆盖

## 产出格式（findings TSV）
severity\tdim\tlocation\ttitle\tfix\teffort\tconfidence
severity: 4=🔴 / 3=🟡 / 2=🟢 / 1=🟢low；dim=D9；effort S/M/L；confidence high/medium/needs-verification
标题与 fix 用中文，location 用 file:line 或 表名/列名。
