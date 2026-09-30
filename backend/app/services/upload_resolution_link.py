"""逐题持久化接入（R05 / AC-005、AC-019）。

真实 persist 节点的收尾：把逐题明细关联回上传根任务（import_id +
source_ordinal），并为每一道保留题登记 resolution：

- 命中公共/个人规范题 → ``matched``（不改公共 sources/frequency）；
- 生成新规范题 → ``created``；
- 匹配失败且不允许落新题 → ``failed``（可恢复失败，不产生 phantom canonical）。

``link_details_to_import`` 由 ``agents/submit/persist_personal.py`` 在 v2
root 上下文存在时调用；事务由调用方持有，本模块不 commit。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


def link_details_to_import(
    conn,
    *,
    import_id: str,
    detail_ids: list[int],
    ordinals: dict[int, int],
    actor_id: int,
    stage: str = "persist",
    matches: dict[int, dict | None] | None = None,
    write_unmatched: bool = False,
) -> int:
    """为逐题明细写 import_id/source_ordinal 与 resolution（幂等）。"""

    from app.services.question_resolution import record_resolution

    linked = 0
    for detail_id in detail_ids:
        detail_id = int(detail_id)
        ordinal = int(ordinals.get(detail_id, 0) or 0)
        conn.execute(
            "UPDATE questions_detail SET import_id = ?, source_ordinal = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (import_id, ordinal, detail_id),
        )
        linked += 1

        match = (matches or {}).get(detail_id)
        if match:
            record_resolution(
                conn,
                detail_id=detail_id,
                occurrence_scope="private",
                occurrence_owner_id=actor_id,
                canonical_id=int(match["canonical_id"]),
                canonical_scope=match.get("canonical_scope", "public"),
                status=match.get("status", "matched"),
                pipeline_version="upload-pipeline-v1",
            )
        elif not write_unmatched:
            # 匹配失败：持久化为可恢复失败，不落 phantom canonical（R05）
            record_resolution(
                conn,
                detail_id=detail_id,
                occurrence_scope="private",
                occurrence_owner_id=actor_id,
                canonical_id=None,
                canonical_scope="private",
                status="failed",
                pipeline_version="upload-pipeline-v1",
                reason="匹配失败，未生成新规范题",
            )
    return linked