# InterviewBoss 数据库结构（Schema）

> 生成：2026-08-14 由迁移链 001-086 全量应用后的 schema 自动导出；与 backend/app/db/migrations/ 同步维护，改迁移后重新生成本节。
> 数据库：SQLite（WAL），backend/data/interview-boss.db；运行时连接恒 PRAGMA foreign_keys=ON（app/db/connection.py）。
> 软删除约定：deleted_at TIMESTAMP 列 + 查询过滤 deleted_at IS NULL；job_positions 历史使用 is_deleted 标志（遗留）。
> 时间戳约定：ISO-8601 文本（YYYY-MM-DD HH:MM:SS UTC 或带 TZ）；迁移 084 统一了 mcp_sessions/login_failures/jobs.available_at。
> 迁移安全：破坏性迁移（081/082/084/085/086）由 run_migrations 自动整库备份到 backend/data/backups/pre_migration_vNNN_*.db 并临时关闭 FK（表重建需要）。

## 迁移历史（081-086 schema hygiene）

| 版本 | 名称 | 内容 |
|---|---|---|
| 081 | cleanup_fk_orphans | 删除历史 FK 孤儿（chat_messages/asked_questions/quality_issue/analysis_queue/sources），断言 foreign_key_check=0 |
| 082 | fts_rebuild_triggers | 重建 question_fts 全量 + 安装 question_bank INSERT/UPDATE/DELETE 同步触发器（trg_question_fts_*） |
| 083 | index_housekeeping | 删除重复唯一索引 idx_practice_deck_key / idx_uqr_user_question |
| 084 | normalize_timestamps_jobs | 重建 jobs（去 error 列、available_at 默认 CURRENT_TIMESTAMP）；login_failures.locked_until REAL→TEXT；mcp_sessions.updated_at INTEGER→TEXT；refresh_tokens.created_at 统一 ISO |
| 085 | add_fk_declarations | 重建 11 表补齐 FK 与 ON DELETE 策略；users.username 小写回填；taxonomy 公共分类去重 + 部分唯一索引 |
| 086 | drop_dead_columns_indexes | 删除 question_bank.vector/duplicate_of 死列；新增 idx_email_codes_expires / idx_rt_expires |

## 表目录（67 张业务表 + FTS shadow）

### admin_assistant_log
- 列：id:INTEGER, session_id:TEXT, admin_id:INTEGER, role:TEXT, content:TEXT, tool_trace:TEXT, created_at:TEXT
- FK：无
- 索引：idx_admin_assistant_log_session

### analysis_queue
- 列：id:INTEGER, interview_id:INTEGER, status:TEXT, created_at:TIMESTAMP, processed_at:TIMESTAMP, question_detail_id:INTEGER, owner_id:INTEGER
- FK：owner_id -> users(id) [SET NULL]; question_detail_id -> questions_detail(id) [CASCADE]; interview_id -> interview(id) [NO ACTION]
- 索引：idx_aq_status_created, idx_aq_status, idx_aq_question_detail, idx_aq_owner, idx_aq_interview

