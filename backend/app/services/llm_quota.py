"""per-user daily LLM call quota（audit D5，3 级）。

LLM 消耗端点原来没有 per-user 配额，单个用户可无限调用以放大成本。
这里按「调用次数」实施每日配额：每个用户每天在 llm_usage 表累加调用次数，
超过 DAILY_LLM_CALL_LIMIT（默认 200 次/日，可用环境变量覆盖）即拒绝后续调用。

表结构（migration 089）：
    llm_usage(user_id, day, call_count, total_tokens, UNIQUE(user_id, day))。
以 (user_id, day) 为主键，天然实现「跨天自动重置」。

重点：
- 以调用次数计费（不强制按 token 限流），total_tokens 仅累计用于统计。
- DB 操作统一走 get_db_connection + run_db，便于在 async 上下文安全调用。
- 本服务只返回 bool（是否允许本次调用），是否抛 429 由调用方（routers）决定。
"""

import os
import logging
from datetime import date

from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

# 每日 LLM 调用次数上限（可配置；服务测试会以 limit 参数覆盖）
DAILY_LLM_CALL_LIMIT = int(os.environ.get("DAILY_LLM_CALL_LIMIT", "200"))


def _today() -> str:
    """当前学习日日期字符串（YYYY-MM-DD，STUDY_TIMEZONE）。

    用 study-day 边界（与刷题学习日一致）而非服务器本地时区，
    避免跨日临界点配额与学习日不同步。独立函数便于测试固定日期。
    """
    from datetime import datetime, timezone
    from app.services.practice_deck_service import _study_timezone
    return datetime.now(timezone.utc).astimezone(_study_timezone()).date().isoformat()


def _increment_usage(conn, user_id: int, day: str, tokens: int = 0, limit: int = DAILY_LLM_CALL_LIMIT) -> bool:
    """Atomically reserve one call, returning False when the limit is reached."""
    if limit <= 0:
        return False

    cursor = conn.execute(
        "INSERT INTO llm_usage (user_id, day, call_count, total_tokens) "
        "VALUES (?, ?, 1, ?) "
        "ON CONFLICT(user_id, day) DO UPDATE SET "
        "call_count = call_count + 1, "
        "total_tokens = total_tokens + excluded.total_tokens "
        "WHERE call_count < ?",
        (user_id, day, tokens, limit),
    )
    conn.commit()
    allowed = cursor.rowcount == 1
    if not allowed:
        logger.warning(
            "per-user daily LLM quota exceeded: user_id=%s day=%s limit=%s",
            user_id,
            day,
            limit,
        )
    return allowed


async def check_and_record(
    user_id: int, tokens: int = 0, limit: int | None = None
) -> bool:
    """查询今日用量并计入本次调用。

    - 今日调用次数已 ≥ 上限 → 返回 False（本次调用被拒绝，不计入）。
    - 否则把本次调用计数 +1（可选累加 tokens）并返回 True。

    limit 为空时使用 DAILY_LLM_CALL_LIMIT（默认 200 次/日）。
    """
    effective_limit = limit if limit is not None else DAILY_LLM_CALL_LIMIT
    day = _today()

    def _run():
        conn = get_db_connection()
        return _increment_usage(conn, user_id, day, tokens, effective_limit)

    return await run_db(_run)


async def release_quota(user_id: int, day: str | None = None) -> None:
    """释放一次已预留的配额（LLM 调用失败时回滚计数）。

    check_and_record 先 +1 再让调用方发 LLM 请求；若 LLM 失败，
    这条计数已消耗但没有产出。release_quota 有界回退（不降为负），
    避免失败调用消耗用户当日配额。
    """
    day = day or _today()

    def _run():
        conn = get_db_connection()
        conn.execute(
            "UPDATE llm_usage SET call_count = MAX(0, call_count - 1) "
            "WHERE user_id = ? AND day = ? AND call_count > 0",
            (user_id, day),
        )
        conn.commit()
    await run_db(_run)
