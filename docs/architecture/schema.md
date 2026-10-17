# InterviewBoss SQLite Schema

> Generated: 2026-10-17
> Source migration commit: 402bb416
> Latest migration: 129 (answer_review)
> foreign_key_check: 0
> Source of truth: `backend/app/db/migrations/` applied to a fresh in-memory SQLite database.
> Runtime: SQLite WAL with `PRAGMA foreign_keys=ON`; soft-deleted rows use `deleted_at IS NULL` filters where documented by the owning service.

## Migration history

| Version | Name | Applied in fresh schema |
|---:|---|---|
| 1 | `base_tables` | yes |
| 2 | `question_bank` | yes |
| 3 | `auth_tables` | yes |
| 4 | `jd_interview_qd_columns` | yes |
| 5 | `question_bank_extra_columns` | yes |
| 6 | `job_positions` | yes |
| 7 | `taxonomy` | yes |
| 8 | `user_question_view` | yes |
| 9 | `analysis_queue` | yes |
| 10 | `users_extra_columns` | yes |
| 11 | `data_backfills` | yes |
| 12 | `admin_seed` | yes |
| 13 | `user_question_view_user_answer` | yes |
| 14 | `data_repairs` | yes |
| 15 | `refresh_tokens_extra` | yes |
| 16 | `normalized_source_tables` | yes |
| 17 | `backfill_normalized_sources` | yes |
| 18 | `composite_indexes` | yes |
| 19 | `fix_cascades` | yes |
| 21 | `performance_indexes` | yes |
| 22 | `jobs_table` | yes |
| 23 | `duplicate_of` | yes |
| 24 | `chat_tables` | yes |
| 25 | `question_fts` | yes |
| 26 | `populate_fts` | yes |
| 27 | `memory_summary` | yes |
| 28 | `session_notes` | yes |
| 29 | `user_resumes` | yes |
| 30 | `coding_module` | yes |
| 31 | `coding_scores` | yes |
| 32 | `embedding_column` | yes |
| 33 | `cluster_id` | yes |
| 34 | `backfill_confidence` | yes |
| 35 | `split_e_category` | yes |
| 36 | `job_payloads` | yes |
| 37 | `conversation_metadata` | yes |
| 38 | `chat_conversation_position` | yes |
| 39 | `merge_review_tables` | yes |
| 40 | `chat_tool_traces` | yes |
| 41 | `asked_questions` | yes |
| 42 | `interview_distribution` | yes |
| 43 | `chat_turns` | yes |
| 44 | `turn_replay_and_revision` | yes |
| 45 | `durable_side_effects` | yes |
| 46 | `structured_turns` | yes |
| 47 | `soft_delete_sources` | yes |
| 48 | `embedding_metadata` | yes |
| 49 | `analysis_queue_owner` | yes |
| 50 | `pipeline_metrics` | yes |
| 51 | `share_default` | yes |
| 52 | `mcp_tokens` | yes |
| 53 | `coding_library` | yes |
| 54 | `mcp_token_seed` | yes |
| 55 | `practice_review_system` | yes |
| 56 | `custom_practice_decks` | yes |
| 57 | `practice_default_decks` | yes |
| 58 | `coding_playlist_order` | yes |
| 59 | `practice_queue_indexes` | yes |
| 60 | `search_config` | yes |
| 61 | `resume_optimization` | yes |
| 62 | `user_recruitment_pref` | yes |
| 63 | `answer_sources` | yes |
| 64 | `user_recruitment_pace` | yes |
| 65 | `llm_api_format` | yes |
| 66 | `cluster_label` | yes |
| 67 | `quality_audit` | yes |
| 68 | `quality_issue` | yes |
| 69 | `admin_assistant_log` | yes |
| 70 | `quality_issue_target` | yes |
| 71 | `quality_issue_new_cat2` | yes |
| 72 | `cluster_review_lifecycle` | yes |
| 73 | `quality_issue_source_snapshot` | yes |
| 74 | `durable_job_lifecycle` | yes |
| 75 | `job_retry_lineage` | yes |
| 76 | `question_variant_ownership` | yes |
| 77 | `quality_issue_identity` | yes |
| 78 | `practice_review_corrections` | yes |
| 79 | `users_email_unique` | yes |
| 80 | `interview_import` | yes |
| 81 | `cleanup_fk_orphans` | yes |
| 82 | `fts_rebuild_triggers` | yes |
| 83 | `index_housekeeping` | yes |
| 84 | `normalize_timestamps_jobs` | yes |
| 85 | `add_fk_declarations` | yes |
| 86 | `drop_dead_columns_indexes` | yes |
| 87 | `evaluation_control_plane` | yes |
| 88 | `practice_review_idempotency` | yes |
| 89 | `llm_usage` | yes |
| 90 | `analysis_queue_fk_cascade` | yes |
| 91 | `repair_fk_orphans` | yes |
| 92 | `preserve_quality_issue_history` | yes |
| 93 | `evaluation_dual_axis` | yes |
| 94 | `review_event_answer_snapshot` | yes |
| 95 | `evaluation_experiment` | yes |
| 96 | `review_event_evaluation_snapshot` | yes |
| 97 | `resume_user_unique` | yes |
| 98 | `practiced_list_index` | yes |
| 99 | `job_progress_phase` | yes |
| 100 | `analysis_queue_scope_idempotency` | yes |
| 101 | `project_harness_releases` | yes |
| 102 | `public_contribution_workflow` | yes |
| 103 | `public_contribution_retry_scope` | yes |
| 104 | `system_taxonomies` | yes |
| 105 | `position_retirement` | yes |
| 108 | `question_bank_scope` | yes |
| 109 | `question_detail_scope_guard` | yes |
| 110 | `harness_event_stream` | yes |
| 111 | `harness_core_state` | yes |
| 112 | `harness_context_hashes` | yes |
| 113 | `harness_turn_base_snapshot` | yes |
| 114 | `harness_attempt_provenance` | yes |
| 115 | `evaluation_lifecycle` | yes |
| 116 | `evaluation_resume` | yes |
| 117 | `evaluation_resume_idempotency` | yes |
| 118 | `jd_bonus` | yes |
| 119 | `admin_audit_log` | yes |
| 120 | `clear_db_confirmations` | yes |
| 121 | `upload_recovery_core` | yes |
| 122 | `upload_resolution` | yes |
| 123 | `public_publish_gate` | yes |
| 124 | `upload_spec_stage_names` | yes |
| 125 | `upload_llm_api_format` | yes |
| 126 | `question_promotions` | yes |
| 127 | `reconcile_branch_identities` | yes |
| 128 | `python_tags` | yes |
| 129 | `answer_review` | yes |

## Tables (95)

### `admin_assistant_log`
- Columns: `id`:INTEGER, `session_id`:TEXT, `admin_id`:INTEGER, `role`:TEXT, `content`:TEXT, `tool_trace`:TEXT, `created_at`:TEXT
- Foreign keys: none
- Indexes: `idx_admin_assistant_log_session` (session_id, admin_id, id)

### `admin_audit_log`
- Columns: `id`:INTEGER, `event_type`:TEXT, `status`:TEXT, `actor_id`:INTEGER, `metadata`:TEXT, `created_at`:TEXT
- Foreign keys: none
- Indexes: `idx_admin_audit_event` (event_type, created_at)

### `analysis_queue`
- Columns: `id`:INTEGER, `interview_id`:INTEGER, `status`:TEXT, `created_at`:TIMESTAMP, `processed_at`:TIMESTAMP, `question_detail_id`:INTEGER, `owner_id`:INTEGER, `contribution_request_id`:INTEGER, `root_import_id`:TEXT, `job_id`:INTEGER, `lease_generation`:INTEGER, `locked_until`:TEXT, `claimed_at`:TEXT, `pipeline_version`:TEXT
- Foreign keys: `owner_id` -> `users`.`id` (SET NULL); `question_detail_id` -> `questions_detail`.`id` (CASCADE); `interview_id` -> `interview`.`id` (CASCADE); `root_import_id` -> `upload_imports`.`id` (NO ACTION)
- Indexes: `idx_analysis_queue_contribution` (contribution_request_id, status); `idx_aq_interview` (interview_id); `idx_aq_owner` (owner_id); `idx_aq_question_detail` (question_detail_id); `idx_aq_status_created` (status, created_at); `idx_aq_status` (status); `uq_analysis_queue_detail_scope` UNIQUE partial (interview_id, question_detail_id, expr:-2); `uq_analysis_queue_v2_work` UNIQUE partial (root_import_id, question_detail_id, expr:-2, expr:-2)

