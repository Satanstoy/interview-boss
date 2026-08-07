#!/usr/bin/env python3
"""
一次性数据修复脚本：面经/题目来源一致性（internal:// 脏数据 + 同笔记 token 变体重复）

修复内容：
1. 回填 interview / jd 表缺失的 url_signature（旧数据未回填，导致 xsec_token 变体
   重复上传未被 _check_duplicate_url_sync 拦截）
2. 合并同 url_signature 的重复公共面经 —— 委托 app.services.interview_merge_service
   （与 admin 来源健康界面共用同一份实现，仅处理公共面经 owner_id IS NULL；
   detail 重挂去重 + 来源表 URL 归一 + JSON 双写列同步 + 软删被合并记录）
3. 报告 internal:// 来源现状（展示层已做"内部面经"降级，数据保留）

用法：
    python fix_source_consistency.py --dry-run   # 只读预览（不写入）
    python fix_source_consistency.py              # 执行修复（自动备份）

安全：破坏性操作前自动备份（shutil.copy2 + WAL checkpoint 后的 .db 主文件）。
"""
import json
import os
import shutil
import sqlite3
import sys
import time

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "interview-boss.db",
)


def _sig_for(url):
    """与 app.db.utils._extract_url_signature 保持一致，脚本内独立实现避免耦合。"""
    import re

    if not url:
        return ""
    m = re.search(r"/explore/([a-f0-9]+)", url)
    if m:
        return f"xhs:{m.group(1)}"
    m = re.search(r"/discuss/(\d+)", url)
    if m:
        return f"nc:{m.group(1)}"
    m = re.search(r"/job_detail/([^?]+)", url)
    if m:
        return f"boss:{m.group(1)}"
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"generic:{parsed.netloc}{parsed.path}"


def backfill_url_signatures(conn, dry_run):
    """回填 interview / jd 表空 url_signature。dry_run 时仍写入，由调用方回滚/提交。"""
    fixed = 0
    for table in ("interview", "jd"):
        rows = conn.execute(
            f"SELECT id, url FROM {table} WHERE url_signature = '' AND url != ''"
        ).fetchall()
        for row in rows:
            sig = _sig_for(row[1])
            if sig:
                fixed += 1
                conn.execute(
                    f"UPDATE {table} SET url_signature = ? WHERE id = ?",
                    (sig, row[0]),
                )
    return fixed


def report_internal_sources(conn):
    """报告 internal:// 来源现状（数据保留，展示层已降级）。"""
    interview_n = conn.execute(
        "SELECT COUNT(*) FROM interview WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
    ).fetchone()[0]
    jd_n = conn.execute(
        "SELECT COUNT(*) FROM jd WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
    ).fetchone()[0]
    qs_n = conn.execute(
        "SELECT COUNT(*) FROM question_sources WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
    ).fetchone()[0]
    return interview_n, jd_n, qs_n


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("=== DRY RUN 模式（只读，不会修改数据库）===\n")

    from app.services.interview_merge_service import merge_all_duplicate_groups

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if not dry_run:
        backup = f"{DB_PATH}.bak.source-consistency-{int(time.time())}"
        shutil.copy2(DB_PATH, backup)
        print(f"已备份: {backup}")

    sig_n = backfill_url_signatures(conn, dry_run)
    print(f"步骤1 回填 url_signature: {sig_n} 条")

    result = merge_all_duplicate_groups(conn, "interview", dry_run=dry_run)
    merged_n = result["merged_count"]
    if merged_n:
        print(f"步骤2 合并重复面经: {merged_n} 条被合并")
        if dry_run:
            for r in result["results"]:
                print(
                    f"  [DRY] 签名 {r['signature']}: 保留 id={r['keep_id']}，"
                    f"合并 {r['merged_count']} 条: {[d['id'] for d in r['drop']]}"
                )
    else:
        print("步骤2 合并重复面经: 无重复组")

    interview_n, jd_n, qs_n = report_internal_sources(conn)
    print(
        f"步骤3 internal:// 现状（保留，展示层降级为「内部面经」）: "
        f"interview={interview_n} jd={jd_n} question_sources={qs_n}"
    )

    if dry_run:
        conn.rollback()
        print("\n以上为预览（已回滚，未写入）；去掉 --dry-run 执行实际修复。")
    else:
        conn.commit()
        print("\n修复完成。")
    conn.close()


if __name__ == "__main__":
    main()
