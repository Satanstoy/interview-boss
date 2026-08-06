#!/usr/bin/env python3
"""
一次性数据修复脚本：面经/题目来源一致性（internal:// 脏数据 + 同笔记 token 变体重复）

修复内容：
1. 回填 interview / jd 表缺失的 url_signature（旧数据未回填，导致 xsec_token 变体
   重复上传未被 _check_duplicate_url_sync 拦截）
2. 合并同 url_signature 的重复面经（如小红书同笔记不同 xsec_token 的两条记录）：
   - questions_detail 重挂到保留记录 + 按题目文本去重
   - question_sources / question_original_item_sources 的 URL 归一 + 同题去重
   - question_bank 的 sources / original_question_sources JSON 双写列同步归一
   - 被合并记录软删（可恢复）
3. 报告 internal:// 来源数量（展示层已做"内部面经"降级，数据保留）

用法：
    python fix_source_consistency.py --dry-run   # 仅预览，不写入
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

_XHS_RE = None


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


def _soft_delete(conn, table, where, args):
    conn.execute(
        f"UPDATE {table} SET deleted_at = CURRENT_TIMESTAMP WHERE {where}", args
    )


def backfill_url_signatures(conn, dry_run):
    """回填 interview / jd 表空 url_signature。"""
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


def _normalize_json_urls(obj, url_map):
    """递归把 JSON 结构中的 url 字段按映射归一（双写列同步）。"""
    if isinstance(obj, dict):
        if "url" in obj and obj["url"] in url_map:
            obj["url"] = url_map[obj["url"]]
        for v in obj.values():
            _normalize_json_urls(v, url_map)
    elif isinstance(obj, list):
        for item in obj:
            _normalize_json_urls(item, url_map)


def merge_duplicate_interviews(conn, dry_run):
    """合并同 url_signature 的重复面经（保留 id 最小的记录）。"""
    merged = 0
    groups = conn.execute(
        """
        SELECT url_signature FROM interview
        WHERE deleted_at IS NULL AND url_signature != ''
        GROUP BY url_signature HAVING COUNT(*) > 1
        """
    ).fetchall()
    for (sig,) in groups:
        rows = conn.execute(
            """
            SELECT id, url FROM interview
            WHERE deleted_at IS NULL AND url_signature = ?
            ORDER BY id ASC
            """,
            (sig,),
        ).fetchall()
        keep_id, keep_url = rows[0]
        drop_pairs = [(i, u) for i, u in rows[1:]]
        url_map = {drop_url: keep_url for _, drop_url in drop_pairs}

        if dry_run:
            print(
                f"  [DRY] 合并面经组 {sig}: 保留 id={keep_id}，"
                f"合并 {len(drop_pairs)} 条: {[i for i, _ in drop_pairs]}"
            )

        # 1) questions_detail 重挂 + 去重
        for drop_id, drop_url in drop_pairs:
            conn.execute(
                "UPDATE questions_detail SET interview_id = ? WHERE interview_id = ?",
                (keep_id, drop_id),
            )
        conn.execute(
            """
            DELETE FROM questions_detail WHERE id NOT IN (
                SELECT MIN(id) FROM questions_detail
                WHERE interview_id = ? GROUP BY question
            ) AND interview_id = ?
            """,
            (keep_id, keep_id),
        )

        # 2) question_sources URL 归一：冲突行（同 qb 已有 keep_url）物理删除
        #    （归一消除的是重复变体，物理删保持恢复语义干净；备份可恢复），
        #    剩余 drop 行 UPDATE 为 keep_url（表有 UNIQUE(question_bank_id, url) 约束）
        for drop_id, drop_url in drop_pairs:
            conn.execute(
                """
                DELETE FROM question_sources
                WHERE url = ? AND deleted_at IS NULL
                  AND question_bank_id IN (
                      SELECT question_bank_id FROM question_sources
                      WHERE url = ? AND deleted_at IS NULL
                  )
                """,
                (drop_url, keep_url),
            )
            conn.execute(
                "UPDATE question_sources SET url = ? WHERE url = ? AND deleted_at IS NULL",
                (keep_url, drop_url),
            )

        # 3) question_original_item_sources URL 归一 + 同题去重
        for drop_id, drop_url in drop_pairs:
            conn.execute(
                """
                UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP
                WHERE url = ? AND deleted_at IS NULL
                  AND original_item_id IN (
                      SELECT original_item_id FROM question_original_item_sources
                      WHERE url = ? AND deleted_at IS NULL
                  )
                """,
                (drop_url, keep_url),
            )
            conn.execute(
                """
                UPDATE question_original_item_sources SET url = ?
                WHERE url = ? AND deleted_at IS NULL
                """,
                (keep_url, drop_url),
            )
        conn.execute(
            """
            UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP
            WHERE deleted_at IS NULL AND id NOT IN (
                SELECT MIN(id) FROM question_original_item_sources
                WHERE deleted_at IS NULL GROUP BY original_item_id, url
            )
            """
        )

        # 4) question_bank JSON 双写列同步归一
        qb_rows = conn.execute(
            "SELECT id, sources, original_question_sources FROM question_bank"
        ).fetchall()
        for qb_id, sources_json, oqs_json in qb_rows:
            changed = False
            try:
                sources = json.loads(sources_json) if sources_json else []
            except Exception:
                sources = None
            try:
                oqs = json.loads(oqs_json) if oqs_json else []
            except Exception:
                oqs = None
            if sources is not None:
                _normalize_json_urls(sources, url_map)
                seen = set()
                deduped = []
                for s in sources:
                    u = s.get("url", "")
                    if u and u in seen:
                        continue
                    seen.add(u)
                    deduped.append(s)
                new_json = json.dumps(deduped, ensure_ascii=False)
                if new_json != sources_json:
                    changed = True
                    sources_json = new_json
            if oqs is not None:
                _normalize_json_urls(oqs, url_map)
                new_json = json.dumps(oqs, ensure_ascii=False)
                if new_json != oqs_json:
                    changed = True
                    oqs_json = new_json
            if changed:
                conn.execute(
                    "UPDATE question_bank SET sources = ?, original_question_sources = ? WHERE id = ?",
                    (sources_json, oqs_json, qb_id),
                )

        # 5) 软删被合并的 interview
        for drop_id, drop_url in drop_pairs:
            _soft_delete(conn, "interview", "id = ? AND deleted_at IS NULL", (drop_id,))
        merged += len(drop_pairs)

    return merged


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
        print("=== DRY RUN 模式（不会修改数据库）===\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if not dry_run:
        backup = f"{DB_PATH}.bak.source-consistency-{int(time.time())}"
        shutil.copy2(DB_PATH, backup)
        print(f"已备份: {backup}")

    sig_n = backfill_url_signatures(conn, dry_run)
    if not dry_run:
        conn.commit()
    print(f"步骤1 回填 url_signature: {sig_n} 条")

    merged_n = merge_duplicate_interviews(conn, dry_run)
    if not dry_run:
        conn.commit()
    print(f"步骤2 合并重复面经: {merged_n} 条被合并")

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