### `assistant_generations`
- Columns: `id`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `turn_id`:TEXT, `message_id`:INTEGER, `parent_generation_id`:TEXT, `source_turn_id`:TEXT, `contract_hash`:TEXT, `evidence_refs_json`:TEXT, `visible`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `parent_generation_id` -> `assistant_generations`.`id` (SET NULL); `message_id` -> `chat_messages`.`id` (CASCADE); `turn_id` -> `chat_turns`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_assistant_generations_visible` (conversation_id, visible, created_at); `sqlite_autoindex_assistant_generations_1` UNIQUE (id); `sqlite_autoindex_assistant_generations_2` UNIQUE (message_id)

### `chat_candidate_sets`
- Columns: `id`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `source`:TEXT, `source_turn_id`:TEXT, `items_json`:TEXT, `schema_version`:INTEGER, `status`:TEXT, `expires_at`:TIMESTAMP, `selected_item_id`:INTEGER, `created_at`:TIMESTAMP, `consumed_at`:TIMESTAMP
- Foreign keys: `source_turn_id` -> `chat_turns`.`id` (SET NULL); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_chat_candidate_sets_owner` (user_id, conversation_id, status, expires_at); `sqlite_autoindex_chat_candidate_sets_1` UNIQUE (id)

### `chat_conversations`
- Columns: `id`:TEXT, `user_id`:INTEGER, `mode`:TEXT, `title`:TEXT, `jd_id`:INTEGER, `resume_text`:TEXT, `status`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `session_notes`:TEXT, `metadata`:TEXT, `job_position`:TEXT, `metadata_version`:INTEGER, `session_notes_version`:INTEGER, `harness_version`:TEXT, `session_version`:INTEGER, `interview_config_json`:TEXT, `language`:TEXT, `question_strategy`:TEXT, `provider_policy_json`:TEXT
- Foreign keys: `jd_id` -> `jd`.`id` (SET NULL); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_cc_updated` (updated_at); `idx_cc_user_status_position` (user_id, status, job_position); `idx_cc_user_status` (user_id, status); `sqlite_autoindex_chat_conversations_1` UNIQUE (id)

### `chat_memories`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `memory_type`:TEXT, `content`:TEXT, `source`:TEXT, `is_active`:INTEGER, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `summary`:TEXT, `source_turn_id`:TEXT, `source_job_id`:TEXT, `memory_schema_version`:INTEGER, `expires_at`:TIMESTAMP, `content_hash`:TEXT
- Foreign keys: `source_job_id` -> `chat_side_effect_jobs`.`id` (SET NULL); `source_turn_id` -> `chat_turns`.`id` (SET NULL); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_chat_memories_provenance` (user_id, source_turn_id, content_hash); `idx_cmem_user_active` (user_id, is_active)

### `chat_messages`
- Columns: `id`:INTEGER, `conversation_id`:TEXT, `role`:TEXT, `content`:TEXT, `token_count`:INTEGER, `metadata`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `conversation_id` -> `chat_conversations`.`id` (CASCADE)
- Indexes: `idx_cm_conversation` (conversation_id, created_at)

### `chat_side_effect_jobs`
- Columns: `id`:TEXT, `kind`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `source_turn_id`:TEXT, `payload_json`:TEXT, `status`:TEXT, `attempts`:INTEGER, `available_at`:TIMESTAMP, `locked_at`:TIMESTAMP, `finished_at`:TIMESTAMP, `last_error`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `source_turn_id` -> `chat_turns`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_chat_side_effect_jobs_ready` (status, available_at); `sqlite_autoindex_chat_side_effect_jobs_1` UNIQUE (id); `sqlite_autoindex_chat_side_effect_jobs_2` UNIQUE (kind, source_turn_id)

### `chat_tool_traces`
- Columns: `id`:INTEGER, `conversation_id`:TEXT, `message_id`:INTEGER, `react_step`:INTEGER, `tool_name`:TEXT, `sanitized_args_json`:TEXT, `result_summary_json`:TEXT, `elapsed_ms`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `message_id` -> `chat_messages`.`id` (SET NULL); `conversation_id` -> `chat_conversations`.`id` (CASCADE)
- Indexes: `idx_ctt_conversation` (conversation_id, created_at)

### `chat_turns`
- Columns: `id`:TEXT, `conversation_id`:TEXT, `user_id`:INTEGER, `client_request_id`:TEXT, `fence`:INTEGER, `status`:TEXT, `user_message_id`:INTEGER, `assistant_message_id`:INTEGER, `cancel_reason`:TEXT, `error_code`:TEXT, `created_at`:TIMESTAMP, `finished_at`:TIMESTAMP, `request_fingerprint`:TEXT, `revision_of_message_id`:INTEGER, `harness_status`:TEXT, `terminal_reason`:TEXT, `session_version`:INTEGER, `ledger_version_at_start`:INTEGER, `turn_run_version`:INTEGER, `current_action_id`:TEXT, `current_attempt_no`:INTEGER, `latest_sequence`:INTEGER, `budget_snapshot_json`:TEXT, `context_pack_hash`:TEXT, `started_at`:TIMESTAMP, `revision_of_turn_id`:TEXT, `lease_owner`:TEXT, `lease_expires_at`:TIMESTAMP, `heartbeat_at`:TIMESTAMP, `stable_prefix_hash`:TEXT, `turn_base_snapshot_json`:TEXT
- Foreign keys: `assistant_message_id` -> `chat_messages`.`id` (SET NULL); `user_message_id` -> `chat_messages`.`id` (SET NULL); `user_id` -> `users`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE)
- Indexes: `idx_chat_turn_fence` (conversation_id, fence); `idx_chat_turn_harness_status` (conversation_id, harness_status, created_at); `idx_chat_turn_recovery` (harness_status, lease_expires_at, heartbeat_at); `idx_chat_turn_request_fingerprint` (conversation_id, request_fingerprint); `idx_chat_turn_revision_of_turn` (revision_of_turn_id); `idx_chat_turn_revision` (revision_of_message_id); `idx_chat_turn_running_conversation` UNIQUE partial (conversation_id); `idx_chat_turn_user_status` (user_id, status, created_at); `sqlite_autoindex_chat_turns_1` UNIQUE (id); `sqlite_autoindex_chat_turns_2` UNIQUE (conversation_id, client_request_id)

### `clear_db_confirmations`
- Columns: `token_hash`:TEXT, `admin_id`:INTEGER, `consumed_at`:TEXT
- Foreign keys: none
- Indexes: `idx_clear_db_confirmation_admin` (admin_id, consumed_at); `sqlite_autoindex_clear_db_confirmations_1` UNIQUE (token_hash)

### `cluster_review_state`
- Columns: `cluster_id`:INTEGER, `current_version`:TEXT, `reviewed_version`:TEXT, `status`:TEXT, `priority`:INTEGER, `last_trigger_reason`:TEXT, `last_reviewed_at`:TEXT, `last_error`:TEXT, `created_at`:TEXT, `updated_at`:TEXT
- Foreign keys: `cluster_id` -> `question_bank`.`id` (CASCADE)
- Indexes: `idx_cluster_review_state_status` (status, priority, updated_at)

### `cluster_review_tasks`
- Columns: `id`:TEXT, `cluster_id`:INTEGER, `review_version`:TEXT, `trigger_reason`:TEXT, `status`:TEXT, `attempts`:INTEGER, `available_at`:TEXT, `locked_until`:TEXT, `arq_job_id`:TEXT, `last_error`:TEXT, `created_at`:TEXT, `started_at`:TEXT, `finished_at`:TEXT
- Foreign keys: `cluster_id` -> `question_bank`.`id` (CASCADE)
- Indexes: `idx_cluster_review_tasks_dispatch` (status, available_at, cluster_id); `idx_cluster_review_tasks_lease` (status, locked_until); `sqlite_autoindex_cluster_review_tasks_1` UNIQUE (id); `sqlite_autoindex_cluster_review_tasks_2` UNIQUE (cluster_id, review_version)

### `coding_playlist_items`
- Columns: `playlist_id`:INTEGER, `problem_id`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `problem_id` -> `coding_problems`.`id` (CASCADE); `playlist_id` -> `coding_playlists`.`id` (CASCADE)
- Indexes: `sqlite_autoindex_coding_playlist_items_1` UNIQUE (playlist_id, problem_id)

### `coding_playlists`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `name`:TEXT, `description`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `position`:INTEGER
- Foreign keys: `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_coding_playlist_user` (user_id); `sqlite_autoindex_coding_playlists_1` UNIQUE (user_id, name)

### `coding_problem_favorites`
- Columns: `user_id`:INTEGER, `problem_id`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `problem_id` -> `coding_problems`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `sqlite_autoindex_coding_problem_favorites_1` UNIQUE (user_id, problem_id)

### `coding_problems`
- Columns: `id`:INTEGER, `title`:TEXT, `description`:TEXT, `difficulty`:TEXT, `tags`:TEXT, `expected_complexity`:TEXT, `source`:TEXT, `supported_languages`:TEXT, `is_active`:INTEGER, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `owner_id`:INTEGER, `source_type`:TEXT
- Foreign keys: `owner_id` -> `users`.`id` (SET NULL)
- Indexes: `idx_coding_problem_owner` (owner_id)

### `coding_submissions`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `problem_id`:INTEGER, `language`:TEXT, `code`:TEXT, `mode`:TEXT, `hint_round`:INTEGER, `parent_submission_id`:INTEGER, `ai_feedback`:TEXT, `error_categories`:TEXT, `is_passed`:INTEGER, `created_at`:TIMESTAMP, `scores`:TEXT, `reference_answer`:TEXT, `total_score`:REAL
- Foreign keys: `parent_submission_id` -> `coding_submissions`.`id` (NO ACTION); `problem_id` -> `coding_problems`.`id` (NO ACTION); `user_id` -> `users`.`id` (NO ACTION)
- Indexes: `idx_coding_sub_parent` (parent_submission_id); `idx_coding_sub_problem` (problem_id); `idx_coding_sub_user` (user_id)

### `email_verification_codes`
- Columns: `id`:INTEGER, `email`:TEXT, `code`:TEXT, `purpose`:TEXT, `user_id`:INTEGER, `expires_at`:TIMESTAMP, `used`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_email_codes_email` (email, purpose, used); `idx_email_codes_expires` (expires_at)

