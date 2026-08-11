#!/usr/bin/env python3
"""按安全顺序修复公共面经题库脏数据。

流程：
1. 回填 URL signature，并合并同来源的重复公共面经/JD；
2. 按规范化原始题目重整跨题簇归属；
3. 关闭会被归属修复取代的 pending 质量卡；
4. 重建原始题目 ownership claim，并执行一致性验收。

默认只 dry-run。执行时必须为每个跨题簇重复组显式提供
``--canonical "原始题目=question_bank_id"``，避免脚本替人工做语义归属决定。

示例：
    python backend/scripts/fix_question_data_quality.py --dry-run --db backend/data/interview-boss.db
    python backend/scripts/fix_question_data_quality.py --execute \
      --canonical "关于研究生方向，搞模型的吗？为什么没有延续该方向学习就业？=6004"
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.db.migrations import run_migrations  # noqa: E402
from app.services.clustering.clusterer import _normalize_question_text  # noqa: E402
from app.services.interview_merge_service import (  # noqa: E402
    list_duplicate_groups,
    merge_all_duplicate_groups,
)
from app.db.migrations.sources import (  # noqa: E402
    ensure_public_url_signature_unique_indexes,
)
from app.services.question_variant_reconciliation import (  # noqa: E402
    normalize_original_question,
    reconcile_cross_cluster_variants,
    scan_cross_cluster_variant_groups,
    sync_all_normalized_tables,
)
from app.services.source_health import _check_dual_write  # noqa: E402

DEFAULT_DB = os.path.join(ROOT, "data", "interview-boss.db")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="公共题库来源与原始题目归属修复")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只读预览（默认）")
    mode.add_argument("--execute", action="store_true", help="执行修复")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument(
        "--canonical",
        action="append",
        default=[],
        metavar="QUESTION=QB_ID",
        help="重复原始题目的规范题簇，可重复传入",
    )
    parser.add_argument("--reviewed-by", type=int, default=None, help="审计人 ID")
    return parser.parse_args()


def _canonical_map(values: list[str]) -> dict[str, int]:
    result = {}
    for value in values:
        question, separator, raw_id = value.rpartition("=")
        if not separator or not question.strip():
            raise ValueError(f"--canonical 格式错误，应为 QUESTION=QB_ID: {value}")
        try:
            qb_id = int(raw_id)
        except ValueError as exc:
            raise ValueError(f"--canonical 的 QB_ID 不是整数: {value}") from exc
        result[normalize_original_question(question)] = qb_id
    return result


def _safe_backup(db_path: str) -> str:
    """Use SQLite backup API so WAL pages are included in the snapshot."""

    backup_path = f"{db_path}.bak.quality-repair-{int(time.time())}"
    source = sqlite3.connect(db_path, timeout=30)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        target.commit()
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"备份完整性检查失败: {result}")
    finally:
        target.close()
        source.close()
    return backup_path


def _backfill_url_signatures(conn, execute: bool) -> int:
    from app.db.utils import _extract_url_signature

    count = 0
    for table in ("interview", "jd"):
        rows = conn.execute(
            f"SELECT id, url FROM {table} WHERE deleted_at IS NULL "
            "AND (url_signature IS NULL OR url_signature = '') AND url != ''"
        ).fetchall()
        for row in rows:
            signature = _extract_url_signature(row["url"])
            if not signature:
                continue
            count += 1
            if execute:
                conn.execute(
                    f"UPDATE {table} SET url_signature = ? WHERE id = ?",
                    (signature, row["id"]),
                )
    return count


def _validate(conn) -> dict:
    source_duplicates = {
        table: len(list_duplicate_groups(conn, table))
        for table in ("interview", "jd")
    }
    variant_groups = scan_cross_cluster_variant_groups(conn)
    dual_write = _check_dual_write(conn)
    ownership_conflicts = conn.execute(
        "SELECT COUNT(*) FROM ("
        "SELECT normalized_question FROM question_variant_owners "
        "GROUP BY normalized_question HAVING COUNT(*) > 1"
        ")"
    ).fetchone()[0]
    return {
        "source_duplicates": source_duplicates,
        "cross_cluster_variant_groups": len(variant_groups),
        "dual_write_mismatches": len(dual_write),
        "ownership_conflicts": ownership_conflicts,
        "ok": (
            not any(source_duplicates.values())
            and not variant_groups
            and not dual_write
            and ownership_conflicts == 0
        ),
    }


def _run(args: argparse.Namespace) -> int:
    execute = bool(args.execute)
    canonical_by_key = _canonical_map(args.canonical)
    if not os.path.exists(args.db):
        print(f"数据库不存在: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        before_groups = scan_cross_cluster_variant_groups(conn)
        missing = [
            group["normalized_question"]
            for group in before_groups
            if group["normalized_question"] not in canonical_by_key
        ]
        if execute and missing:
            print(
                json.dumps(
                    {
                        "error": "execute 需要为所有跨题簇重复组指定 --canonical",
                        "missing_normalized_questions": missing,
                        "cluster_ids": [group["cluster_ids"] for group in before_groups if group["normalized_question"] in missing],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2

        if not execute:
            signature_count = _backfill_url_signatures(conn, execute=False)
            source_preview = {
                table: merge_all_duplicate_groups(conn, table, dry_run=True)
                for table in ("interview", "jd")
            }
            variant_preview = reconcile_cross_cluster_variants(
                conn, canonical_by_key, dry_run=True
            )
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "url_signatures_to_backfill": signature_count,
                        "dual_write_mismatches_before": len(_check_dual_write(conn)),
                        "source_preview": source_preview,
                        "variant_preview": variant_preview,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        backup_path = _safe_backup(args.db)
        # The migration is deliberately applied only after the backup. It is
        # idempotent and creates the atomic claim table for future writes.
        run_migrations(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            signatures = _backfill_url_signatures(conn, execute=True)
            source_results = {
                table: merge_all_duplicate_groups(
                    conn, table, dry_run=False, commit=False
                )
                for table in ("interview", "jd")
            }
            variant_result = reconcile_cross_cluster_variants(
                conn,
                canonical_by_key,
                dry_run=False,
                reviewed_by=args.reviewed_by,
            )
            normalized_rows_synced = sync_all_normalized_tables(conn)
            validation = _validate(conn)
            if not validation["ok"]:
                raise RuntimeError(
                    "修复后验收失败，事务将回滚: "
                    + json.dumps(validation, ensure_ascii=False)
                )
            source_indexes = ensure_public_url_signature_unique_indexes(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        print(
            json.dumps(
                {
                    "dry_run": False,
                    "backup": backup_path,
                    "url_signatures_backfilled": signatures,
                    "source_results": source_results,
                    "variant_result": variant_result,
                    "normalized_rows_synced": normalized_rows_synced,
                    "validation": validation,
                    "source_indexes": source_indexes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(_run(_parse_args()))
    except (ValueError, RuntimeError) as exc:
        print(f"修复失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