### assistant_generations
- 列：id:TEXT, user_id:INTEGER, conversation_id:TEXT, turn_id:TEXT, message_id:INTEGER, parent_generation_id:TEXT, source_turn_id:TEXT, contract_hash:TEXT, evidence_refs_json:TEXT, visible:INTEGER, created_at:TIMESTAMP
- FK：parent_generation_id -> assistant_generations(id) [SET NULL]; message_id -> chat_messages(id) [CASCADE]; turn_id -> chat_turns(id) [CASCADE]; conversation_id -> chat_conversations(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_assistant_generations_visible

### chat_candidate_sets
- 列：id:TEXT, user_id:INTEGER, conversation_id:TEXT, source:TEXT, source_turn_id:TEXT, items_json:TEXT, schema_version:INTEGER, status:TEXT, expires_at:TIMESTAMP, selected_item_id:INTEGER, created_at:TIMESTAMP, consumed_at:TIMESTAMP
- FK：source_turn_id -> chat_turns(id) [SET NULL]; conversation_id -> chat_conversations(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_chat_candidate_sets_owner

### chat_conversations
- 列：id:TEXT, user_id:INTEGER, mode:TEXT, title:TEXT, jd_id:INTEGER, resume_text:TEXT, status:TEXT, created_at:TIMESTAMP, updated_at:TIMESTAMP, session_notes:TEXT, metadata:TEXT, job_position:TEXT, metadata_version:INTEGER, session_notes_version:INTEGER
- FK：jd_id -> jd(id) [SET NULL]; user_id -> users(id) [CASCADE]
- 索引：idx_cc_user_status_position, idx_cc_user_status, idx_cc_updated

### chat_memories
- 列：id:INTEGER, user_id:INTEGER, memory_type:TEXT, content:TEXT, source:TEXT, is_active:INTEGER, created_at:TIMESTAMP, updated_at:TIMESTAMP, summary:TEXT, source_turn_id:TEXT, source_job_id:TEXT, memory_schema_version:INTEGER, expires_at:TIMESTAMP, content_hash:TEXT
- FK：source_job_id -> chat_side_effect_jobs(id) [SET NULL]; source_turn_id -> chat_turns(id) [SET NULL]; user_id -> users(id) [CASCADE]
- 索引：idx_cmem_user_active, idx_chat_memories_provenance

### chat_messages
- 列：id:INTEGER, conversation_id:TEXT, role:TEXT, content:TEXT, token_count:INTEGER, metadata:TEXT, created_at:TIMESTAMP
- FK：conversation_id -> chat_conversations(id) [CASCADE]
- 索引：idx_cm_conversation

### chat_side_effect_jobs
- 列：id:TEXT, kind:TEXT, user_id:INTEGER, conversation_id:TEXT, source_turn_id:TEXT, payload_json:TEXT, status:TEXT, attempts:INTEGER, available_at:TIMESTAMP, locked_at:TIMESTAMP, finished_at:TIMESTAMP, last_error:TEXT, created_at:TIMESTAMP
- FK：source_turn_id -> chat_turns(id) [CASCADE]; conversation_id -> chat_conversations(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_chat_side_effect_jobs_ready

### chat_tool_traces
- 列：id:INTEGER, conversation_id:TEXT, message_id:INTEGER, react_step:INTEGER, tool_name:TEXT, sanitized_args_json:TEXT, result_summary_json:TEXT, elapsed_ms:INTEGER, created_at:TIMESTAMP
- FK：message_id -> chat_messages(id) [SET NULL]; conversation_id -> chat_conversations(id) [CASCADE]
- 索引：idx_ctt_conversation

### chat_turns
- 列：id:TEXT, conversation_id:TEXT, user_id:INTEGER, client_request_id:TEXT, fence:INTEGER, status:TEXT, user_message_id:INTEGER, assistant_message_id:INTEGER, cancel_reason:TEXT, error_code:TEXT, created_at:TIMESTAMP, finished_at:TIMESTAMP, request_fingerprint:TEXT, revision_of_message_id:INTEGER
- FK：assistant_message_id -> chat_messages(id) [SET NULL]; user_message_id -> chat_messages(id) [SET NULL]; user_id -> users(id) [CASCADE]; conversation_id -> chat_conversations(id) [CASCADE]
- 索引：idx_chat_turn_revision, idx_chat_turn_request_fingerprint, idx_chat_turn_user_status, idx_chat_turn_fence, idx_chat_turn_running_conversation

### cluster_review_state
- 列：cluster_id:INTEGER, current_version:TEXT, reviewed_version:TEXT, status:TEXT, priority:INTEGER, last_trigger_reason:TEXT, last_reviewed_at:TEXT, last_error:TEXT, created_at:TEXT, updated_at:TEXT
- FK：cluster_id -> question_bank(id) [CASCADE]
- 索引：idx_cluster_review_state_status

### cluster_review_tasks
- 列：id:TEXT, cluster_id:INTEGER, review_version:TEXT, trigger_reason:TEXT, status:TEXT, attempts:INTEGER, available_at:TEXT, locked_until:TEXT, arq_job_id:TEXT, last_error:TEXT, created_at:TEXT, started_at:TEXT, finished_at:TEXT
- FK：cluster_id -> question_bank(id) [CASCADE]
- 索引：idx_cluster_review_tasks_lease, idx_cluster_review_tasks_dispatch

### coding_playlist_items
- 列：playlist_id:INTEGER, problem_id:INTEGER, created_at:TIMESTAMP
- FK：problem_id -> coding_problems(id) [CASCADE]; playlist_id -> coding_playlists(id) [CASCADE]

### coding_playlists
- 列：id:INTEGER, user_id:INTEGER, name:TEXT, description:TEXT, created_at:TIMESTAMP, updated_at:TIMESTAMP, position:INTEGER
- FK：user_id -> users(id) [CASCADE]
- 索引：idx_coding_playlist_user

### coding_problem_favorites
- 列：user_id:INTEGER, problem_id:INTEGER, created_at:TIMESTAMP
- FK：problem_id -> coding_problems(id) [CASCADE]; user_id -> users(id) [CASCADE]

### coding_problems
- 列：id:INTEGER, title:TEXT, description:TEXT, difficulty:TEXT, tags:TEXT, expected_complexity:TEXT, source:TEXT, supported_languages:TEXT, is_active:INTEGER, created_at:TIMESTAMP, updated_at:TIMESTAMP, owner_id:INTEGER, source_type:TEXT
- FK：owner_id -> users(id) [SET NULL]
- 索引：idx_coding_problem_owner

### coding_submissions
- 列：id:INTEGER, user_id:INTEGER, problem_id:INTEGER, language:TEXT, code:TEXT, mode:TEXT, hint_round:INTEGER, parent_submission_id:INTEGER, ai_feedback:TEXT, error_categories:TEXT, is_passed:INTEGER, created_at:TIMESTAMP, scores:TEXT, reference_answer:TEXT, total_score:REAL
- FK：parent_submission_id -> coding_submissions(id) [NO ACTION]; problem_id -> coding_problems(id) [NO ACTION]; user_id -> users(id) [NO ACTION]
- 索引：idx_coding_sub_parent, idx_coding_sub_problem, idx_coding_sub_user

### email_verification_codes
- 列：id:INTEGER, email:TEXT, code:TEXT, purpose:TEXT, user_id:INTEGER, expires_at:TIMESTAMP, used:INTEGER, created_at:TIMESTAMP
- FK：user_id -> users(id) [CASCADE]
- 索引：idx_email_codes_expires, idx_email_codes_email

### interview
- 列：id:INTEGER, url:TEXT, company:TEXT, round:TEXT, focus:TEXT, questions_list:TEXT, difficulty:TEXT, created_at:TIMESTAMP, season:TEXT, owner_id:INTEGER, status:TEXT, job_position:TEXT, url_signature:TEXT, updated_at:TIMESTAMP, deleted_at:TIMESTAMP, analysis_status:TEXT, analysis_stage:TEXT, analysis_result:TEXT, analysis_updated_at:TIMESTAMP
- FK：owner_id -> users(id) [NO ACTION]
- 索引：idx_interview_url_owner_deleted, idx_interview_url_sig, idx_interview_owner_status, idx_interview_url_unique, idx_interview_url

### interview_asked_questions
- 列：id:INTEGER, user_id:INTEGER, conversation_id:TEXT, question_id:INTEGER, asked_at:TIMESTAMP
- FK：question_id -> question_bank(id) [CASCADE]; conversation_id -> chat_conversations(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_iaq_user_question, idx_iaq_conversation

### interview_distribution_refresh_jobs
- 列：scope:TEXT, job_position:TEXT, requested_source_version:TEXT, published_source_version:TEXT, status:TEXT, attempt_count:INTEGER, claimed_by:TEXT, claimed_at:TIMESTAMP, last_error:TEXT, next_retry_at:TIMESTAMP, updated_at:TIMESTAMP
- FK：无

### interview_distribution_stat_exclusions
- 列：stats_version:INTEGER, scope:TEXT, job_position:TEXT, interview_id:INTEGER, exclusion_reason:TEXT, created_at:TIMESTAMP
- FK：无

### interview_distribution_stats
- 列：scope:TEXT, job_position:TEXT, question_type:TEXT, stats_version:INTEGER, posterior_mean_ratio:REAL, posterior_alpha:REAL, raw_question_count:INTEGER, sample_interview_count:INTEGER, sample_question_count:INTEGER, recommended_total_count:INTEGER, dispersion:REAL, confidence:TEXT, calculated_at:TIMESTAMP
- FK：无

### interview_events
- 列：id:INTEGER, user_id:INTEGER, conversation_id:TEXT, turn_id:TEXT, event_key:TEXT, event_type:TEXT, payload_json:TEXT, schema_version:INTEGER, created_at:TIMESTAMP
- FK：turn_id -> chat_turns(id) [CASCADE]; conversation_id -> chat_conversations(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_interview_events_replay

### interview_import_chunks
- 列：import_id:TEXT, stream_type:TEXT, chunk_index:INTEGER, total_chunks:INTEGER, content_hash:TEXT, content:TEXT, created_at:TIMESTAMP
- FK：import_id -> interview_imports(id) [CASCADE]
- 索引：idx_interview_import_chunks_import

### interview_imports
- 列：id:TEXT, user_id:INTEGER, client_request_id:TEXT, title:TEXT, job_position:TEXT, company:TEXT, interview_round:TEXT, recruiting_season:TEXT, resume_id:INTEGER, resume_text:TEXT, context_json:TEXT, external_analysis_json:TEXT, status:TEXT, job_id:INTEGER, conversation_id:TEXT, report_json:TEXT, error_code:TEXT, error_message:TEXT, analysis_attempt:INTEGER, created_at:TIMESTAMP, updated_at:TIMESTAMP, completed_at:TIMESTAMP
- FK：job_id -> jobs(id) [SET NULL]; user_id -> users(id) [CASCADE]
- 索引：idx_interview_imports_conversation, idx_interview_imports_user_status

### invalidated_families
- 列：family_id:TEXT, invalidated_at:TIMESTAMP
- FK：无

### jd
- 列：id:INTEGER, url:TEXT, company:TEXT, season:TEXT, owner_id:INTEGER, status:TEXT, url_signature:TEXT, updated_at:TIMESTAMP, job_position:TEXT, deleted_at:TIMESTAMP, tech_stack:TEXT, source:TEXT, position:TEXT, salary:TEXT, job_title:TEXT
- FK：无
- 索引：idx_jd_url_sig, idx_jd_owner_status, idx_jd_url_unique, idx_jd_url

### job_payloads
- 列：job_id:INTEGER, payload:TEXT, created_at:TIMESTAMP
- FK：job_id -> jobs(id) [CASCADE]

### job_positions
- 列：id:INTEGER, name:TEXT, description:TEXT, created_at:TIMESTAMP, updated_at:TIMESTAMP
- FK：无

### jobs
- 列：id:INTEGER, job_type:TEXT, status:TEXT, progress_current:INTEGER, progress_total:INTEGER, progress_message:TEXT, result:TEXT, created_by:INTEGER, created_at:TIMESTAMP, updated_at:TIMESTAMP, completed_at:TIMESTAMP, attempts:INTEGER, available_at:TEXT, locked_until:TEXT, arq_job_id:TEXT, worker_id:TEXT, last_error:TEXT, started_at:TEXT, idempotency_key:TEXT, parent_job_id:INTEGER
- FK：created_by -> users(id) [NO ACTION]
- 索引：uq_jobs_idempotency, idx_jobs_type, idx_jobs_status, idx_jobs_parent, idx_jobs_dispatch, idx_jobs_creator_type_status

### login_failures
- 列：id:INTEGER, username:TEXT, failure_count:INTEGER, locked_until:TEXT, updated_at:TIMESTAMP
- FK：无

### mcp_tokens
- 列：user_id:INTEGER, token_hash:TEXT, token_hint:TEXT, created_at:TIMESTAMP, rotated_at:TIMESTAMP, last_used_at:TIMESTAMP, token_seed:TEXT
- FK：user_id -> users(id) [CASCADE]
- 索引：idx_mcp_tokens_hash

### merge_feedback
- 列：id:INTEGER, merge_history_id:INTEGER, question_bank_id:INTEGER, feedback_type:TEXT, comment:TEXT, user_id:INTEGER, created_at:TIMESTAMP
- FK：user_id -> users(id) [SET NULL]; question_bank_id -> question_bank(id) [SET NULL]; merge_history_id -> merge_history(id) [SET NULL]
- 索引：idx_merge_feedback_history

### merge_history
- 列：id:INTEGER, survivor_id:INTEGER, merged_ids:TEXT, merged_questions:TEXT, pre_snapshot:TEXT, post_snapshot:TEXT, operation_type:TEXT, phase:TEXT, confidence:REAL, cat2:TEXT, operator_id:INTEGER, is_rolled_back:INTEGER, rolled_back_at:TIMESTAMP, rolled_back_by:INTEGER, created_at:TIMESTAMP
- FK：rolled_back_by -> users(id) [SET NULL]; operator_id -> users(id) [SET NULL]; survivor_id -> question_bank(id) [SET NULL]
- 索引：idx_merge_history_cat2, idx_merge_history_survivor

### pipeline_metrics
- 列：id:INTEGER, operation:TEXT, job_position:TEXT, owner_id:INTEGER, questions_in:INTEGER, matched:INTEGER, new_clusters:INTEGER, merged:INTEGER, llm_calls:INTEGER, elapsed_seconds:REAL, error:TEXT, created_at:TIMESTAMP
- FK：无
- 索引：idx_pm_created, idx_pm_op

### practice_deck_items
- 列：id:INTEGER, deck_id:INTEGER, question_bank_id:INTEGER, sort_order:INTEGER, created_at:TIMESTAMP
- FK：question_bank_id -> question_bank(id) [CASCADE]; deck_id -> practice_decks(id) [CASCADE]
- 索引：idx_practice_deck_items_queue, idx_practice_deck_items_question, idx_practice_deck_items_order

### practice_decks
- 列：id:INTEGER, deck_key:TEXT, name:TEXT, description:TEXT, deck_type:TEXT, criteria_json:TEXT, sort_order:INTEGER, created_at:TIMESTAMP, updated_at:TIMESTAMP, owner_id:INTEGER, visibility:TEXT
- FK：owner_id -> users(id) [CASCADE]
- 索引：idx_practice_decks_owner

### practice_review_events
- 列：id:INTEGER, user_id:INTEGER, question_bank_id:INTEGER, review_id:INTEGER, rating:TEXT, score:INTEGER, source:TEXT, reviewed_at:TIMESTAMP, before_state_json:TEXT, corrected_at:TIMESTAMP
- FK：review_id -> user_question_review(id) [CASCADE]; question_bank_id -> question_bank(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_practice_events_user_time

### quality_audit
- 列：id:INTEGER, audited_at:TEXT, sample_size:INTEGER, total_variants:INTEGER, inconsistent_count:INTEGER, duplicate_count:INTEGER, coverage_count:INTEGER, inconsistent_rate:REAL, duplicate_rate:REAL, coverage_rate:REAL, report_path:TEXT, triggered_cleanup:INTEGER
- FK：无

### quality_issue
- 列：id:INTEGER, qb_id:INTEGER, variant_index:INTEGER, issue_type:TEXT, suggested_action:TEXT, reason:TEXT, suggested_value:TEXT, confidence:REAL, status:TEXT, created_at:TEXT, reviewed_at:TEXT, reviewed_by:INTEGER, target_qb_id:INTEGER, new_cat2:TEXT, review_version:TEXT, review_task_id:TEXT, trigger_reason:TEXT, variant_key:TEXT, source_question:TEXT, source_cat2:TEXT, issue_fingerprint:TEXT, superseded_at:TEXT, superseded_by:INTEGER
- FK：qb_id -> question_bank(id) [CASCADE]
- 索引：uq_quality_issue_review_version, uq_quality_issue_active_fingerprint, idx_quality_issue_review_version, idx_quality_issue_fingerprint

### question_bank
- 列：id:INTEGER, question:TEXT, cat1:TEXT, cat2:TEXT, tags:TEXT, difficulty:TEXT, frequency:INTEGER, ai_answer:TEXT, sources:TEXT, original_questions:TEXT, original_question_sources:TEXT, is_starred:INTEGER, owner_id:INTEGER, submitted_by:INTEGER, status:TEXT, created_at:TIMESTAMP, updated_at:TIMESTAMP, deleted_at:TIMESTAMP, job_position:TEXT, question_manually_edited:INTEGER, embedding:BLOB, cluster_id:INTEGER, embedding_model:TEXT, embedding_dim:INTEGER, answer_sources:TEXT, cluster_label:TEXT
- FK：submitted_by -> users(id) [NO ACTION]; owner_id -> users(id) [NO ACTION]
- 索引：idx_qb_job_position_visibility, idx_qb_cluster_id, idx_qb_deleted_owner_status, idx_qb_owner_status_position, idx_qb_job_position, idx_qb_owner_status

### question_original_item_sources
- 列：id:INTEGER, original_item_id:INTEGER, url:TEXT, company:TEXT, round:TEXT, created_at:TIMESTAMP, deleted_at:TIMESTAMP
- FK：original_item_id -> question_original_items(id) [CASCADE]
- 索引：idx_qois_deleted_at, idx_qois_url, idx_qois_oi

### question_original_items
- 列：id:INTEGER, question_bank_id:INTEGER, question_text:TEXT, created_at:TIMESTAMP, deleted_at:TIMESTAMP
- FK：question_bank_id -> question_bank(id) [CASCADE]
- 索引：idx_qoi_deleted_at, idx_qoi_text, idx_qoi_qb

### question_position
- 列：question_id:INTEGER, position_id:INTEGER
- FK：position_id -> job_positions(id) [CASCADE]; question_id -> question_bank(id) [CASCADE]
- 索引：idx_qp_position_question, idx_qp_position

### question_sources
- 列：id:INTEGER, question_bank_id:INTEGER, url:TEXT, company:TEXT, round:TEXT, created_at:TIMESTAMP, deleted_at:TIMESTAMP
- FK：question_bank_id -> question_bank(id) [CASCADE]
- 索引：idx_qs_deleted_at, idx_qs_url, idx_qs_qb

### question_variant_owners
- 列：normalized_question:TEXT, question_bank_id:INTEGER, question_text:TEXT, updated_at:TIMESTAMP
- FK：question_bank_id -> question_bank(id) [CASCADE]
- 索引：idx_question_variant_owners_qb

### questions_detail
- 列：id:INTEGER, interview_id:INTEGER, question:TEXT, cat1:TEXT, cat2:TEXT, tags:TEXT, difficulty:TEXT, diff_tag:TEXT, answer:TEXT, url:TEXT, source:TEXT, owner_id:INTEGER, status:TEXT, deleted_at:TIMESTAMP, updated_at:TIMESTAMP, company:TEXT, round:TEXT, job_position:TEXT, question_type:TEXT, dimension:TEXT
- FK：无
- 索引：idx_qd_interview_question_type, idx_qd_question, idx_qd_url

### refresh_tokens
- 列：id:INTEGER, user_id:INTEGER, jti:TEXT, expires_at:TEXT, created_at:TIMESTAMP, remember:INTEGER, ip_address:TEXT, user_agent:TEXT, family_id:TEXT
- FK：user_id -> users(id) [NO ACTION]
- 索引：idx_rt_expires, idx_rt_family, idx_rt_user, idx_rt_jti

### schema_version
- 列：version:INTEGER, name:TEXT, applied_at:TIMESTAMP
- FK：无

### taxonomy
- 列：id:INTEGER, position_name:TEXT, categories_json:TEXT, is_default:INTEGER, created_at:TIMESTAMP, updated_at:TIMESTAMP, source:TEXT, owner_id:INTEGER, is_public:INTEGER
- FK：无
- 索引：uq_taxonomy_public, idx_taxonomy_position_owner

### user_interview_distribution_preferences
- 列：user_id:INTEGER, job_position:TEXT, mode:TEXT, target_question_count:INTEGER, custom_distribution:TEXT, selected_experience_id:INTEGER, style_strength:TEXT, updated_at:TIMESTAMP
- FK：无

### user_llm_config
- 列：user_id:INTEGER, api_key:TEXT, base_url:TEXT, model:TEXT, timeout:INTEGER, updated_at:TIMESTAMP, api_format:TEXT, thinking:INTEGER
- FK：user_id -> users(id) [CASCADE]

### user_practice_history
- 列：id:INTEGER, user_id:INTEGER, question_bank_id:INTEGER, user_answer:TEXT, evaluation_result:TEXT, score:INTEGER, created_at:TIMESTAMP, updated_at:TIMESTAMP
- FK：question_bank_id -> question_bank(id) [CASCADE]; user_id -> users(id) [NO ACTION]
- 索引：idx_uph_user_date, idx_uph_question, idx_uph_user

### user_profile
- 列：key:TEXT, value:TEXT, updated_at:TIMESTAMP
- FK：无

### user_question_review
- 列：id:INTEGER, user_id:INTEGER, question_bank_id:INTEGER, state:TEXT, proficiency:INTEGER, review_count:INTEGER, lapse_count:INTEGER, last_rating:TEXT, last_score:INTEGER, last_reviewed_at:TIMESTAMP, next_review_at:TIMESTAMP, interval_days:REAL, ease_factor:REAL, stability_days:REAL, difficulty:REAL, algorithm:TEXT, created_at:TIMESTAMP, updated_at:TIMESTAMP
- FK：question_bank_id -> question_bank(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_uqr_proficiency, idx_uqr_due

### user_question_view
- 列：id:INTEGER, user_id:INTEGER, question_bank_id:INTEGER, is_starred:INTEGER, personal_tags:TEXT, note:TEXT, user_answer:TEXT, created_at:TIMESTAMP, updated_at:TIMESTAMP
- FK：question_bank_id -> question_bank(id) [CASCADE]; user_id -> users(id) [CASCADE]
- 索引：idx_uqv_user_starred, idx_uqv_user_question

### user_recruitment_pref
- 列：user_id:INTEGER, graduation_year:INTEGER, batch:TEXT, daily_capacity:INTEGER, updated_at:TIMESTAMP, pace:TEXT
- FK：无

### user_resumes
- 列：id:INTEGER, user_id:INTEGER, filename:TEXT, raw_text:TEXT, created_at:TIMESTAMP, updated_at:TIMESTAMP, optimized_text:TEXT, optimization_points:TEXT, optimized_position:TEXT, optimized_at:TIMESTAMP
- FK：user_id -> users(id) [CASCADE]
- 索引：idx_resume_user

### user_search_config
- 列：user_id:INTEGER, provider:TEXT, api_key:TEXT, base_url:TEXT, enabled:INTEGER, updated_at:TIMESTAMP
- FK：user_id -> users(id) [CASCADE]

### users
- 列：id:INTEGER, username:TEXT, password_hash:TEXT, is_admin:INTEGER, bank_mode:TEXT, created_at:TIMESTAMP, current_position_id:INTEGER, updated_at:TIMESTAMP, personal_position:TEXT, email:TEXT, share_default:TEXT
- FK：current_position_id -> job_positions(id) [SET NULL]
- 索引：idx_users_email_unique