### `eval_artifacts`
- Columns: `id`:INTEGER, `run_id`:INTEGER, `item_id`:INTEGER, `attempt_id`:INTEGER, `artifact_type`:TEXT, `storage_path`:TEXT, `digest`:TEXT, `size_bytes`:INTEGER, `retention_class`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `attempt_id` -> `eval_attempts`.`id` (CASCADE); `item_id` -> `eval_items`.`id` (CASCADE); `run_id` -> `eval_runs`.`id` (CASCADE)
- Indexes: none

### `eval_attempts`
- Columns: `id`:INTEGER, `item_id`:INTEGER, `attempt_index`:INTEGER, `attempt_kind`:TEXT, `status`:TEXT, `failure_class`:TEXT, `raw_observation_json`:TEXT, `error_message`:TEXT, `started_at`:TIMESTAMP, `finished_at`:TIMESTAMP
- Foreign keys: `item_id` -> `eval_items`.`id` (CASCADE)
- Indexes: `sqlite_autoindex_eval_attempts_1` UNIQUE (item_id, attempt_index)

### `eval_batches`
- Columns: `id`:INTEGER, `batch_fingerprint`:TEXT, `target_release_id`:INTEGER, `evaluation_release_id`:INTEGER, `benchmark_suite_release_id`:INTEGER, `eval_protocol_release_id`:INTEGER, `judge_release_id`:INTEGER, `simulator_harness_release_id`:INTEGER, `candidate_simulator_release_id`:INTEGER, `harness_release_id`:INTEGER, `environment_fingerprint`:TEXT, `seed`:INTEGER, `replication_count`:INTEGER, `status`:TEXT, `total_items`:INTEGER, `completed_items`:INTEGER, `failed_items`:INTEGER, `created_by`:INTEGER, `created_at`:TIMESTAMP, `started_at`:TIMESTAMP, `finished_at`:TIMESTAMP, `cancel_requested`:INTEGER, `summary_json`:TEXT, `snapshot_json`:TEXT, `last_heartbeat_at`:TIMESTAMP
- Foreign keys: `created_by` -> `users`.`id` (SET NULL); `harness_release_id` -> `harness_releases`.`id` (RESTRICT); `candidate_simulator_release_id` -> `eval_releases`.`id` (RESTRICT); `simulator_harness_release_id` -> `eval_releases`.`id` (RESTRICT); `judge_release_id` -> `eval_releases`.`id` (RESTRICT); `eval_protocol_release_id` -> `eval_releases`.`id` (RESTRICT); `benchmark_suite_release_id` -> `eval_releases`.`id` (RESTRICT); `evaluation_release_id` -> `eval_releases`.`id` (RESTRICT); `target_release_id` -> `eval_releases`.`id` (RESTRICT)
- Indexes: `idx_eval_batches_status_created` (status, created_at); `sqlite_autoindex_eval_batches_1` UNIQUE (batch_fingerprint)

### `eval_benchmark_cases`
- Columns: `id`:INTEGER, `suite_id`:INTEGER, `case_key`:TEXT, `scenario_key`:TEXT, `input_snapshot_json`:TEXT, `contract_json`:TEXT, `input_digest`:TEXT, `active`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `suite_id` -> `eval_benchmark_suites`.`id` (CASCADE)
- Indexes: `idx_eval_cases_suite_active` (suite_id, active, id); `sqlite_autoindex_eval_benchmark_cases_1` UNIQUE (suite_id, case_key)

### `eval_benchmark_suites`
- Columns: `id`:INTEGER, `release_id`:INTEGER, `suite_key`:TEXT, `target_type`:TEXT, `judge_model`:TEXT, `description`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `release_id` -> `eval_releases`.`id` (RESTRICT)
- Indexes: `sqlite_autoindex_eval_benchmark_suites_1` UNIQUE (release_id)

### `eval_events`
- Columns: `id`:INTEGER, `run_id`:INTEGER, `sequence`:INTEGER, `event_type`:TEXT, `payload_json`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `run_id` -> `eval_runs`.`id` (CASCADE)
- Indexes: `idx_eval_events_run_sequence` (run_id, sequence); `sqlite_autoindex_eval_events_1` UNIQUE (run_id, sequence)

### `eval_experiment_events`
- Columns: `id`:INTEGER, `experiment_id`:INTEGER, `sequence`:INTEGER, `event_type`:TEXT, `payload_json`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `experiment_id` -> `eval_experiments`.`id` (CASCADE)
- Indexes: `idx_eval_experiment_events_sequence` (experiment_id, sequence); `sqlite_autoindex_eval_experiment_events_1` UNIQUE (experiment_id, sequence)

### `eval_experiment_runs`
- Columns: `id`:INTEGER, `experiment_id`:INTEGER, `run_id`:INTEGER, `target_type`:TEXT, `display_order`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `run_id` -> `eval_runs`.`id` (CASCADE); `experiment_id` -> `eval_experiments`.`id` (CASCADE)
- Indexes: `idx_eval_experiment_runs_experiment` (experiment_id, display_order, id); `sqlite_autoindex_eval_experiment_runs_1` UNIQUE (run_id); `sqlite_autoindex_eval_experiment_runs_2` UNIQUE (experiment_id, target_type)

### `eval_experiments`
- Columns: `id`:INTEGER, `experiment_key`:TEXT, `status`:TEXT, `target_types_json`:TEXT, `comparison_group`:TEXT, `environment_fingerprint`:TEXT, `seed`:INTEGER, `replication_count`:INTEGER, `total_runs`:INTEGER, `completed_runs`:INTEGER, `failed_runs`:INTEGER, `cancelled_runs`:INTEGER, `summary_json`:TEXT, `created_by`:INTEGER, `created_at`:TIMESTAMP, `started_at`:TIMESTAMP, `finished_at`:TIMESTAMP
- Foreign keys: `created_by` -> `users`.`id` (SET NULL)
- Indexes: `idx_eval_experiments_status_created` (status, created_at); `sqlite_autoindex_eval_experiments_1` UNIQUE (experiment_key)

