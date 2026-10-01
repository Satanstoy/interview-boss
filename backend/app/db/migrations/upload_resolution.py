"""Migration 122: 原题关联、发布投影/版本与队列增量。

设计见 specs/2026-09-29-upload-recovery/contracts.md §1.5、§1.6、§3.1。
只加 nullable 列与新表；旧数据保持可读，不做任何自动回填或猜测关联。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


def _migration_122_upload_resolution(conn):
    # ── 1.5 questions_detail：来源 ordinal 与 import 归属 ───────
    columns = {row[1] for row in conn.execute("PRAGMA table_info('questions_detail')").fetchall()}
    if "import_id" not in columns:
        conn.execute(
            "ALTER TABLE questions_detail ADD COLUMN import_id TEXT REFERENCES upload_imports(id)"
        )
    if "source_ordinal" not in columns:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN source_ordinal INTEGER")
    # ordinal 来自完整提取结果；过滤不能重编号，否则重试会写错题
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_questions_detail_import_ordinal "
        "ON questions_detail(import_id, source_ordinal) "
        "WHERE import_id IS NOT NULL AND source_ordinal IS NOT NULL"
    )

    # ── 1.5 question_resolutions：原题 ↔ 规范题关联 ────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS question_resolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detail_id INTEGER NOT NULL REFERENCES questions_detail(id),
            occurrence_scope TEXT NOT NULL CHECK (occurrence_scope IN ('private','public')),
            occurrence_owner_id INTEGER REFERENCES users(id),
            canonical_id INTEGER REFERENCES question_bank(id),
            canonical_scope TEXT,
            status TEXT NOT NULL
                CHECK (status IN ('matched','created','needs_review','failed','invalidated')),
            taxonomy_version TEXT,
            pipeline_version TEXT NOT NULL,
            input_version INTEGER NOT NULL DEFAULT 1,
            confidence REAL,
            decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            invalidated_at TEXT,
            reason TEXT,
            CHECK (
                (occurrence_scope = 'private' AND occurrence_owner_id IS NOT NULL)
                OR (occurrence_scope = 'public' AND occurrence_owner_id IS NULL)
            ),
            CHECK (
                (status IN ('matched','created') AND canonical_id IS NOT NULL)
                OR (status NOT IN ('matched','created'))
            )
        )
        """
    )
    # 每 detail 最多一个当前（未失效）resolution
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_question_resolution_current "
        "ON question_resolutions(detail_id) WHERE invalidated_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_question_resolution_canonical "
        "ON question_resolutions(canonical_id)"
    )

    # ── 3.1 审核投影与 revision ─────────────────────────────────
    pcr_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('public_contribution_requests')").fetchall()
    }
    if "revision" not in pcr_columns:
        conn.execute(
            "ALTER TABLE public_contribution_requests ADD COLUMN revision "
            "INTEGER NOT NULL DEFAULT 1"
        )
    if "review_projection_json" not in pcr_columns:
        conn.execute(
            "ALTER TABLE public_contribution_requests ADD COLUMN review_projection_json TEXT"
        )
    if "projection_hash" not in pcr_columns:
        conn.execute("ALTER TABLE public_contribution_requests ADD COLUMN projection_hash TEXT")

    # ── 1.6 analysis_queue：v2 归属与 scope 租约字段 ────────────
    queue_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
    }
    queue_additions = {
        "root_import_id": "TEXT REFERENCES upload_imports(id)",
        "job_id": "INTEGER",
        "lease_generation": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "TEXT",
        "claimed_at": "TEXT",
        "pipeline_version": "TEXT",
    }
    for name, definition in queue_additions.items():
        if name not in queue_columns:
            conn.execute(f"ALTER TABLE analysis_queue ADD COLUMN {name} {definition}")

    # 升级 scope 唯一约束前先报告重复，不盲删（旧数据保持原样）
    duplicates = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT 1 FROM analysis_queue "
        "  WHERE root_import_id IS NOT NULL AND question_detail_id IS NOT NULL "
        "  GROUP BY root_import_id, question_detail_id, COALESCE(owner_id, -1), "
        "           COALESCE(pipeline_version, '') "
        "  HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    if duplicates:
        logger.warning(
            "migration_122: 发现 %d 组 v2 重复队列行，未删除，需人工核对后处理",
            duplicates,
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_queue_v2_work "
        "ON analysis_queue(root_import_id, question_detail_id, COALESCE(owner_id, -1), "
        "COALESCE(pipeline_version, '')) "
        "WHERE root_import_id IS NOT NULL AND question_detail_id IS NOT NULL"
    )

    logger.info("migration_122: upload resolution and publication columns are ready")


def _migration_123_public_publish_gate(conn):
    """migration 123：公共面经发布门槛（AC-015 / README §5.3）。

    审批通过不等于 published：公共贡献物化出的 ``interview`` 在处理完成前
    不能被普通用户的面经/统计/来源接口查询出来。旧数据与私人面经默认
    ``published``，只有新物化的公共申请从 ``pending`` 开始。
    """

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('interview')").fetchall()
    }
    if "publish_status" not in columns:
        conn.execute(
            "ALTER TABLE interview ADD COLUMN publish_status TEXT NOT NULL "
            "DEFAULT 'published'"
        )
    # 存量行（含历史公共面经）一律视为已发布，不改变既有可见性
    conn.execute(
        "UPDATE interview SET publish_status = 'published' "
        "WHERE publish_status IS NULL OR publish_status = ''"
    )
    logger.info("migration_123: public publish gate is ready")
