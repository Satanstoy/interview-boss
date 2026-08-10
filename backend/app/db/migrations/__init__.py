"""Database migrations package.

Each migration function is self-contained and idempotent.
Functions are organized by domain in submodules and re-exported here
so that ``from app.db.migrations import _migration_033_cluster_id`` continues to work.
"""

import logging

# ── Domain submodules ──────────────────────────────────────────────────────
from app.db.migrations.question_bank import (
    _migration_001_base_tables,
    _migration_002_question_bank,
    _migration_004_jd_interview_qd_columns,
    _migration_005_question_bank_extra_columns,
    _migration_006_job_positions,
    _migration_007_taxonomy,
    _migration_063_answer_sources,
)
from app.db.migrations.auth import (
    _migration_003_auth_tables,
    _migration_010_users_extra_columns,
    _migration_012_admin_seed,
    _migration_015_refresh_tokens_extra,
    _migration_051_share_default,
    _migration_052_mcp_tokens,
    _migration_054_mcp_token_seed,
    _migration_060_search_config,
    _migration_065_llm_api_format,
)
from app.db.migrations.data_repair import (
    _migration_011_data_backfills,
    _migration_014_data_repairs,
    _migration_017_backfill_normalized_sources,
    _migration_018_composite_indexes,
    _migration_019_fix_cascades,
    _migration_020_drop_json_columns,
    _migration_021_performance_indexes,
)
from app.db.migrations.sources import (
    _migration_016_normalized_source_tables,
    _migration_023_duplicate_of,
    _migration_047_soft_delete_sources,
)
from app.db.migrations.view import (
    _migration_008_user_question_view,
    _migration_013_user_question_view_user_answer,
)
from app.db.migrations.practice import _migration_055_practice_review_system
from app.db.migrations.practice_decks import _migration_056_custom_practice_decks
from app.db.migrations.practice_defaults import _migration_057_practice_default_decks
from app.db.migrations.practice_performance import _migration_059_practice_queue_indexes
from app.db.migrations.chat import (
    _migration_024_chat_tables,
    _migration_025_question_fts,
    _migration_026_populate_fts,
    _migration_027_memory_summary,
    _migration_028_session_notes,
    _migration_037_conversation_metadata,
    _migration_038_chat_conversation_position,
    _migration_040_chat_tool_traces,
    _migration_041_asked_questions,
    _migration_043_chat_turns,
    _migration_044_turn_replay_and_revision,
    _migration_045_durable_side_effects,
    _migration_046_structured_turns,
)
from app.db.migrations.coding import (
    _migration_029_user_resumes,
    _migration_030_coding_module,
    _migration_031_coding_scores,
    _migration_053_coding_library,
    _migration_058_coding_playlist_order,
)
from app.db.migrations.resume import _migration_061_resume_optimization
from app.db.migrations.clustering import (
    _migration_032_embedding_column,
    _migration_033_cluster_id,
    _migration_034_backfill_confidence,
    _migration_035_split_e_category,
    _migration_037_backfill_embeddings,
    _migration_039_merge_review_tables,
    _migration_048_embedding_metadata,
    _migration_066_cluster_label,
    _migration_067_quality_audit,
    _migration_068_quality_issue,
    _classify_e_question,
)
from app.db.migrations.admin_assistant import (
    _migration_069_admin_assistant_log,
    _migration_070_quality_issue_target,
    _migration_071_quality_issue_new_cat2,
    _migration_073_quality_issue_source_snapshot,
)
from app.db.migrations.jobs import (
    _migration_009_analysis_queue,
    _migration_022_jobs_table,
    _migration_036_job_payloads,
    _migration_049_analysis_queue_owner,
    _migration_050_pipeline_metrics,
)
from app.db.migrations.interview_distribution import (
    _migration_042_interview_distribution,
)
from app.db.migrations.recruitment import (
    _migration_062_user_recruitment_pref,
    _migration_064_user_recruitment_pace,
)

logger = logging.getLogger("interview-boss")

# ---------------------------------------------------------------------------
# Migration registry — ordered list of (version, name, function)
# ---------------------------------------------------------------------------