### `eval_human_reviews`
- Columns: `id`:INTEGER, `comparison_group`:TEXT, `run_a_id`:INTEGER, `run_b_id`:INTEGER, `item_key`:TEXT, `reviewer_id`:INTEGER, `choice`:TEXT, `dimensions_json`:TEXT, `comment`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `reviewer_id` -> `users`.`id` (RESTRICT); `run_b_id` -> `eval_runs`.`id` (CASCADE); `run_a_id` -> `eval_runs`.`id` (CASCADE)
- Indexes: `idx_eval_reviews_group` (comparison_group, created_at)

### `eval_items`
- Columns: `id`:INTEGER, `run_id`:INTEGER, `case_id`:INTEGER, `replication_index`:INTEGER, `seed`:INTEGER, `status`:TEXT, `selected_attempt_id`:INTEGER, `contract_status`:TEXT, `hard_gate_status`:TEXT, `judge_status`:TEXT, `score`:REAL, `result_json`:TEXT, `created_at`:TIMESTAMP, `started_at`:TIMESTAMP, `finished_at`:TIMESTAMP
- Foreign keys: `case_id` -> `eval_benchmark_cases`.`id` (RESTRICT); `run_id` -> `eval_runs`.`id` (CASCADE)
- Indexes: `idx_eval_items_run_status` (run_id, status, id); `sqlite_autoindex_eval_items_1` UNIQUE (run_id, case_id, replication_index)

### `eval_releases`
- Columns: `id`:INTEGER, `release_key`:TEXT, `release_type`:TEXT, `version`:TEXT, `target_type`:TEXT, `display_name`:TEXT, `status`:TEXT, `manifest_json`:TEXT, `manifest_digest`:TEXT, `judge_model`:TEXT, `git_sha`:TEXT, `image_digest`:TEXT, `config_digest`:TEXT, `created_by`:INTEGER, `created_at`:TIMESTAMP, `published_at`:TIMESTAMP, `archived_at`:TIMESTAMP
- Foreign keys: `created_by` -> `users`.`id` (SET NULL)
- Indexes: `idx_eval_releases_type_status` (release_type, status); `sqlite_autoindex_eval_releases_1` UNIQUE (release_key)

### `eval_runs`
- Columns: `id`:INTEGER, `batch_id`:INTEGER, `target_release_id`:INTEGER, `evaluation_release_id`:INTEGER, `benchmark_suite_release_id`:INTEGER, `eval_protocol_release_id`:INTEGER, `judge_release_id`:INTEGER, `simulator_harness_release_id`:INTEGER, `candidate_simulator_release_id`:INTEGER, `harness_release_id`:INTEGER, `comparison_group`:TEXT, `idempotency_key`:TEXT, `status`:TEXT, `total_items`:INTEGER, `completed_items`:INTEGER, `failed_items`:INTEGER, `summary_json`:TEXT, `created_by`:INTEGER, `created_at`:TIMESTAMP, `started_at`:TIMESTAMP, `finished_at`:TIMESTAMP, `cancel_requested`:INTEGER, `snapshot_json`:TEXT, `last_heartbeat_at`:TIMESTAMP, `restart_of_run_id`:INTEGER, `resume_of_run_id`:INTEGER
- Foreign keys: `resume_of_run_id` -> `eval_runs`.`id` (SET NULL); `restart_of_run_id` -> `eval_runs`.`id` (SET NULL); `created_by` -> `users`.`id` (SET NULL); `harness_release_id` -> `harness_releases`.`id` (RESTRICT); `candidate_simulator_release_id` -> `eval_releases`.`id` (RESTRICT); `simulator_harness_release_id` -> `eval_releases`.`id` (RESTRICT); `judge_release_id` -> `eval_releases`.`id` (RESTRICT); `eval_protocol_release_id` -> `eval_releases`.`id` (RESTRICT); `benchmark_suite_release_id` -> `eval_releases`.`id` (RESTRICT); `evaluation_release_id` -> `eval_releases`.`id` (RESTRICT); `target_release_id` -> `eval_releases`.`id` (RESTRICT); `batch_id` -> `eval_batches`.`id` (RESTRICT)
- Indexes: `idx_eval_runs_active_resume_of` UNIQUE partial (resume_of_run_id); `idx_eval_runs_comparison_group` (comparison_group, created_at); `idx_eval_runs_evaluation_release` (evaluation_release_id, created_at); `idx_eval_runs_harness_release` (harness_release_id, created_at); `idx_eval_runs_resume_of` (resume_of_run_id); `idx_eval_runs_status_created` (status, created_at)

### `harness_releases`
- Columns: `id`:INTEGER, `harness_key`:TEXT, `target_type`:TEXT, `version`:TEXT, `display_name`:TEXT, `status`:TEXT, `manifest_json`:TEXT, `manifest_digest`:TEXT, `source_ref`:TEXT, `git_sha`:TEXT, `image_digest`:TEXT, `config_digest`:TEXT, `created_at`:TIMESTAMP, `published_at`:TIMESTAMP, `archived_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `idx_harness_releases_target_status` (target_type, status, id); `sqlite_autoindex_harness_releases_1` UNIQUE (harness_key, version)

### `interview`
- Columns: `id`:INTEGER, `url`:TEXT, `company`:TEXT, `round`:TEXT, `focus`:TEXT, `questions_list`:TEXT, `difficulty`:TEXT, `created_at`:TIMESTAMP, `season`:TEXT, `owner_id`:INTEGER, `status`:TEXT, `job_position`:TEXT, `url_signature`:TEXT, `updated_at`:TIMESTAMP, `deleted_at`:TIMESTAMP, `analysis_status`:TEXT, `analysis_stage`:TEXT, `analysis_result`:TEXT, `analysis_updated_at`:TIMESTAMP, `publish_status`:TEXT
- Foreign keys: `owner_id` -> `users`.`id` (NO ACTION)
- Indexes: `idx_interview_owner_status` (owner_id, status); `idx_interview_url_owner_deleted` (url, owner_id, deleted_at); `idx_interview_url_sig` (url_signature); `idx_interview_url_unique` UNIQUE partial (url, owner_id); `idx_interview_url` (url)

### `interview_actions`
- Columns: `id`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `turn_id`:TEXT, `action_key`:TEXT, `action_type`:TEXT, `phase`:TEXT, `status`:TEXT, `current_attempt_no`:INTEGER, `input_json`:TEXT, `output_json`:TEXT, `error_code`:TEXT, `created_at`:TIMESTAMP, `started_at`:TIMESTAMP, `finished_at`:TIMESTAMP
- Foreign keys: `turn_id` -> `chat_turns`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_interview_actions_recovery` (status, created_at); `idx_interview_actions_turn` (turn_id, created_at); `sqlite_autoindex_interview_actions_1` UNIQUE (id); `sqlite_autoindex_interview_actions_2` UNIQUE (turn_id, action_key)

### `interview_artifacts`
- Columns: `id`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `turn_id`:TEXT, `action_id`:TEXT, `attempt_id`:TEXT, `artifact_type`:TEXT, `visibility`:TEXT, `content_json`:TEXT, `content_hash`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `attempt_id` -> `interview_attempts`.`id` (SET NULL); `action_id` -> `interview_actions`.`id` (SET NULL); `turn_id` -> `chat_turns`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_interview_artifacts_turn` (turn_id, created_at); `sqlite_autoindex_interview_artifacts_1` UNIQUE (id)

### `interview_asked_questions`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `conversation_id`:TEXT, `question_id`:INTEGER, `asked_at`:TIMESTAMP
- Foreign keys: `question_id` -> `question_bank`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_iaq_conversation` (conversation_id); `idx_iaq_user_question` (user_id, question_id)

