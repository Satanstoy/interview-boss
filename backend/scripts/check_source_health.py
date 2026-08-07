#!/usr/bin/env python3
"""来源健康检查 CLI：同签名重复面经 / internal:// 增长 / JSON 双写不一致。

用法：
    python backend/scripts/check_source_health.py                # 人类可读报告
    python backend/scripts/check_source_health.py --json         # 结构化 JSON 输出
    python backend/scripts/check_source_health.py --baseline <路径>   # 指定 internal 基线文件
    python backend/scripts/check_source_health.py --exit-code   # 发现问题时以非 0 退出（cron 告警用）

说明：
    - 只读检查，绝不修改数据库；唯一副作用是更新 internal 基线文件。
    - 基线默认存 backend/data/source_health_baseline.json，用于识别
      internal:// 相对上一次的新增。
    - 复用 app.services.source_health 的同一份实现，与 weekly cron
      （worker.scheduled_source_health_task）保持口径一致。
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.services.source_health import run_source_health_checks  # noqa: E402

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "interview-boss.db",
)
DEFAULT_BASELINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "source_health_baseline.json",
)


def _fmt_groups(groups):
    if not groups:
        return "  无"
    return "".join(
        f"  - {g['signature']} × {g['count']} (id {g['min_id']}~{g['max_id']})\n"
        for g in groups
    ).rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description="来源健康检查")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help="internal 基线文件路径（默认 backend/data/source_health_baseline.json）",
    )
    parser.add_argument(
        "--exit-code", action="store_true", help="发现问题时退出码非 0"
    )
    parser.add_argument(
        "--db", default=DB_PATH, help="SQLite 数据库路径（默认生产库）"
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"❌ 数据库不存在: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        report = run_source_health_checks(conn, baseline_path=args.baseline)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("🔍 来源健康检查")
        print("=" * 60)
        dup_i = report["duplicate_signature_groups"]["interview"]
        dup_j = report["duplicate_signature_groups"]["jd"]
        print(f"1. 同签名重复面经: interview={len(dup_i)} 组, jd={len(dup_j)} 组")
        if dup_i:
            print("   interview 重复组:")
            print(_fmt_groups(dup_i))
        if dup_j:
            print("   jd 重复组:")
            print(_fmt_groups(dup_j))
        internal = report["internal"]
        print(
            f"2. internal:// 现状: interview={internal['interview']} "
            f"jd={internal['jd']} question_sources={internal['question_sources']}"
        )
        if internal["new_urls"]:
            print(f"   自上次新增 {len(internal['new_urls'])} 条:")
            for u in internal["new_urls"]:
                print(f"    - {u}")
        mismatches = report["dual_write_mismatches"]
        print(f"3. JSON 双写不一致: {len(mismatches)} 处")
        for m in mismatches[:20]:
            print(
                f"   - qb_id={m['qb_id']} {m['field']} "
                f"json_only={len(m['json_only'])} table_only={len(m['table_only'])}"
            )
        if len(mismatches) > 20:
            print(f"   ... 等 {len(mismatches)} 处")
        print("=" * 60)
        print("✅ 健康" if report["ok"] else "⚠️  发现问题，建议运行 fix_source_consistency.py 处理")

    if args.exit_code and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
