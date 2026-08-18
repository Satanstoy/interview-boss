"""Database migrations package.

Each migration function is self-contained and idempotent.
Functions are organized by domain in submodules and re-exported here
so that ``from app.db.migrations import _migration_033_cluster_id`` continues to work.
"""

import datetime
import logging
import os
import sqlite3

from app.core.config import DB_PATH
from app.db.migrations.data_repair_2 import migration_091_repair_fk_orphans

# 破坏性迁移版本（含数据删除/表重建/格式转换）：执行前自动整库备份 + 临时关闭 FK 约束
DESTRUCTIVE_VERSIONS = {81, 82, 84, 85, 86, 90, 91, 92}


def _backup_before_destructive(db_path: str, version: int, name: str) -> str | None:
    """破坏性迁移前用 SQLite backup API 生成整库快照；源文件不存在则跳过。"""
    if not db_path or not os.path.exists(db_path):
        return None
    backups_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backups_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backups_dir, f"pre_migration_v{version:03d}_{stamp}.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    logger.info("已备份数据库到 %s（迁移 %03d %s 前）", dest, version, name)
    return dest


def _conn_is_memory(conn) -> bool:
    """迁移连接是否指向内存库（测试环境），避免误备份生产文件。"""
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        return bool(row and row[1] == "main" and row[2] == "")
    except Exception:
        return True


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
    _migration_020_drop_json_columns,  # noqa: F401 — migration re-export
    _migration_021_performance_indexes,
)
from app.db.migrations.sources import (
    _migration_016_normalized_source_tables,
    _migration_023_duplicate_of,
    _migration_047_soft_delete_sources,
    ensure_public_url_signature_unique_indexes,  # noqa: F401 — migration re-export
)
from app.db.migrations.view import (
    _migration_008_user_question_view,
    _migration_013_user_question_view_user_answer,
)
from app.db.migrations.practice import _migration_055_practice_review_system
from app.db.migrations.practice_decks import _migration_056_custom_practice_decks
from app.db.migrations.practice_defaults import _migration_057_practice_default_decks
from app.db.migrations.practice_performance import _migration_059_practice_queue_indexes
from app.db.migrations.practice_corrections import _migration_078_practice_review_corrections
from app.db.migrations.practice_idempotency import _migration_088_practice_review_idempotency
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
from app.db.migrations.resume import (
    _migration_061_resume_optimization,
    _migration_097_resume_user_unique,
)
from app.db.migrations.clustering import (
    _migration_032_embedding_column,
    _migration_033_cluster_id,
    _migration_034_backfill_confidence,
    _migration_035_split_e_category,
    _migration_037_backfill_embeddings,  # noqa: F401 — migration re-export
    _migration_039_merge_review_tables,
    _migration_048_embedding_metadata,
    _migration_066_cluster_label,
    _migration_067_quality_audit,
    _migration_068_quality_issue,
    _migration_072_cluster_review_lifecycle,
    _migration_076_question_variant_ownership,
    _migration_077_quality_issue_identity,
    _classify_e_question,  # noqa: F401 — migration re-export
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
    _migration_074_durable_job_lifecycle,
    _migration_075_job_retry_lineage,
)
from app.db.migrations.auth import _migration_079_users_email_unique
from app.db.migrations.interview_distribution import (
    _migration_042_interview_distribution,
)
from app.db.migrations.recruitment import (
    _migration_062_user_recruitment_pref,
    _migration_064_user_recruitment_pace,
)
from app.db.migrations.interview_import import _migration_080_interview_import
from app.db.migrations.evaluation import _migration_087_evaluation_control_plane
from app.db.migrations.evaluation_dual_axis import _migration_093_evaluation_dual_axis
from app.db.migrations.evaluation_experiment import _migration_095_evaluation_experiment
from app.db.migrations.practice import _migration_094_review_event_answer_snapshot, _migration_096_review_event_evaluation_snapshot
from app.db.migrations.schema_hygiene import (
    _migration_081_cleanup_fk_orphans,
    _migration_082_fts_rebuild_triggers,
    _migration_083_index_housekeeping,
    _migration_084_normalize_timestamps_jobs,
    _migration_085_add_fk_declarations,
    _migration_086_drop_dead_columns_indexes,
)
from app.db.migrations.llm import _migration_089_llm_usage
from app.db.migrations.schema_hygiene_2 import (
    migration_090_analysis_queue_fk,
    migration_092_preserve_quality_issue_history,
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
    (72, "cluster_review_lifecycle", _migration_072_cluster_review_lifecycle),
    (73, "quality_issue_source_snapshot", _migration_073_quality_issue_source_snapshot),
    (74, "durable_job_lifecycle", _migration_074_durable_job_lifecycle),
    (75, "job_retry_lineage", _migration_075_job_retry_lineage),
    (76, "question_variant_ownership", _migration_076_question_variant_ownership),
    (77, "quality_issue_identity", _migration_077_quality_issue_identity),
    (78, "practice_review_corrections", _migration_078_practice_review_corrections),
    (79, "users_email_unique", _migration_079_users_email_unique),
    (80, "interview_import", _migration_080_interview_import),
    (81, "cleanup_fk_orphans", _migration_081_cleanup_fk_orphans),
    (82, "fts_rebuild_triggers", _migration_082_fts_rebuild_triggers),
    (83, "index_housekeeping", _migration_083_index_housekeeping),
    (84, "normalize_timestamps_jobs", _migration_084_normalize_timestamps_jobs),
    (85, "add_fk_declarations", _migration_085_add_fk_declarations),
    (86, "drop_dead_columns_indexes", _migration_086_drop_dead_columns_indexes),
    (87, "evaluation_control_plane", _migration_087_evaluation_control_plane),
    (88, "practice_review_idempotency", _migration_088_practice_review_idempotency),
    (89, "llm_usage", _migration_089_llm_usage),
    (90, "analysis_queue_fk_cascade", migration_090_analysis_queue_fk),
    (91, "repair_fk_orphans", migration_091_repair_fk_orphans),
    (92, "preserve_quality_issue_history", migration_092_preserve_quality_issue_history),
    (93, "evaluation_dual_axis", _migration_093_evaluation_dual_axis),
    (94, "review_event_answer_snapshot", _migration_094_review_event_answer_snapshot),
    (95, "evaluation_experiment", _migration_095_evaluation_experiment),
    (96, "review_event_evaluation_snapshot", _migration_096_review_event_evaluation_snapshot),
    (97, "resume_user_unique", _migration_097_resume_user_unique),
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
        destructive = version in DESTRUCTIVE_VERSIONS
        fk_was_on = False
        if destructive:
            # 数据安全：破坏性迁移前整库备份（内存库/文件缺失则跳过）
            if not _conn_is_memory(conn):
                _backup_before_destructive(DB_PATH, version, name)
            # PRAGMA foreign_keys 只能在事务外切换；表重建期间必须关闭，
            # 否则 DROP 父表会触发隐式 DELETE 级联清空子表
            fk_was_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
            if fk_was_on:
                conn.execute("PRAGMA foreign_keys=OFF")
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
        finally:
            if destructive and fk_was_on:
                conn.execute("PRAGMA foreign_keys=ON")