### `interview_attempts`
- Columns: `id`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `turn_id`:TEXT, `action_id`:TEXT, `attempt_no`:INTEGER, `status`:TEXT, `call_mode`:TEXT, `provider`:TEXT, `model`:TEXT, `context_pack_hash`:TEXT, `prompt_cache_key`:TEXT, `request_hash`:TEXT, `error_code`:TEXT, `created_at`:TIMESTAMP, `started_at`:TIMESTAMP, `finished_at`:TIMESTAMP, `harness_version`:TEXT, `prompt_schema`:TEXT, `sampling_hash`:TEXT, `skill_hashes_json`:TEXT
- Foreign keys: `action_id` -> `interview_actions`.`id` (CASCADE); `turn_id` -> `chat_turns`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_interview_attempts_turn` (turn_id, created_at); `sqlite_autoindex_interview_attempts_1` UNIQUE (id); `sqlite_autoindex_interview_attempts_2` UNIQUE (action_id, attempt_no)

### `interview_distribution_refresh_jobs`
- Columns: `scope`:TEXT, `job_position`:TEXT, `requested_source_version`:TEXT, `published_source_version`:TEXT, `status`:TEXT, `attempt_count`:INTEGER, `claimed_by`:TEXT, `claimed_at`:TIMESTAMP, `last_error`:TEXT, `next_retry_at`:TIMESTAMP, `updated_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `sqlite_autoindex_interview_distribution_refresh_jobs_1` UNIQUE (scope, job_position)

### `interview_distribution_stat_exclusions`
- Columns: `stats_version`:INTEGER, `scope`:TEXT, `job_position`:TEXT, `interview_id`:INTEGER, `exclusion_reason`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `sqlite_autoindex_interview_distribution_stat_exclusions_1` UNIQUE (stats_version, scope, job_position, interview_id)

### `interview_distribution_stats`
- Columns: `scope`:TEXT, `job_position`:TEXT, `question_type`:TEXT, `stats_version`:INTEGER, `posterior_mean_ratio`:REAL, `posterior_alpha`:REAL, `raw_question_count`:INTEGER, `sample_interview_count`:INTEGER, `sample_question_count`:INTEGER, `recommended_total_count`:INTEGER, `dispersion`:REAL, `confidence`:TEXT, `calculated_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `sqlite_autoindex_interview_distribution_stats_1` UNIQUE (scope, job_position, question_type, stats_version)

### `interview_event_outbox`
- Columns: `event_id`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `turn_id`:TEXT, `sequence`:INTEGER, `event_type`:TEXT, `payload_json`:TEXT, `status`:TEXT, `attempts`:INTEGER, `available_at`:TIMESTAMP, `locked_at`:TIMESTAMP, `published_at`:TIMESTAMP, `last_error`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `turn_id` -> `chat_turns`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_interview_event_outbox_ready` (status, available_at, created_at); `sqlite_autoindex_interview_event_outbox_1` UNIQUE (event_id); `sqlite_autoindex_interview_event_outbox_2` UNIQUE (turn_id, sequence)

### `interview_events`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `conversation_id`:TEXT, `turn_id`:TEXT, `event_key`:TEXT, `event_type`:TEXT, `payload_json`:TEXT, `schema_version`:INTEGER, `created_at`:TIMESTAMP, `event_id`:TEXT, `sequence`:INTEGER, `action_id`:TEXT, `phase`:TEXT, `channel`:TEXT, `visibility`:TEXT
- Foreign keys: `turn_id` -> `chat_turns`.`id` (CASCADE); `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_interview_events_replay` (conversation_id, id); `idx_interview_events_turn_channel` (turn_id, channel, sequence); `idx_interview_events_turn_event_id` UNIQUE (turn_id, event_id); `idx_interview_events_turn_sequence` UNIQUE (turn_id, sequence); `sqlite_autoindex_interview_events_1` UNIQUE (turn_id, event_key)

### `interview_import_chunks`
- Columns: `import_id`:TEXT, `stream_type`:TEXT, `chunk_index`:INTEGER, `total_chunks`:INTEGER, `content_hash`:TEXT, `content`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `import_id` -> `interview_imports`.`id` (CASCADE)
- Indexes: `idx_interview_import_chunks_import` (import_id, stream_type, chunk_index); `sqlite_autoindex_interview_import_chunks_1` UNIQUE (import_id, stream_type, chunk_index)

### `interview_imports`
- Columns: `id`:TEXT, `user_id`:INTEGER, `client_request_id`:TEXT, `title`:TEXT, `job_position`:TEXT, `company`:TEXT, `interview_round`:TEXT, `recruiting_season`:TEXT, `resume_id`:INTEGER, `resume_text`:TEXT, `context_json`:TEXT, `external_analysis_json`:TEXT, `status`:TEXT, `job_id`:INTEGER, `conversation_id`:TEXT, `report_json`:TEXT, `error_code`:TEXT, `error_message`:TEXT, `analysis_attempt`:INTEGER, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `completed_at`:TIMESTAMP
- Foreign keys: `job_id` -> `jobs`.`id` (SET NULL); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_interview_imports_conversation` (conversation_id); `idx_interview_imports_user_status` (user_id, status, updated_at); `sqlite_autoindex_interview_imports_1` UNIQUE (id); `sqlite_autoindex_interview_imports_2` UNIQUE (user_id, client_request_id)

### `interview_ledgers`
- Columns: `id`:TEXT, `user_id`:INTEGER, `conversation_id`:TEXT, `ledger_version`:INTEGER, `asked_question_refs_json`:TEXT, `coverage_events_json`:TEXT, `covered_dimensions_json`:TEXT, `current_topic`:TEXT, `current_phase`:TEXT, `depth`:INTEGER, `closing_stage`:TEXT, `counter_question_status`:TEXT, `recent_rhythm_signals_json`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP
- Foreign keys: `conversation_id` -> `chat_conversations`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_interview_ledgers_owner` (user_id, conversation_id, ledger_version); `sqlite_autoindex_interview_ledgers_1` UNIQUE (id); `sqlite_autoindex_interview_ledgers_2` UNIQUE (conversation_id)

### `invalidated_families`
- Columns: `family_id`:TEXT, `invalidated_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `sqlite_autoindex_invalidated_families_1` UNIQUE (family_id)

### `jd`
- Columns: `id`:INTEGER, `url`:TEXT, `company`:TEXT, `season`:TEXT, `owner_id`:INTEGER, `status`:TEXT, `url_signature`:TEXT, `updated_at`:TIMESTAMP, `job_position`:TEXT, `deleted_at`:TIMESTAMP, `tech_stack`:TEXT, `source`:TEXT, `position`:TEXT, `salary`:TEXT, `job_title`:TEXT, `bonus`:TEXT
- Foreign keys: none
- Indexes: `idx_jd_owner_status` (owner_id, status); `idx_jd_url_sig` (url_signature); `idx_jd_url_unique` UNIQUE partial (url, owner_id); `idx_jd_url` (url)

### `job_payloads`
- Columns: `job_id`:INTEGER, `payload`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `job_id` -> `jobs`.`id` (CASCADE)
- Indexes: none

### `job_positions`
- Columns: `id`:INTEGER, `name`:TEXT, `description`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `is_deleted`:INTEGER
- Foreign keys: none
- Indexes: `idx_job_positions_active` (is_deleted, name); `sqlite_autoindex_job_positions_1` UNIQUE (name)

### `jobs`
- Columns: `id`:INTEGER, `job_type`:TEXT, `status`:TEXT, `progress_current`:INTEGER, `progress_total`:INTEGER, `progress_message`:TEXT, `result`:TEXT, `created_by`:INTEGER, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `completed_at`:TIMESTAMP, `attempts`:INTEGER, `available_at`:TEXT, `locked_until`:TEXT, `arq_job_id`:TEXT, `worker_id`:TEXT, `last_error`:TEXT, `started_at`:TEXT, `idempotency_key`:TEXT, `parent_job_id`:INTEGER, `progress_phase`:TEXT, `root_import_id`:TEXT, `upload_attempt_id`:INTEGER, `work_key`:TEXT, `lease_generation`:INTEGER
- Foreign keys: `created_by` -> `users`.`id` (NO ACTION); `upload_attempt_id` -> `upload_attempts`.`id` (NO ACTION); `root_import_id` -> `upload_imports`.`id` (NO ACTION)
- Indexes: `idx_jobs_creator_type_status` (created_by, job_type, status); `idx_jobs_dispatch` (job_type, status, available_at, locked_until); `idx_jobs_parent` (parent_job_id, created_at); `idx_jobs_status` (status); `idx_jobs_type` (job_type); `idx_jobs_v2_root` (root_import_id); `uq_jobs_idempotency` UNIQUE partial (job_type, idempotency_key); `uq_jobs_v2_work_active` UNIQUE partial (root_import_id, job_type, work_key)

### `llm_usage`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `day`:TEXT, `call_count`:INTEGER, `total_tokens`:INTEGER, `updated_at`:TEXT
- Foreign keys: none
- Indexes: `idx_llm_usage_user_day` (user_id, day); `sqlite_autoindex_llm_usage_1` UNIQUE (user_id, day)

### `login_failures`
- Columns: `id`:INTEGER, `username`:TEXT, `failure_count`:INTEGER, `locked_until`:TEXT, `updated_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `sqlite_autoindex_login_failures_1` UNIQUE (username)

