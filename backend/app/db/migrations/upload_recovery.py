"""Migration 121: upload recovery core（稳定业务任务、恢复批次、检查点、账本、scope 租约）。

设计见 specs/2026-09-29-upload-recovery/contracts.md §1.1–§1.4、§1.6、§1.7。
只做“加表/加列/加约束”，不改写历史行：旧 jobs 的 root/attempt/work_key 保持 NULL。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


def _migration_121_upload_recovery_core(conn):
    # ── 1.1 upload_imports：稳定业务任务 ─────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_imports (
            id TEXT PRIMARY KEY,
            requester_id INTEGER NOT NULL REFERENCES users(id),
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            target_intent TEXT NOT NULL CHECK (target_intent IN ('private','share')),
            source_type TEXT NOT NULL CHECK (source_type IN ('interview','jd','auto')),
            resolved_type TEXT,
            position_id INTEGER,
            position_name TEXT NOT NULL DEFAULT '',
            input_version INTEGER NOT NULL DEFAULT 1,
            pipeline_version TEXT NOT NULL,
            policy_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'queued',
            current_attempt_no INTEGER NOT NULL DEFAULT 0,
            interview_id INTEGER,
            contribution_request_id INTEGER,
            revision INTEGER NOT NULL DEFAULT 1,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            payload_expires_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_upload_imports_idempotency "
        "ON upload_imports(requester_id, idempotency_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_upload_imports_requester "
        "ON upload_imports(requester_id, created_at DESC)"
    )

    # ── 1.2 upload_attempts：恢复批次 ───────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id TEXT NOT NULL REFERENCES upload_imports(id),
            attempt_no INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','completed','failed','superseded')),
            requested_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_upload_attempts_import_no "
        "ON upload_attempts(import_id, attempt_no)"
    )
    # 一个业务任务至多一个活跃恢复批次（可多题并行，但不能整族并行恢复）
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_upload_attempts_one_active "
        "ON upload_attempts(import_id) WHERE status = 'active'"
    )

    # ── 1.3 jobs 增量：v2 归属与 fencing 代次 ───────────────────
    columns = {row[1] for row in conn.execute("PRAGMA table_info('jobs')").fetchall()}
    additions = {
        "root_import_id": "TEXT REFERENCES upload_imports(id)",
        "upload_attempt_id": "INTEGER REFERENCES upload_attempts(id)",
        "work_key": "TEXT",
        "lease_generation": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
    # 同一 root 的同一 work_key 至多一个在途 job；旧 job（root NULL）不受影响
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_v2_work_active "
        "ON jobs(root_import_id, job_type, work_key) "
        "WHERE root_import_id IS NOT NULL AND work_key IS NOT NULL "
        "AND status IN ('pending','queued','running')"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_v2_root ON jobs(root_import_id)")

    # ── 1.4 upload_stage_results：阶段检查点 ────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_stage_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id TEXT NOT NULL REFERENCES upload_imports(id),
            stage TEXT NOT NULL,
            unit_key TEXT NOT NULL,
            input_version INTEGER NOT NULL DEFAULT 1,
            pipeline_version TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('pending','running','succeeded','skipped','failed','needs_action')),
            result_json TEXT,
            output_hash TEXT,
            error_code TEXT,
            retryable INTEGER NOT NULL DEFAULT 0,
            job_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_upload_stage_result "
        "ON upload_stage_results(import_id, stage, unit_key, input_version)"
    )

    # ── 1.7 upload_llm_calls：调用账本 ──────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_import_id TEXT REFERENCES upload_imports(id),
            stage TEXT NOT NULL,
            unit_key TEXT NOT NULL DEFAULT '',
            call_key TEXT NOT NULL UNIQUE,
            credential_scope TEXT NOT NULL,
            payer_type TEXT NOT NULL,
            payer_user_id INTEGER REFERENCES users(id),
            provider TEXT,
            model TEXT,
            config_fingerprint TEXT,
            status TEXT NOT NULL DEFAULT 'reserved'
                CHECK (status IN ('reserved','succeeded','failed','unknown')),
            input_tokens INTEGER,
            output_tokens INTEGER,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            error_code TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_upload_llm_calls_root "
        "ON upload_llm_calls(root_import_id, stage)"
    )

    # ── 1.6 upload_scope_leases：公共池串行写入 ─────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upload_scope_leases (
            scope_key TEXT PRIMARY KEY,
            holder_token TEXT,
            generation INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT
        )
        """
    )

    logger.info("migration_121: upload recovery core tables are ready")


def _migration_125_upload_llm_api_format(conn):
    """Record the protocol actually used for each durable provider attempt."""

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('upload_llm_calls')").fetchall()
    }
    if "api_format" not in columns:
        conn.execute("ALTER TABLE upload_llm_calls ADD COLUMN api_format TEXT")
