"""面试对话上下文构建器 — 从系统各模块收集用户画像和题库信息

参考 Claude Code / OpenClaw / Hermes 的上下文注入模式：
- 用户目标岗位 + 描述
- 岗位分类体系（题目类别）
- 用户练习统计（弱点/强项/最近练习的题目）
- 跨对话历史面试经验（Hermes: session_search）
"""
import logging
from typing import Optional
from app.db.queries import get_user_job_position, get_taxonomy_for_position
from app.db.connection import get_db_connection

logger = logging.getLogger("interview-boss")


def build_interview_context(user_id: int, conversation_id: Optional[str] = None) -> tuple[str, str]:
    """构建面试上下文字符串，注入到系统 prompt 中

    Returns:
        (context_text, position_name) — 上下文文本和岗位名
    """
    parts = []

    # 1. 目标岗位
    position_id, position_name = get_user_job_position(user_id)
    parts.append(f"【求职背景】\n目标岗位: {position_name}")

    # 2. 岗位分类体系（题目类别）
    taxonomy = get_taxonomy_for_position(position_name, user_id)
    if taxonomy and taxonomy.get("categories"):
        cats = taxonomy["categories"]
        cat_lines = []
        for cat in cats[:8]:  # 最多 8 个大类
            cat1 = cat.get("name", "")
            children = cat.get("children", [])
            if children:
                child_names = ", ".join(
                    c if isinstance(c, str) else c.get("name", "")
                    for c in children[:5]
                )
                cat_lines.append(f"- {cat1}: {child_names}")
            else:
                cat_lines.append(f"- {cat1}")
        if cat_lines:
            parts.append("【考察类别】\n" + "\n".join(cat_lines))

    # 3. 用户练习统计
    stats = _get_user_practice_summary(user_id)
    if stats:
        parts.append(f"【练习情况】\n{stats}")

    # 4. 跨对话历史面试经验（Hermes: session_search）
    try:
        from app.services.chat_service import search_past_sessions, format_session_recall
        # 用岗位名和已有分类作为搜索关键词
        search_keywords = [position_name]
        past_sessions = search_past_sessions(
            user_id,
            search_keywords,
            limit=2,
            exclude_conv_id=conversation_id,
            job_position=position_name,
        )
        recall_text = format_session_recall(past_sessions)
        if recall_text:
            parts.append(recall_text)
    except Exception as e:
        logger.debug(f"历史会话搜索跳过: {e}")

    return "\n\n".join(parts), position_name


def _get_user_practice_summary(user_id: int) -> str:
    """获取用户练习统计摘要（轻量级查询）"""
    try:
        with get_db_connection() as conn:
            # 总练习数和平均分
            row = conn.execute(
                "SELECT COUNT(*) as total, AVG(score) as avg_score "
                "FROM practice_review_events WHERE user_id = ? AND source = 'self_check'",
                (user_id,)
            ).fetchone()
            total = row[0] if row else 0
            avg_score = round(row[1], 1) if row and row[1] else 0

            if total == 0:
                return "尚未开始练习"

            # 按类别统计正确率（通过 question_bank 的 cat1）
            cat_stats = conn.execute(
                "SELECT qb.cat1, COUNT(*) as cnt, AVG(oph.score) as avg_s "
                "FROM practice_review_events oph "
                "JOIN question_bank qb ON oph.question_bank_id = qb.id "
                "WHERE oph.user_id = ? AND oph.source = 'self_check' AND qb.cat1 IS NOT NULL AND qb.cat1 != '' "
                "GROUP BY qb.cat1 ORDER BY avg_s ASC LIMIT 5",
                (user_id,)
            ).fetchall()

            lines = [f"已练习 {total} 题，平均分 {avg_score} 分"]

            # 薄弱环节（正确率最低的类别）
            weak_cats = [r for r in cat_stats if r[2] and r[2] < 70]
            if weak_cats:
                weak_lines = [f"- {r[0]}（平均 {round(r[1])} 分）" for r in weak_cats[:3]]
                lines.append("薄弱环节:\n" + "\n".join(weak_lines))

            # 最近练习的 3 题（读 review 体系；user_practice_history 已停写）
            recent = conn.execute(
                "SELECT qb.question, pr.score FROM practice_review_events pr "
                "JOIN question_bank qb ON pr.question_bank_id = qb.id "
                "WHERE pr.user_id = ? AND pr.source = 'self_check' AND pr.score IS NOT NULL "
                "ORDER BY pr.reviewed_at DESC LIMIT 3",
                (user_id,)
            ).fetchall()
            if recent:
                recent_lines = [f"- {r[0][:40]}...（{r[1]}分）" for r in recent]
                lines.append("最近练习:\n" + "\n".join(recent_lines))

            return "\n".join(lines)
    except Exception as e:
        logger.debug(f"获取练习统计失败: {e}")
        return ""


def get_position_question_stats(position_name: str) -> str:
    """获取岗位题目分布统计（用于告诉 AI 当前题库覆盖情况）"""
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT cat1, COUNT(*) as cnt FROM question_bank "
                "WHERE deleted_at IS NULL AND status = 'approved' "
                "AND job_position = ? "
                "GROUP BY cat1 ORDER BY cnt DESC LIMIT 10",
                (position_name,)
            ).fetchall()

            if not rows:
                return ""

            lines = [f"题库共 {sum(r[1] for r in rows)} 题:"]
            for r in rows:
                lines.append(f"- {r[0] or '未分类'}: {r[1]} 题")
            return "\n".join(lines)
    except Exception as e:
        logger.debug(f"获取题目分布失败: {e}")
        return ""