### `mcp_tokens`
- Columns: `user_id`:INTEGER, `token_hash`:TEXT, `token_hint`:TEXT, `created_at`:TIMESTAMP, `rotated_at`:TIMESTAMP, `last_used_at`:TIMESTAMP, `token_seed`:TEXT
- Foreign keys: `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_mcp_tokens_hash` (token_hash); `sqlite_autoindex_mcp_tokens_1` UNIQUE (token_hash)

### `merge_feedback`
- Columns: `id`:INTEGER, `merge_history_id`:INTEGER, `question_bank_id`:INTEGER, `feedback_type`:TEXT, `comment`:TEXT, `user_id`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `user_id` -> `users`.`id` (SET NULL); `question_bank_id` -> `question_bank`.`id` (SET NULL); `merge_history_id` -> `merge_history`.`id` (SET NULL)
- Indexes: `idx_merge_feedback_history` (merge_history_id)

### `merge_history`
- Columns: `id`:INTEGER, `survivor_id`:INTEGER, `merged_ids`:TEXT, `merged_questions`:TEXT, `pre_snapshot`:TEXT, `post_snapshot`:TEXT, `operation_type`:TEXT, `phase`:TEXT, `confidence`:REAL, `cat2`:TEXT, `operator_id`:INTEGER, `is_rolled_back`:INTEGER, `rolled_back_at`:TIMESTAMP, `rolled_back_by`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `rolled_back_by` -> `users`.`id` (SET NULL); `operator_id` -> `users`.`id` (SET NULL); `survivor_id` -> `question_bank`.`id` (SET NULL)
- Indexes: `idx_merge_history_cat2` (cat2); `idx_merge_history_survivor` (survivor_id)

### `pipeline_metrics`
- Columns: `id`:INTEGER, `operation`:TEXT, `job_position`:TEXT, `owner_id`:INTEGER, `questions_in`:INTEGER, `matched`:INTEGER, `new_clusters`:INTEGER, `merged`:INTEGER, `llm_calls`:INTEGER, `elapsed_seconds`:REAL, `error`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `idx_pm_created` (created_at); `idx_pm_op` (operation)

### `practice_deck_items`
- Columns: `id`:INTEGER, `deck_id`:INTEGER, `question_bank_id`:INTEGER, `sort_order`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `question_bank_id` -> `question_bank`.`id` (CASCADE); `deck_id` -> `practice_decks`.`id` (CASCADE)
- Indexes: `idx_practice_deck_items_order` (deck_id, sort_order, id); `idx_practice_deck_items_question` (question_bank_id); `idx_practice_deck_items_queue` (deck_id, sort_order, id, question_bank_id); `sqlite_autoindex_practice_deck_items_1` UNIQUE (deck_id, question_bank_id)

### `practice_decks`
- Columns: `id`:INTEGER, `deck_key`:TEXT, `name`:TEXT, `description`:TEXT, `deck_type`:TEXT, `criteria_json`:TEXT, `sort_order`:INTEGER, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `owner_id`:INTEGER, `visibility`:TEXT
- Foreign keys: `owner_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_practice_decks_owner` (owner_id, sort_order); `sqlite_autoindex_practice_decks_1` UNIQUE (deck_key)

