"""来源健康检查：同签名重复面经 / internal:// 增长 / JSON 双写不一致。

持续监控缺口：这些异常不会主动告警，复发只能等用户发现。此模块提供
幂等、只读的健康检查，供 weekly cron（worker.scheduled_source_health_task）
和手动脚本（backend/scripts/check_source_health.py）复用同一份实现。
"""

import json
import os
import re
from urllib.parse import urlparse

from app.db.connection import get_db_connection

_INTERNAL_PREFIX = "internal://"


# ── 同签名重复面经 ──────────────────────────────────────────


def _duplicate_signature_groups(conn, table: str) -> list:
    """按 url_signature 分组，返回存在重复（>1 活跃记录）的组。

    只统计公共面经（owner_id IS NULL）：私有面经属于用户个人，由 submit
    入口按 owner 去重；管理员监控/合并只针对公共数据。
    """
    if "url_signature" not in {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }:
        return []
    rows = conn.execute(
        f"""
        SELECT url_signature, COUNT(*) AS n, MIN(id) AS min_id, MAX(id) AS max_id
        FROM {table}
        WHERE deleted_at IS NULL AND url_signature != '' AND owner_id IS NULL
        GROUP BY url_signature
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        """
    ).fetchall()
    return [
        {
            "signature": r[0],
            "count": r[1],
            "min_id": r[2],
            "max_id": r[3],
        }
        for r in rows
    ]


# ── internal:// 增长 ────────────────────────────────────────


def _internal_counts(conn) -> dict:
    """统计 interview / jd / question_sources 中活跃 internal:// 记录数。"""
    result = {"interview": 0, "jd": 0, "question_sources": 0}
    try:
        result["interview"] = conn.execute(
            "SELECT COUNT(*) FROM interview WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
        ).fetchone()[0]
    except Exception:
        pass
    try:
        result["jd"] = conn.execute(
            "SELECT COUNT(*) FROM jd WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
        ).fetchone()[0]
    except Exception:
        pass
    try:
        result["question_sources"] = conn.execute(
            "SELECT COUNT(*) FROM question_sources WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
        ).fetchone()[0]
    except Exception:
        pass
    return result


def _collect_internal_urls(conn) -> list:
    """收集所有活跃 internal:// 来源，标识为 <table>:<url>。"""
    urls = []
    try:
        rows = conn.execute(
            "SELECT url FROM interview WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
        ).fetchall()
        urls += [f"interview:{r[0]}" for r in rows]
    except Exception:
        pass
    try:
        rows = conn.execute(
            "SELECT url FROM jd WHERE url LIKE 'internal://%' AND deleted_at IS NULL"
        ).fetchall()
        urls += [f"jd:{r[0]}" for r in rows]
    except Exception:
        pass
    return urls


def _load_baseline(path: str | None) -> set:
    if not path or not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f).get("internal_urls", []))
    except Exception:
        return set()


def _save_baseline(path: str | None, urls: list) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"internal_urls": sorted(urls)}, f, ensure_ascii=False)


# ── JSON 双写不一致 ─────────────────────────────────────────


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
    )


def _check_dual_write(conn) -> list:
    """对比 question_bank 的 JSON 双写列与规范化表的 URL/题目集合。

    JSON 列（sources / original_questions / original_question_sources）与
    question_sources / question_original_items / question_original_item_sources
    表理论上应保持同步（dual-write）。任何一侧缺失/多出都视为不一致，
    供 cron 告警后由 fix_source_consistency.py 修复。
    """
    mismatches = []
    if not _table_exists(conn, "question_bank"):
        return mismatches
    qs_ok = _table_exists(conn, "question_sources")
    oi_ok = _table_exists(conn, "question_original_items")
    ois_ok = _table_exists(conn, "question_original_item_sources")

    rows = conn.execute(
        "SELECT id, sources, original_questions, original_question_sources "
        "FROM question_bank WHERE deleted_at IS NULL"
    ).fetchall()

    for r in rows:
        qb_id = r["id"]

        # sources JSON vs question_sources 表
        try:
            json_urls = {
                s["url"]
                for s in json.loads(r["sources"] or "[]")
                if isinstance(s, dict) and s.get("url")
            }
        except Exception:
            json_urls = None
        if json_urls is not None:
            table_urls = set()
            if qs_ok:
                try:
                    table_urls = {
                        row[0]
                        for row in conn.execute(
                            "SELECT url FROM question_sources WHERE question_bank_id = ? AND deleted_at IS NULL",
                            (qb_id,),
                        )
                    }
                except Exception:
                    table_urls = None
            if table_urls is not None and json_urls != table_urls:
                mismatches.append(
                    {
                        "qb_id": qb_id,
                        "field": "sources",
                        "json_only": sorted(json_urls - table_urls),
                        "table_only": sorted(table_urls - json_urls),
                    }
                )

        # original_questions JSON vs question_original_items 表
        try:
            json_oq = set(json.loads(r["original_questions"] or "[]"))
        except Exception:
            json_oq = None
        if json_oq is not None:
            table_oq = set()
            if oi_ok:
                try:
                    table_oq = {
                        row[0]
                        for row in conn.execute(
                            "SELECT question_text FROM question_original_items WHERE question_bank_id = ? AND deleted_at IS NULL",
                            (qb_id,),
                        )
                    }
                except Exception:
                    table_oq = None
            if table_oq is not None and json_oq != table_oq:
                mismatches.append(
                    {
                        "qb_id": qb_id,
                        "field": "original_questions",
                        "json_only": sorted(json_oq - table_oq),
                        "table_only": sorted(table_oq - json_oq),
                    }
                )

        # original_question_sources JSON vs question_original_item_sources 表
        if oi_ok and ois_ok:
            try:
                json_oqs_urls = {
                    s.get("url")
                    for item in json.loads(r["original_question_sources"] or "[]")
                    if isinstance(item, dict)
                    for s in item.get("sources", [])
                    if isinstance(s, dict) and s.get("url")
                }
            except Exception:
                json_oqs_urls = None
            if json_oqs_urls is not None:
                try:
                    table_oqs_urls = {
                        row[0]
                        for row in conn.execute(
                            """
                            SELECT qois.url
                            FROM question_original_item_sources qois
                            JOIN question_original_items qoi ON qoi.id = qois.original_item_id
                            WHERE qoi.question_bank_id = ? AND qois.deleted_at IS NULL AND qoi.deleted_at IS NULL
                            """,
                            (qb_id,),
                        )
                    }
                except Exception:
                    table_oqs_urls = None
                if table_oqs_urls is not None and json_oqs_urls != table_oqs_urls:
                    mismatches.append(
                        {
                            "qb_id": qb_id,
                            "field": "original_question_sources",
                            "json_only": sorted(json_oqs_urls - table_oqs_urls),
                            "table_only": sorted(table_oqs_urls - json_oqs_urls),
                        }
                    )

    return mismatches


# ── 入口 ────────────────────────────────────────────────────


def run_source_health_checks(conn=None, baseline_path: str | None = None) -> dict:
    """执行全部来源健康检查。

    Args:
        conn: sqlite3 connection（默认用 app.db.connection.get_db_connection()）。
        baseline_path: internal:// 基线文件路径。提供时会把本次 internal URL
            集合写入该文件，并在返回里标出相对上一次的新增项。

    Returns:
        dict: 结构化检查结果（供 worker cron 落日志 / 脚本 --json 输出）。
    """
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        current_internal = _collect_internal_urls(conn)
        baseline_exists = bool(baseline_path) and os.path.exists(baseline_path)
        baseline = _load_baseline(baseline_path)
        # 首次运行（基线文件不存在）只建立基线，不把存量 internal:// 视为新增
        new_urls = (
            sorted(set(current_internal) - baseline) if baseline_exists else []
        )
        _save_baseline(baseline_path, current_internal)

        report = {
            "duplicate_signature_groups": {
                "interview": _duplicate_signature_groups(conn, "interview"),
                "jd": _duplicate_signature_groups(conn, "jd"),
            },
            "internal": {
                **_internal_counts(conn),
                "new_urls": new_urls,
            },
            "dual_write_mismatches": _check_dual_write(conn),
        }
        report["ok"] = (
            not report["duplicate_signature_groups"]["interview"]
            and not report["duplicate_signature_groups"]["jd"]
            and not report["internal"]["new_urls"]
            and not report["dual_write_mismatches"]
        )
        return report
    finally:
        if close:
            conn.close()


# 保留通用签名逻辑给 future 变体检查（http/https/www 变体）复用
_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _generic_path_key(url: str) -> str:
    """generic 签名的归一化键：忽略协议与 www 前缀，用于变体识别。"""
    if not url or _INTERNAL_PREFIX in url:
        return ""
    parsed = urlparse(url if _HTTP_URL_RE.match(url) else f"https://{url}")
    host = parsed.netloc.removeprefix("www.")
    return f"{host}{parsed.path}".rstrip("/")
