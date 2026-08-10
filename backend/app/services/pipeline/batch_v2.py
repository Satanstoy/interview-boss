"""
批处理逻辑：增量聚类、完整流水线、孤岛碎片整理（v2 版本）

新增功能：
- compact_singletons_in_db 增加"孤岛匹配已有聚类"步骤
"""

import json
import asyncio
import logging
from typing import List, Dict

from app.db.connection import get_db_connection, run_db
from app.db.question_bank_sources import (
    delete_all_for_qb,
    insert_source,
    insert_original_item,
)
from app.services.clustering import process_incremental_batch, _cluster_unmatched
from .sanitize import BATCH_SIZE, sanitize_batch
from .queue import (
    dequeue_batch,
    mark_batch_done,
    mark_batch_failed,
    should_trigger_clustering,
)
from .writer import apply_matched, insert_new_clusters, tag_and_write_details
from .compact import _do_merge_to_existing

logger = logging.getLogger("interview-boss")

_EXISTING_CLUSTERS_PAGE_SIZE = 100


# ============================================================
# 孤岛碎片整理（Compaction）- v2 版本
# ============================================================


async def compact_singletons_in_db_v2(user_id: int = None) -> Dict:
    """孤岛碎片整理：对 frequency=1 的独立题按 cat2 做二次合并

    流程：
    1. 加载所有 frequency>1 的题目作为已有聚类
    2. 加载所有 frequency=1 的题目
    3. 按 cat2 分组后，对每组：
       - 先用 MATCH_EXISTING_PROMPT 把 frequency=1 的题和 frequency>1 的题做匹配
       - 匹配上的：把 frequency=1 的题合并到对应的 frequency>1 聚类
       - 未匹配的：再走现有的互相聚类逻辑
    """
    _SINGLETONS_PAGE_SIZE = 200

    # Step 1: 加载所有 frequency>1 的题目作为已有聚类
    def _load_existing_clusters():
        import numpy as np

        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question, cat2, embedding "
            "FROM question_bank "
            "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
            "AND frequency > 1 "
            "ORDER BY id"
        ).fetchall()
        result = []
        for r in rows:
            entry = {"id": r["id"], "question": r["question"], "cat2": r["cat2"] or ""}
            if r["embedding"]:
                entry["embedding"] = np.frombuffer(
                    r["embedding"], dtype=np.float32
                ).copy()
            result.append(entry)
        return result

    existing_clusters = await run_db(_load_existing_clusters)
    logger.info(f"[Compaction] 加载 {len(existing_clusters)} 个已有聚类 (frequency>1)")

    # 按 cat2 分组已有聚类
    existing_by_cat2 = {}
    for c in existing_clusters:
        cat2 = c["cat2"]
        existing_by_cat2.setdefault(cat2, []).append(c)

    # Step 2: 加载所有 frequency=1 的题目
    singletons = []
    offset = 0
    while True:

        def _load_page(_offset=offset):
            conn = get_db_connection()
            rows = conn.execute(
                "SELECT id, question, cat1, cat2, tags, difficulty, sources, "
                "original_questions, original_question_sources, ai_answer "
                "FROM question_bank "
                "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
                "AND frequency = 1 "
                "ORDER BY id LIMIT ? OFFSET ?",
                (_SINGLETONS_PAGE_SIZE, _offset),
            ).fetchall()
            return [dict(r) for r in rows]

        page = await run_db(_load_page)
        if not page:
            break
        singletons.extend(page)
        offset += len(page)
        del page
        await asyncio.sleep(0)

    if not singletons:
        return {
            "total_singletons": 0,
            "merged": 0,
            "remaining": 0,
            "matched_to_existing": 0,
        }

    logger.info(f"[Compaction] 加载 {len(singletons)} 个孤立题 (frequency=1)")

    # 按 cat2 分组
    cat2_groups: Dict[str, List[Dict]] = {}
    for r in singletons:
        cat2 = r.get("cat2") or ""
        cat2_groups.setdefault(cat2, []).append(r)

    # Step 3: 先用 MATCH_EXISTING_PROMPT 把 frequency=1 的题和 frequency>1 的题做匹配
    total_matched_to_existing = 0
    remaining_singletons = []

    for cat2, group in cat2_groups.items():
        if not group:
            continue

        existing = existing_by_cat2.get(cat2, [])
        if not existing:
            # 没有已有聚类，所有题都进入下一步
            remaining_singletons.extend(group)
            continue

        # 构建 new_rows 格式
        new_rows = [
            {"id": r["id"], "question": r["question"], "cat2": cat2} for r in group
        ]

        # 调用 process_incremental_batch 进行匹配
        try:
            result = await process_incremental_batch(
                new_rows, {cat2: existing}, user_id=user_id
            )

            matched = result.get("matched_to_existing", [])
            new_clusters = result.get("new_clusters", [])

            if matched:
                total_matched_to_existing += len(matched)
                logger.info(
                    f"[Compaction] cat2={cat2}: {len(matched)} 题匹配到已有聚类"
                )

                # 执行合并：把 frequency=1 的题合并到对应的 frequency>1 聚类
                for match in matched:

                    def _do_match_merge(m=match):
                        conn = get_db_connection()
                        conn.execute("BEGIN")
                        try:
                            entry = conn.execute(
                                "SELECT id, question, cat1, cat2, tags, difficulty, frequency, "
                                "sources, original_questions, original_question_sources, ai_answer "
                                "FROM question_bank WHERE id = ?",
                                (m["qd_id"],),
                            ).fetchone()
                            if not entry:
                                conn.execute("ROLLBACK")
                                return
                            _do_merge_to_existing(
                                int(m["cluster_id"]),
                                dict(entry),
                                operation_type="compaction",
                                phase="phase1.5",
                                cat2=cat2,
                                operator_id=user_id,
                                confidence=float(m.get("confidence") or 0),
                            )
                            conn.execute("COMMIT")
                            return
                        except Exception:
                            conn.execute("ROLLBACK")
                            raise

                    await run_db(_do_match_merge)

            # 未匹配的题进入下一步
            matched_ids = {str(m["qd_id"]) for m in matched}
            for r in group:
                if str(r["id"]) not in matched_ids:
                    remaining_singletons.append(r)

        except Exception as e:
            logger.warning(f"[Compaction] cat2={cat2} 匹配已有聚类失败: {e}")
            remaining_singletons.extend(group)

    logger.info(f"[Compaction] 匹配到已有聚类: {total_matched_to_existing} 题")
    logger.info(f"[Compaction] 剩余孤立题: {len(remaining_singletons)} 题")

    # Step 4: 对剩余的孤立题进行互相聚类
    # 按 cat2 分组
    remaining_cat2_groups: Dict[str, List[Dict]] = {}
    for r in remaining_singletons:
        cat2 = r.get("cat2") or ""
        remaining_cat2_groups.setdefault(cat2, []).append(r)

    total_merged = 0

    for cat2, group in remaining_cat2_groups.items():
        if len(group) < 2:
            continue

        items_for_cluster = [{"id": r["id"], "question": r["question"]} for r in group]

        try:
            clusters = await _cluster_unmatched(items_for_cluster, user_id)
        except Exception as e:
            logger.warning(f"[Compaction] cat2={cat2} 聚类失败: {e}")
            continue

        for cluster in clusters:
            ids = cluster.get("ids", [])
            if len(ids) < 2:
                continue

            qb_entries = []
            for sid in ids:
                entry = next((r for r in group if str(r["id"]) == str(sid)), None)
                if entry:
                    qb_entries.append(entry)
            if len(qb_entries) < 2:
                continue

            qb_entries.sort(key=lambda x: (-x.get("frequency", 1), x["id"]))
            survivor = qb_entries[0]
            to_merge = qb_entries[1:]

            def _do_merge(s=survivor, m=to_merge):
                conn = get_db_connection()
                conn.execute("BEGIN")
                try:
                    existing = conn.execute(
                        "SELECT sources, original_questions, original_question_sources, ai_answer "
                        "FROM question_bank WHERE id = ?",
                        (s["id"],),
                    ).fetchone()
                    try:
                        s_src = (
                            json.loads(existing["sources"])
                            if existing["sources"]
                            else []
                        )
                    except Exception:
                        s_src = []
                    try:
                        s_oqs = (
                            json.loads(existing["original_questions"])
                            if existing["original_questions"]
                            else []
                        )
                    except Exception:
                        s_oqs = []
                    try:
                        s_oqs_src = (
                            json.loads(existing["original_question_sources"])
                            if existing["original_question_sources"]
                            else []
                        )
                    except Exception:
                        s_oqs_src = []

                    # 保留 ai_answer：如果 survivor 没有，从被合并的题中获取
                    s_ai_answer = existing["ai_answer"] if existing else None
                    if not s_ai_answer:
                        for entry in m:
                            if entry.get("ai_answer"):
                                s_ai_answer = entry["ai_answer"]
                                break

                    seen_urls = {x.get("url") for x in s_src}

                    for entry in m:
                        try:
                            o_src = (
                                json.loads(entry["sources"]) if entry["sources"] else []
                            )
                        except Exception:
                            o_src = []
                        for x in o_src:
                            u = x.get("url", "")
                            if u and u not in seen_urls:
                                s_src.append(x)
                                seen_urls.add(u)

                        try:
                            o_oqs = (
                                json.loads(entry["original_questions"])
                                if entry["original_questions"]
                                else []
                            )
                        except Exception:
                            o_oqs = []
                        for oq in o_oqs:
                            if oq and oq not in s_oqs:
                                s_oqs.append(oq)

                        try:
                            o_oqs_src = (
                                json.loads(entry["original_question_sources"])
                                if entry["original_question_sources"]
                                else []
                            )
                        except Exception:
                            o_oqs_src = []
                        s_oqs_src.extend(o_oqs_src)

                        conn.execute(
                            "DELETE FROM question_bank WHERE id = ?", (entry["id"],)
                        )
                        conn.execute(
                            "DELETE FROM question_position WHERE question_id = ?",
                            (entry["id"],),
                        )

                    conn.execute(
                        "UPDATE question_bank SET frequency = ?, sources = ?, "
                        "original_questions = ?, original_question_sources = ?, "
                        "ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            len(s_oqs),
                            json.dumps(s_src, ensure_ascii=False),
                            json.dumps(s_oqs, ensure_ascii=False),
                            json.dumps(s_oqs_src, ensure_ascii=False),
                            s_ai_answer,
                            s["id"],
                        ),
                    )

                    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                    mark_cluster_review_pending(conn, s["id"], "merge:compaction_v2")

                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            await run_db(_do_merge)
            total_merged += len(to_merge)

        await asyncio.sleep(0.5)

    return {
        "total_singletons": len(singletons),
        "merged": total_merged,
        "remaining": len(remaining_singletons) - total_merged,
        "matched_to_existing": total_matched_to_existing,
    }