### `practice_review_events`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `question_bank_id`:INTEGER, `review_id`:INTEGER, `rating`:TEXT, `score`:INTEGER, `source`:TEXT, `reviewed_at`:TIMESTAMP, `before_state_json`:TEXT, `corrected_at`:TIMESTAMP, `idempotency_key`:TEXT, `user_answer`:TEXT, `evaluation_result`:TEXT
- Foreign keys: `review_id` -> `user_question_review`.`id` (CASCADE); `question_bank_id` -> `question_bank`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_practice_events_idempotency` UNIQUE partial (user_id, question_bank_id, idempotency_key); `idx_practice_events_user_time` (user_id, reviewed_at)

### `public_contribution_events`
- Columns: `id`:INTEGER, `request_id`:INTEGER, `actor_id`:INTEGER, `action`:TEXT, `from_status`:TEXT, `to_status`:TEXT, `metadata_json`:TEXT, `created_at`:TIMESTAMP
- Foreign keys: `actor_id` -> `users`.`id` (NO ACTION); `request_id` -> `public_contribution_requests`.`id` (CASCADE)
- Indexes: none

### `public_contribution_items`
- Columns: `id`:INTEGER, `request_id`:INTEGER, `source_item_type`:TEXT, `source_item_id`:INTEGER, `ordinal`:INTEGER, `status`:TEXT, `snapshot_json`:TEXT, `review_json`:TEXT, `public_detail_id`:INTEGER, `error_message`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP
- Foreign keys: `public_detail_id` -> `questions_detail`.`id` (NO ACTION); `request_id` -> `public_contribution_requests`.`id` (CASCADE)
- Indexes: `idx_public_contribution_items_status` (request_id, status, ordinal); `sqlite_autoindex_public_contribution_items_1` UNIQUE (request_id, ordinal)

### `public_contribution_requests`
- Columns: `id`:INTEGER, `source_type`:TEXT, `source_id`:INTEGER, `requester_id`:INTEGER, `status`:TEXT, `snapshot_json`:TEXT, `review_json`:TEXT, `public_interview_id`:INTEGER, `public_jd_id`:INTEGER, `reviewed_by`:INTEGER, `reviewed_at`:TIMESTAMP, `error_message`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `revision`:INTEGER, `review_projection_json`:TEXT, `projection_hash`:TEXT
- Foreign keys: `public_jd_id` -> `jd`.`id` (NO ACTION); `public_interview_id` -> `interview`.`id` (NO ACTION); `reviewed_by` -> `users`.`id` (NO ACTION); `requester_id` -> `users`.`id` (NO ACTION)
- Indexes: `idx_public_contribution_request_owner` (requester_id, created_at); `idx_public_contribution_request_status` (status, source_type, updated_at); `uq_public_contribution_active_source` UNIQUE partial (source_type, source_id, requester_id)

### `quality_audit`
- Columns: `id`:INTEGER, `audited_at`:TEXT, `sample_size`:INTEGER, `total_variants`:INTEGER, `inconsistent_count`:INTEGER, `duplicate_count`:INTEGER, `coverage_count`:INTEGER, `inconsistent_rate`:REAL, `duplicate_rate`:REAL, `coverage_rate`:REAL, `report_path`:TEXT, `triggered_cleanup`:INTEGER
- Foreign keys: none
- Indexes: none

### `quality_issue`
- Columns: `id`:INTEGER, `qb_id`:INTEGER, `source_qb_id`:INTEGER, `variant_index`:INTEGER, `issue_type`:TEXT, `suggested_action`:TEXT, `reason`:TEXT, `suggested_value`:TEXT, `confidence`:REAL, `status`:TEXT, `created_at`:TEXT, `reviewed_at`:TEXT, `reviewed_by`:INTEGER, `target_qb_id`:INTEGER, `new_cat2`:TEXT, `review_version`:TEXT, `review_task_id`:TEXT, `trigger_reason`:TEXT, `variant_key`:TEXT, `source_question`:TEXT, `source_cat2`:TEXT, `issue_fingerprint`:TEXT, `superseded_at`:TEXT, `superseded_by`:INTEGER
- Foreign keys: `qb_id` -> `question_bank`.`id` (SET NULL)
- Indexes: `idx_quality_issue_fingerprint` (issue_fingerprint); `idx_quality_issue_review_version` (qb_id, review_version, status); `uq_quality_issue_active_fingerprint` UNIQUE partial (issue_fingerprint); `uq_quality_issue_review_version` UNIQUE partial (qb_id, review_version, issue_type, variant_key)

### `question_bank`
- Columns: `id`:INTEGER, `question`:TEXT, `cat1`:TEXT, `cat2`:TEXT, `tags`:TEXT, `difficulty`:TEXT, `frequency`:INTEGER, `ai_answer`:TEXT, `sources`:TEXT, `original_questions`:TEXT, `original_question_sources`:TEXT, `is_starred`:INTEGER, `owner_id`:INTEGER, `submitted_by`:INTEGER, `status`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `deleted_at`:TIMESTAMP, `job_position`:TEXT, `question_manually_edited`:INTEGER, `embedding`:BLOB, `cluster_id`:INTEGER, `embedding_model`:TEXT, `embedding_dim`:INTEGER, `answer_sources`:TEXT, `cluster_label`:TEXT, `answer_review_status`:TEXT, `answer_review_issues`:TEXT
- Foreign keys: `submitted_by` -> `users`.`id` (NO ACTION); `owner_id` -> `users`.`id` (NO ACTION)
- Indexes: `idx_qb_cluster_id` (cluster_id); `idx_qb_deleted_owner_status` (deleted_at, owner_id, status); `idx_qb_job_position_visibility` (job_position, deleted_at, owner_id, status); `idx_qb_job_position` (job_position); `idx_qb_owner_status_position` (owner_id, status, job_position); `idx_qb_owner_status` (owner_id, status); `idx_qb_visibility_review_state` (visibility, review_state, job_position, deleted_at)

### `question_detail_scope_quarantine`
- Columns: `detail_id`:INTEGER, `url`:TEXT, `reason`:TEXT, `candidate_count`:INTEGER, `created_at`:TIMESTAMP
- Foreign keys: `detail_id` -> `questions_detail`.`id` (CASCADE)
- Indexes: `idx_qd_scope_quarantine_reason` (reason, created_at)

### `question_fts`
- Columns: `question`:ANY, `cat1`:ANY, `cat2`:ANY, `tags`:ANY, `ai_answer`:ANY
- Foreign keys: none
- Indexes: none

### `question_original_item_sources`
- Columns: `id`:INTEGER, `original_item_id`:INTEGER, `url`:TEXT, `company`:TEXT, `round`:TEXT, `created_at`:TIMESTAMP, `deleted_at`:TIMESTAMP
- Foreign keys: `original_item_id` -> `question_original_items`.`id` (CASCADE)
- Indexes: `idx_qois_deleted_at` (deleted_at); `idx_qois_oi` (original_item_id); `idx_qois_url` (url); `sqlite_autoindex_question_original_item_sources_1` UNIQUE (original_item_id, url)

### `question_original_items`
- Columns: `id`:INTEGER, `question_bank_id`:INTEGER, `question_text`:TEXT, `created_at`:TIMESTAMP, `deleted_at`:TIMESTAMP
- Foreign keys: `question_bank_id` -> `question_bank`.`id` (CASCADE)
- Indexes: `idx_qoi_deleted_at` (deleted_at); `idx_qoi_qb` (question_bank_id); `idx_qoi_text` (question_text); `sqlite_autoindex_question_original_items_1` UNIQUE (question_bank_id, question_text)

### `question_position`
- Columns: `question_id`:INTEGER, `position_id`:INTEGER
- Foreign keys: `position_id` -> `job_positions`.`id` (CASCADE); `question_id` -> `question_bank`.`id` (CASCADE)
- Indexes: `idx_qp_position_question` (position_id, question_id); `idx_qp_position` (position_id); `sqlite_autoindex_question_position_1` UNIQUE (question_id, position_id)

### `question_promotion_requests`
- Columns: `pending_question_id`:INTEGER, `source_question_id`:INTEGER, `requester_id`:INTEGER, `snapshot_json`:TEXT, `review_projection_json`:TEXT, `target_question_id`:INTEGER, `status`:TEXT, `reviewer_id`:INTEGER, `created_at`:TEXT, `reviewed_at`:TEXT
- Foreign keys: `reviewer_id` -> `users`.`id` (NO ACTION); `target_question_id` -> `question_bank`.`id` (SET NULL); `requester_id` -> `users`.`id` (NO ACTION); `source_question_id` -> `question_bank`.`id` (SET NULL)
- Indexes: `uq_pending_question_promotion` UNIQUE partial (source_question_id)

### `question_resolutions`
- Columns: `id`:INTEGER, `detail_id`:INTEGER, `occurrence_scope`:TEXT, `occurrence_owner_id`:INTEGER, `canonical_id`:INTEGER, `canonical_scope`:TEXT, `status`:TEXT, `taxonomy_version`:TEXT, `pipeline_version`:TEXT, `input_version`:INTEGER, `confidence`:REAL, `decided_at`:TEXT, `invalidated_at`:TEXT, `reason`:TEXT
- Foreign keys: `canonical_id` -> `question_bank`.`id` (NO ACTION); `occurrence_owner_id` -> `users`.`id` (NO ACTION); `detail_id` -> `questions_detail`.`id` (NO ACTION)
- Indexes: `idx_question_resolution_canonical` (canonical_id); `uq_question_resolution_current` UNIQUE partial (detail_id)

### `question_sources`
- Columns: `id`:INTEGER, `question_bank_id`:INTEGER, `url`:TEXT, `company`:TEXT, `round`:TEXT, `created_at`:TIMESTAMP, `deleted_at`:TIMESTAMP
- Foreign keys: `question_bank_id` -> `question_bank`.`id` (CASCADE)
- Indexes: `idx_qs_deleted_at` (deleted_at); `idx_qs_qb` (question_bank_id); `idx_qs_url` (url); `sqlite_autoindex_question_sources_1` UNIQUE (question_bank_id, url)

### `question_variant_owners`
- Columns: `normalized_question`:TEXT, `question_bank_id`:INTEGER, `question_text`:TEXT, `updated_at`:TIMESTAMP
- Foreign keys: `question_bank_id` -> `question_bank`.`id` (CASCADE)
- Indexes: `idx_question_variant_owners_qb` (question_bank_id); `sqlite_autoindex_question_variant_owners_1` UNIQUE (normalized_question)

### `questions_detail`
- Columns: `id`:INTEGER, `interview_id`:INTEGER, `question`:TEXT, `cat1`:TEXT, `cat2`:TEXT, `tags`:TEXT, `difficulty`:TEXT, `diff_tag`:TEXT, `answer`:TEXT, `url`:TEXT, `source`:TEXT, `owner_id`:INTEGER, `status`:TEXT, `deleted_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `company`:TEXT, `round`:TEXT, `job_position`:TEXT, `question_type`:TEXT, `dimension`:TEXT, `import_id`:TEXT, `source_ordinal`:INTEGER
- Foreign keys: `import_id` -> `upload_imports`.`id` (NO ACTION)
- Indexes: `idx_qd_interview_question_type` (interview_id, question_type); `idx_qd_question` (question); `idx_qd_url` (url); `uq_questions_detail_import_ordinal` UNIQUE partial (import_id, source_ordinal)

### `refresh_tokens`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `jti`:TEXT, `expires_at`:TEXT, `created_at`:TIMESTAMP, `remember`:INTEGER, `ip_address`:TEXT, `user_agent`:TEXT, `family_id`:TEXT
- Foreign keys: `user_id` -> `users`.`id` (NO ACTION)
- Indexes: `idx_rt_expires` (expires_at); `idx_rt_family` (family_id); `idx_rt_jti` (jti); `idx_rt_user` (user_id); `sqlite_autoindex_refresh_tokens_1` UNIQUE (jti)

### `schema_version`
- Columns: `version`:INTEGER, `name`:TEXT, `applied_at`:TIMESTAMP
- Foreign keys: none
- Indexes: none

