#!/usr/bin/env python3
"""历史上传任务迁移（AC-023）：dry-run 优先，manifest 匹配才 apply。

用法：

    python backend/scripts/backfill_upload_recovery.py \
        --database /tmp/upload-recovery-test.db --dry-run --report /tmp/manifest.json

    python backend/scripts/backfill_upload_recovery.py \
        --database /tmp/upload-recovery-test.db --apply --manifest /tmp/manifest.json

输出只包含 counts、候选 job id 与冲突原因，绝不打印题干、图片或 Key。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.upload_backfill import (  # noqa: E402
    ManifestMismatch,
    apply_backfill,
    plan_backfill,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="上传任务历史迁移")
    parser.add_argument("--database", required=True, help="目标 SQLite 路径")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只规划并输出报告（默认推荐）")
    mode.add_argument("--apply", action="store_true", help="按 manifest 应用")
    parser.add_argument("--report", help="dry-run 报告输出路径")
    parser.add_argument("--manifest", help="apply 时要求匹配的 manifest 路径")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        if args.dry_run:
            report = plan_backfill(conn)
            if args.report:
                Path(args.report).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2, default=str)
                )
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "chains_scanned": report["chains_scanned"],
                        "imports_created": report["imports_created"],
                        "attempts_created": report["attempts_created"],
                        "jobs_linked": report["jobs_linked"],
                        "ambiguous": len(report["ambiguous"]),
                        "manifest_hash": report["manifest_hash"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        if not args.manifest:
            print("--apply 必须提供 --manifest", file=sys.stderr)
            return 2
        manifest = json.loads(Path(args.manifest).read_text())
        try:
            result = apply_backfill(
                conn, manifest=manifest, expected_manifest_hash=manifest.get("manifest_hash")
            )
        except ManifestMismatch as exc:
            conn.rollback()
            print(f"拒绝应用：{exc}", file=sys.stderr)
            return 3
        conn.commit()
        print(json.dumps({"mode": "apply", **result}, ensure_ascii=False, default=str))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
