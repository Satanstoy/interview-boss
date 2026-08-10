#!/usr/bin/env python3
"""Backfill version-aware cluster review state and durable evaluation tasks.

Default mode is a read-only dry run.  Use ``--apply`` only after the current
quality worker has finished.  Existing question text, answers, sources,
merge_history and quality_issue rows are never rewritten by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.db.migrations import run_migrations  # noqa: E402
from app.services.cluster_review_lifecycle import (  # noqa: E402
    backfill_cluster_review_state,
    review_state_summary,
)

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "interview-boss.db",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="回填聚类质量审核生命周期")
    parser.add_argument("--db", default=DB_PATH, help="SQLite 数据库路径")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="正式写入 schema/state/task；默认只读 dry-run",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"数据库不存在: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        if args.apply:
            # 迁移本身只创建新 schema，不改写旧业务数据；随后回填在同一
            # 连接中提交，便于运维明确看到一次完整变更。
            run_migrations(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "cluster_review_state" not in tables:
            print(
                "缺少 schema 072，请先使用 --apply 执行迁移；dry-run 不会自动修改 schema。",
                file=sys.stderr,
            )
            return 2

        report = backfill_cluster_review_state(conn, dry_run=not args.apply)
        summary = review_state_summary(conn)
        if args.apply:
            conn.commit()
    finally:
        conn.close()

    result = {"report": report, "summary": summary, "mode": "apply" if args.apply else "dry-run"}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