### `taxonomy`
- Columns: `id`:INTEGER, `position_name`:TEXT, `categories_json`:TEXT, `is_default`:INTEGER, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `source`:TEXT, `owner_id`:INTEGER, `is_public`:INTEGER, `tags_json`:TEXT
- Foreign keys: none
- Indexes: `idx_taxonomy_position_owner` UNIQUE (position_name, source, owner_id); `uq_taxonomy_public` UNIQUE partial (position_name, source)

### `upload_attempts`
- Columns: `id`:INTEGER, `import_id`:TEXT, `attempt_no`:INTEGER, `status`:TEXT, `requested_by`:INTEGER, `created_at`:TEXT, `completed_at`:TEXT
- Foreign keys: `requested_by` -> `users`.`id` (NO ACTION); `import_id` -> `upload_imports`.`id` (NO ACTION)
- Indexes: `uq_upload_attempts_import_no` UNIQUE (import_id, attempt_no); `uq_upload_attempts_one_active` UNIQUE partial (import_id)

### `upload_imports`
- Columns: `id`:TEXT, `requester_id`:INTEGER, `idempotency_key`:TEXT, `request_hash`:TEXT, `target_intent`:TEXT, `source_type`:TEXT, `resolved_type`:TEXT, `position_id`:INTEGER, `position_name`:TEXT, `input_version`:INTEGER, `pipeline_version`:TEXT, `policy_json`:TEXT, `payload_json`:TEXT, `status`:TEXT, `current_attempt_no`:INTEGER, `interview_id`:INTEGER, `contribution_request_id`:INTEGER, `revision`:INTEGER, `error_code`:TEXT, `error_message`:TEXT, `created_at`:TEXT, `updated_at`:TEXT, `completed_at`:TEXT, `payload_expires_at`:TEXT
- Foreign keys: `requester_id` -> `users`.`id` (NO ACTION)
- Indexes: `idx_upload_imports_requester` (requester_id, created_at); `sqlite_autoindex_upload_imports_1` UNIQUE (id); `uq_upload_imports_idempotency` UNIQUE (requester_id, idempotency_key)

### `upload_llm_calls`
- Columns: `id`:INTEGER, `root_import_id`:TEXT, `stage`:TEXT, `unit_key`:TEXT, `call_key`:TEXT, `credential_scope`:TEXT, `payer_type`:TEXT, `payer_user_id`:INTEGER, `provider`:TEXT, `model`:TEXT, `config_fingerprint`:TEXT, `status`:TEXT, `input_tokens`:INTEGER, `output_tokens`:INTEGER, `started_at`:TEXT, `finished_at`:TEXT, `error_code`:TEXT, `api_format`:TEXT
- Foreign keys: `payer_user_id` -> `users`.`id` (NO ACTION); `root_import_id` -> `upload_imports`.`id` (NO ACTION)
- Indexes: `idx_upload_llm_calls_root` (root_import_id, stage); `sqlite_autoindex_upload_llm_calls_1` UNIQUE (call_key)

### `upload_scope_leases`
- Columns: `scope_key`:TEXT, `holder_token`:TEXT, `generation`:INTEGER, `locked_until`:TEXT
- Foreign keys: none
- Indexes: `sqlite_autoindex_upload_scope_leases_1` UNIQUE (scope_key)

### `upload_stage_results`
- Columns: `id`:INTEGER, `import_id`:TEXT, `stage`:TEXT, `unit_key`:TEXT, `input_version`:INTEGER, `pipeline_version`:TEXT, `status`:TEXT, `result_json`:TEXT, `output_hash`:TEXT, `error_code`:TEXT, `retryable`:INTEGER, `job_id`:INTEGER, `created_at`:TEXT, `updated_at`:TEXT
- Foreign keys: `import_id` -> `upload_imports`.`id` (NO ACTION)
- Indexes: `uq_upload_stage_result` UNIQUE (import_id, stage, unit_key, input_version)

### `user_interview_distribution_preferences`
- Columns: `user_id`:INTEGER, `job_position`:TEXT, `mode`:TEXT, `target_question_count`:INTEGER, `custom_distribution`:TEXT, `selected_experience_id`:INTEGER, `style_strength`:TEXT, `updated_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `sqlite_autoindex_user_interview_distribution_preferences_1` UNIQUE (user_id, job_position)

### `user_llm_config`
- Columns: `user_id`:INTEGER, `api_key`:TEXT, `base_url`:TEXT, `model`:TEXT, `timeout`:INTEGER, `updated_at`:TIMESTAMP, `api_format`:TEXT, `thinking`:INTEGER
- Foreign keys: `user_id` -> `users`.`id` (CASCADE)
- Indexes: none

### `user_practice_history`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `question_bank_id`:INTEGER, `user_answer`:TEXT, `evaluation_result`:TEXT, `score`:INTEGER, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP
- Foreign keys: `question_bank_id` -> `question_bank`.`id` (CASCADE); `user_id` -> `users`.`id` (NO ACTION)
- Indexes: `idx_uph_question` (question_bank_id); `idx_uph_user_date` (user_id, created_at); `idx_uph_user` (user_id)

### `user_profile`
- Columns: `key`:TEXT, `value`:TEXT, `updated_at`:TIMESTAMP
- Foreign keys: none
- Indexes: `sqlite_autoindex_user_profile_1` UNIQUE (key)

### `user_question_review`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `question_bank_id`:INTEGER, `state`:TEXT, `proficiency`:INTEGER, `review_count`:INTEGER, `lapse_count`:INTEGER, `last_rating`:TEXT, `last_score`:INTEGER, `last_reviewed_at`:TIMESTAMP, `next_review_at`:TIMESTAMP, `interval_days`:REAL, `ease_factor`:REAL, `stability_days`:REAL, `difficulty`:REAL, `algorithm`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP
- Foreign keys: `question_bank_id` -> `question_bank`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_uqr_due` (user_id, next_review_at); `idx_uqr_proficiency` (user_id, proficiency); `idx_uqr_user_updated` (user_id, updated_at); `sqlite_autoindex_user_question_review_1` UNIQUE (user_id, question_bank_id)

### `user_question_view`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `question_bank_id`:INTEGER, `is_starred`:INTEGER, `personal_tags`:TEXT, `note`:TEXT, `user_answer`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP
- Foreign keys: `question_bank_id` -> `question_bank`.`id` (CASCADE); `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_uqv_user_question` UNIQUE (user_id, question_bank_id); `idx_uqv_user_starred` (user_id, is_starred)

### `user_recruitment_pref`
- Columns: `user_id`:INTEGER, `graduation_year`:INTEGER, `batch`:TEXT, `daily_capacity`:INTEGER, `updated_at`:TIMESTAMP, `pace`:TEXT
- Foreign keys: none
- Indexes: none

### `user_resumes`
- Columns: `id`:INTEGER, `user_id`:INTEGER, `filename`:TEXT, `raw_text`:TEXT, `created_at`:TIMESTAMP, `updated_at`:TIMESTAMP, `optimized_text`:TEXT, `optimization_points`:TEXT, `optimized_position`:TEXT, `optimized_at`:TIMESTAMP
- Foreign keys: `user_id` -> `users`.`id` (CASCADE)
- Indexes: `idx_resume_user_unique` UNIQUE (user_id); `idx_resume_user` (user_id)

### `user_search_config`
- Columns: `user_id`:INTEGER, `provider`:TEXT, `api_key`:TEXT, `base_url`:TEXT, `enabled`:INTEGER, `updated_at`:TIMESTAMP
- Foreign keys: `user_id` -> `users`.`id` (CASCADE)
- Indexes: none

### `users`
- Columns: `id`:INTEGER, `username`:TEXT, `password_hash`:TEXT, `is_admin`:INTEGER, `bank_mode`:TEXT, `created_at`:TIMESTAMP, `current_position_id`:INTEGER, `updated_at`:TIMESTAMP, `personal_position`:TEXT, `email`:TEXT, `share_default`:TEXT
- Foreign keys: `current_position_id` -> `job_positions`.`id` (SET NULL)
- Indexes: `idx_users_email_unique` UNIQUE partial (email); `sqlite_autoindex_users_1` UNIQUE (username)