_MIGRATIONS = [
    (1, "base_tables", _migration_001_base_tables),
    (2, "question_bank", _migration_002_question_bank),
    (3, "auth_tables", _migration_003_auth_tables),
    (4, "jd_interview_qd_columns", _migration_004_jd_interview_qd_columns),
    (5, "question_bank_extra_columns", _migration_005_question_bank_extra_columns),
    (6, "job_positions", _migration_006_job_positions),
    (7, "taxonomy", _migration_007_taxonomy),
    (8, "user_question_view", _migration_008_user_question_view),
    (9, "analysis_queue", _migration_009_analysis_queue),
    (10, "users_extra_columns", _migration_010_users_extra_columns),
    (11, "data_backfills", _migration_011_data_backfills),
    (12, "admin_seed", _migration_012_admin_seed),
    (
        13,
        "user_question_view_user_answer",
        _migration_013_user_question_view_user_answer,
    ),
    (14, "data_repairs", _migration_014_data_repairs),
    (15, "refresh_tokens_extra", _migration_015_refresh_tokens_extra),
    (16, "normalized_source_tables", _migration_016_normalized_source_tables),
    (17, "backfill_normalized_sources", _migration_017_backfill_normalized_sources),
    (18, "composite_indexes", _migration_018_composite_indexes),
    (19, "fix_cascades", _migration_019_fix_cascades),
    # (20, 'drop_json_columns',         _migration_020_drop_json_columns),  # TODO: 启用前需先移除写路径中的 JSON 列引用
    (21, "performance_indexes", _migration_021_performance_indexes),
    (22, "jobs_table", _migration_022_jobs_table),
    (23, "duplicate_of", _migration_023_duplicate_of),
    (24, "chat_tables", _migration_024_chat_tables),
    (25, "question_fts", _migration_025_question_fts),
    (26, "populate_fts", _migration_026_populate_fts),
    (27, "memory_summary", _migration_027_memory_summary),
    (28, "session_notes", _migration_028_session_notes),
    (29, "user_resumes", _migration_029_user_resumes),
    (30, "coding_module", _migration_030_coding_module),
    (31, "coding_scores", _migration_031_coding_scores),
    (32, "embedding_column", _migration_032_embedding_column),
    (33, "cluster_id", _migration_033_cluster_id),
    (34, "backfill_confidence", _migration_034_backfill_confidence),
    (35, "split_e_category", _migration_035_split_e_category),
    (36, "job_payloads", _migration_036_job_payloads),
    (37, "conversation_metadata", _migration_037_conversation_metadata),
    (38, "chat_conversation_position", _migration_038_chat_conversation_position),
    (39, "merge_review_tables", _migration_039_merge_review_tables),
    (40, "chat_tool_traces", _migration_040_chat_tool_traces),
    (41, "asked_questions", _migration_041_asked_questions),
    (42, "interview_distribution", _migration_042_interview_distribution),
    (43, "chat_turns", _migration_043_chat_turns),
    (44, "turn_replay_and_revision", _migration_044_turn_replay_and_revision),
    (45, "durable_side_effects", _migration_045_durable_side_effects),
    (46, "structured_turns", _migration_046_structured_turns),
    (47, "soft_delete_sources", _migration_047_soft_delete_sources),
    (48, "embedding_metadata", _migration_048_embedding_metadata),
    (49, "analysis_queue_owner", _migration_049_analysis_queue_owner),
    (50, "pipeline_metrics", _migration_050_pipeline_metrics),
    (51, "share_default", _migration_051_share_default),
    (52, "mcp_tokens", _migration_052_mcp_tokens),
    (53, "coding_library", _migration_053_coding_library),
    (54, "mcp_token_seed", _migration_054_mcp_token_seed),
    (55, "practice_review_system", _migration_055_practice_review_system),
    (56, "custom_practice_decks", _migration_056_custom_practice_decks),
    (57, "practice_default_decks", _migration_057_practice_default_decks),
    (58, "coding_playlist_order", _migration_058_coding_playlist_order),
    (59, "practice_queue_indexes", _migration_059_practice_queue_indexes),
    (60, "search_config", _migration_060_search_config),
    (61, "resume_optimization", _migration_061_resume_optimization),
    (62, "user_recruitment_pref", _migration_062_user_recruitment_pref),
    (63, "answer_sources", _migration_063_answer_sources),
    (64, "user_recruitment_pace", _migration_064_user_recruitment_pace),
    (65, "llm_api_format", _migration_065_llm_api_format),
    (66, "cluster_label", _migration_066_cluster_label),
    (67, "quality_audit", _migration_067_quality_audit),
    (68, "quality_issue", _migration_068_quality_issue),
    (69, "admin_assistant_log", _migration_069_admin_assistant_log),
    (70, "quality_issue_target", _migration_070_quality_issue_target),
    (71, "quality_issue_new_cat2", _migration_071_quality_issue_new_cat2),
    (73, "quality_issue_source_snapshot", _migration_073_quality_issue_source_snapshot),
]


def run_migrations(conn):
    """Apply all pending migrations in order."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    applied = {
        row[0]
        for row in cursor.execute("SELECT version FROM schema_version").fetchall()
    }
    for version, name, func in _MIGRATIONS:
        if version in applied:
            continue
        logger.info(f"Applying migration {version:03d}: {name}")
        cursor.execute("BEGIN")
        try:
            func(conn)
            cursor.execute(
                "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                (version, name),
            )
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise
