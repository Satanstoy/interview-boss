"""同签名重复公共面经的列表与合并。

只处理公共面经（interview/jd 表 `owner_id IS NULL`）。私有面经属于用户
个人，由 submit 入口按 owner 去重；管理员监控/合并绝不触碰私有数据。

合并语义：同 url_signature 的重复公共记录保留最早（MIN id），软删其余，
并把 questions_detail 重挂、question_sources/question_original_item_sources
URL 归一 + 去重、question_bank JSON 双写列同步归一。软删可恢复，不加历史表。

本模块替代 `backend/scripts/fix_source_consistency.py` 内联的合并逻辑，
供 admin 路由与运维脚本复用同一份实现（避免口径漂移）。
"""

import json
import logging

from fastapi import HTTPException

logger = logging.getLogger("interview-boss")


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


def _public_qb_ids(conn):
    """所有公共 question_bank id 子查询（合并只归一公共题来源）。"""
    return "SELECT id FROM question_bank WHERE owner_id IS NULL"


def _public_oi_ids(conn):
    """所有公共 question_original_items id 子查询（经 qb JOIN 限定）。"""
    return (
        "SELECT qoi.id FROM question_original_items qoi "
        "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
        "WHERE qoi.deleted_at IS NULL AND qb.owner_id IS NULL"
    )


def list_duplicate_groups(conn, table: str = "interview") -> list:
    """列出同签名重复的公共记录组（每组 count>1）。

    Returns: [{signature, table, count, keep_id, records: [{id, url}]}]
    """
    if table not in ("interview", "jd"):
        raise HTTPException(status_code=400, detail=f"不支持的表类型: {table}")
    rows = conn.execute(
        f"""
        SELECT url_signature, COUNT(*) AS n, MIN(id) AS min_id
        FROM {table}
        WHERE deleted_at IS NULL AND url_signature != '' AND owner_id IS NULL
        GROUP BY url_signature
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        """
    ).fetchall()
    groups = []
    for r in rows:
        records = [
            {"id": row[0], "url": row[1]}
            for row in conn.execute(
                f"SELECT id, url FROM {table} "
                f"WHERE deleted_at IS NULL AND url_signature = ? AND owner_id IS NULL "
                f"ORDER BY id ASC",
                (r[0],),
            ).fetchall()
        ]
        groups.append(
            {
                "signature": r[0],
                "table": table,
                "count": r[1],
                "keep_id": records[0]["id"] if records else None,
                "records": records,
            }
        )
    return groups


def merge_duplicate_group(
    conn,
    signature: str,
    table: str = "interview",
    dry_run: bool = True,
    *,
    commit: bool = True,
) -> dict:
    """合并指定签名的重复公共记录组（保留最早，软删其余）。

    dry_run=True 时只计算预览（不执行任何写入，纯只读）；
    dry_run=False 时真实执行。默认 commit；批量数据修复编排器可传
    ``commit=False``，把来源合并与题簇修复放在同一事务中。

    Returns: {signature, table, dry_run, keep_id, keep_url, drop, merged_count, actions}
    """
    if not signature:
        raise HTTPException(status_code=400, detail="signature 不能为空")
    if table not in ("interview", "jd"):
        raise HTTPException(status_code=400, detail=f"不支持的表类型: {table}")

    records = conn.execute(
        f"SELECT id, url FROM {table} "
        f"WHERE deleted_at IS NULL AND url_signature = ? AND owner_id IS NULL "
        f"ORDER BY id ASC",
        (signature,),
    ).fetchall()
    if len(records) < 2:
        raise HTTPException(
            status_code=404,
            detail=f"签名 {signature} 无重复公共记录（可能已合并）",
        )

    keep_id, keep_url = records[0][0], records[0][1]
    drop_pairs = [(r[0], r[1]) for r in records[1:]]
    url_map = {drop_url: keep_url for _, drop_url in drop_pairs}

    base = {
        "signature": signature,
        "table": table,
        "dry_run": dry_run,
        "keep_id": keep_id,
        "keep_url": keep_url,
        "drop": [{"id": i, "url": u} for i, u in drop_pairs],
        "merged_count": len(drop_pairs),
    }

    # dry_run：只读预览，不执行任何写入
    if dry_run:
        return {
            **base,
            "actions": _preview_actions(conn, table, keep_id, drop_pairs),
        }

    actions = _execute_merge(conn, table, keep_id, keep_url, drop_pairs)
    if commit:
        conn.commit()
    return {**base, "actions": actions}


def _preview_actions(conn, table, keep_id, drop_pairs) -> dict:
    """只读估算将影响的行数（不写入）。"""
    actions = {k: 0 for k in _ACTIONS_KEYS}
    if table != "interview":
        actions["records_soft_deleted"] = len(drop_pairs)
        return actions
    actions["interviews_soft_deleted"] = len(drop_pairs)
    drop_ids = [d for d, _ in drop_pairs]
    ph = ",".join("?" * len(drop_ids))
    # detail 重挂 + 去重：预估挂到 keep 的 detail 数与重复的 question 数
    actions["questions_detail_rehung"] = conn.execute(
        f"SELECT COUNT(*) FROM questions_detail WHERE interview_id IN ({ph}) "
        f"AND owner_id IS NULL AND deleted_at IS NULL",
        drop_ids,
    ).fetchone()[0]
    dup_detail = conn.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT question) FROM questions_detail "
        "WHERE interview_id = ? AND owner_id IS NULL AND deleted_at IS NULL",
        (keep_id,),
    ).fetchone()[0]
    actions["questions_detail_deduped"] = max(0, dup_detail)
    # question_sources 冲突行 + 待归一行
    keep_url = None
    url_map = {u: None for _, u in drop_pairs}
    removed = 0
    normalized = 0
    for drop_url in url_map:
        removed += conn.execute(
            "SELECT COUNT(*) FROM question_sources WHERE url = ? AND deleted_at IS NULL "
            "AND question_bank_id IN (" + _public_qb_ids(conn) + ")",
            (drop_url,),
        ).fetchone()[0]
    # 归一行估算：drop 行 - 被物理删除的冲突行（近似 = 非冲突的 drop 行）
    normalized = removed  # 近似：被删除的行不再归一，未删除的 drop 行全部归一
    actions["question_sources_removed"] = removed
    actions["question_sources_normalized"] = normalized
    # qois 归一 + 软删
    for drop_url in url_map:
        actions["qois_soft_deleted"] += conn.execute(
            "SELECT COUNT(*) FROM question_original_item_sources WHERE url = ? AND deleted_at IS NULL "
            "AND original_item_id IN (" + _public_oi_ids(conn) + ")",
            (drop_url,),
        ).fetchone()[0]
    actions["qois_normalized"] = actions["qois_soft_deleted"]
    # JSON 双写列变更数
    actions["qb_json_updated"] = conn.execute(
        "SELECT COUNT(*) FROM question_bank WHERE owner_id IS NULL AND deleted_at IS NULL "
        "AND (sources LIKE ? OR original_question_sources LIKE ?)",
        (f"%{list(url_map)[0]}%", f"%{list(url_map)[0]}%"),
    ).fetchone()[0]
    return actions


_ACTIONS_KEYS = (
    "questions_detail_rehung",
    "questions_detail_deduped",
    "question_sources_normalized",
    "question_sources_removed",
    "qois_normalized",
    "qois_soft_deleted",
    "qb_json_updated",
    "interviews_soft_deleted",
    "records_soft_deleted",
)


def _execute_merge(conn, table, keep_id, keep_url, drop_pairs) -> dict:
    """真实执行合并（调用方负责 commit）。"""
    actions = {k: 0 for k in _ACTIONS_KEYS}
    url_map = {drop_url: keep_url for _, drop_url in drop_pairs}

    if table == "interview":
        for drop_id, drop_url in drop_pairs:
            cur = conn.execute(
                "UPDATE questions_detail SET interview_id = ? "
                "WHERE interview_id = ? AND owner_id IS NULL AND deleted_at IS NULL",
                (keep_id, drop_id),
            )
            actions["questions_detail_rehung"] += cur.rowcount
        cur = conn.execute(
            "DELETE FROM questions_detail WHERE deleted_at IS NULL AND owner_id IS NULL "
            "AND interview_id = ? AND id NOT IN ("
            "  SELECT MIN(id) FROM questions_detail "
            "  WHERE interview_id = ? AND owner_id IS NULL AND deleted_at IS NULL "
            "  GROUP BY question"
            ")",
            (keep_id, keep_id),
        )
        actions["questions_detail_deduped"] += cur.rowcount

        # question_sources URL 归一（仅公共 qb）：冲突行物理删除，其余 UPDATE
        for drop_id, drop_url in drop_pairs:
            cur = conn.execute(
                "DELETE FROM question_sources "
                "WHERE url = ? AND deleted_at IS NULL "
                "AND question_bank_id IN ("
                "  SELECT question_bank_id FROM question_sources "
                "  WHERE url = ? AND deleted_at IS NULL"
                ") AND question_bank_id IN (" + _public_qb_ids(conn) + ")",
                (drop_url, keep_url),
            )
            actions["question_sources_removed"] += cur.rowcount
            cur = conn.execute(
                "UPDATE question_sources SET url = ? "
                "WHERE url = ? AND deleted_at IS NULL "
                "AND question_bank_id IN (" + _public_qb_ids(conn) + ")",
                (keep_url, drop_url),
            )
            actions["question_sources_normalized"] += cur.rowcount

        # question_original_item_sources URL 归一 + 同题软删去重（公共 oi）
        for drop_id, drop_url in drop_pairs:
            cur = conn.execute(
                "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE url = ? AND deleted_at IS NULL "
                "AND original_item_id IN ("
                "  SELECT original_item_id FROM question_original_item_sources "
                "  WHERE url = ? AND deleted_at IS NULL"
                ") AND original_item_id IN (" + _public_oi_ids(conn) + ")",
                (drop_url, keep_url),
            )
            actions["qois_soft_deleted"] += cur.rowcount
            cur = conn.execute(
                "UPDATE question_original_item_sources SET url = ? "
                "WHERE url = ? AND deleted_at IS NULL "
                "AND original_item_id IN (" + _public_oi_ids(conn) + ")",
                (keep_url, drop_url),
            )
            actions["qois_normalized"] += cur.rowcount
        cur = conn.execute(
            "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE deleted_at IS NULL "
            "AND original_item_id IN (" + _public_oi_ids(conn) + ") "
            "AND id NOT IN ("
            "  SELECT MIN(id) FROM question_original_item_sources "
            "  WHERE deleted_at IS NULL AND original_item_id IN (" + _public_oi_ids(conn) + ") "
            "  GROUP BY original_item_id, url"
            ")",
        )
        actions["qois_soft_deleted"] += cur.rowcount

        # question_bank JSON 双写列同步归一（仅公共 qb）
        qb_rows = conn.execute(
            "SELECT id, sources, original_question_sources FROM question_bank "
            "WHERE owner_id IS NULL AND deleted_at IS NULL"
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
                    "UPDATE question_bank SET sources = ?, original_question_sources = ? "
                    "WHERE id = ? AND owner_id IS NULL",
                    (sources_json, oqs_json, qb_id),
                )
                from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                mark_cluster_review_pending(conn, qb_id, "source_normalized")
                actions["qb_json_updated"] += 1

        # 软删被合并的 interview
        for drop_id, drop_url in drop_pairs:
            cur = conn.execute(
                "UPDATE interview SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND deleted_at IS NULL AND owner_id IS NULL",
                (drop_id,),
            )
            actions["interviews_soft_deleted"] += cur.rowcount
    else:  # jd：仅软删重复记录
        for drop_id, drop_url in drop_pairs:
            cur = conn.execute(
                "UPDATE jd SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND deleted_at IS NULL AND owner_id IS NULL",
                (drop_id,),
            )
            actions["records_soft_deleted"] += cur.rowcount

    return actions


def merge_all_duplicate_groups(
    conn,
    table: str = "interview",
    dry_run: bool = True,
    *,
    commit: bool = True,
) -> dict:
    """合并所有同签名重复的公共记录组（运维脚本复用）。"""
    results = []
    merged_count = 0
    for group in list_duplicate_groups(conn, table):
        result = merge_duplicate_group(
            conn,
            group["signature"],
            table=table,
            dry_run=dry_run,
            commit=commit,
        )
        results.append(result)
        merged_count += result["merged_count"]
    return {"results": results, "merged_count": merged_count}
