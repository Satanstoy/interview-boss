"""用户简历管理服务 — PDF 解析 + CRUD

使用 pdfplumber 提取 PDF 文本，存储到 user_resumes 表。
每个用户仅保留一份最新简历（重复上传覆盖旧的）。
"""
import json
import logging
from io import BytesIO
from typing import Optional
from app.db.connection import get_db_connection

logger = logging.getLogger("interview-boss")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """从 PDF 字节流中提取纯文本

    使用 pdfplumber（基于 pdfminer.six）替代 pypdf：
    pypdf 对 CID 字体的中文简历（WPS/LaTeX 导出）存在已知 bug——
    同一文本对象被重复提取两次、字符间距被误判为空格导致乱码，
    且对多栏布局无感知。pdfplumber 布局感知更强、无重复 bug。

    Args:
        pdf_bytes: PDF 文件的字节内容

    Returns:
        提取的纯文本内容

    Raises:
        ValueError: 如果不是有效的 PDF 文件
    """
    import pdfplumber

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text_parts = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text.strip())
            return "\n\n".join(text_parts)
    except Exception:
        raise ValueError("无效的 PDF 文件，无法解析")


def save_resume(user_id: int, filename: str, raw_text: str) -> int:
    """保存用户简历（覆盖旧简历）

    同时停用 chat_memories 中的旧简历记忆（audit D9 / spec Task A M39）：
    user_resumes 是简历唯一事实源，旧副本不得被面试 agent 继续召回。

    Args:
        user_id: 用户 ID
        filename: 原始文件名
        raw_text: 提取的纯文本

    Returns:
        简历记录 ID
    """
    from app.services.chat_memory_service import deactivate_resume_memories

    with get_db_connection() as conn:
        # 删除旧简历
        conn.execute("DELETE FROM user_resumes WHERE user_id = ?", (user_id,))
        # 插入新简历
        cursor = conn.execute(
            "INSERT INTO user_resumes (user_id, filename, raw_text) VALUES (?, ?, ?)",
            (user_id, filename, raw_text)
        )
        conn.commit()
        resume_id = cursor.lastrowid
    # 同步停用 chat 旧简历记忆；失败不阻断上传（记录日志）
    try:
        deactivate_resume_memories(user_id)
    except Exception:
        logger.exception("停用旧简历记忆失败")
    return resume_id


def get_resume(user_id: int) -> Optional[dict]:
    """获取用户的简历

    Args:
        user_id: 用户 ID

    Returns:
        简历字典 {id, filename, raw_text, created_at} 或 None
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, filename, raw_text, created_at FROM user_resumes WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "filename": row[1],
        "raw_text": row[2],
        "created_at": row[3],
    }


def get_resume_text(user_id: int) -> Optional[str]:
    """获取用户简历的纯文本（轻量级，仅返回文本）

    Returns:
        简历文本或 None
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT raw_text FROM user_resumes WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    return row[0] if row else None


def delete_resume(user_id: int) -> bool:
    """删除用户的简历

    同时停用 chat_memories 中的简历记忆，避免已删除简历的 PII 被
    面试 agent 继续召回（audit D9 / spec Task A M39）。

    Returns:
        是否成功删除
    """
    from app.services.chat_memory_service import deactivate_resume_memories

    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM user_resumes WHERE user_id = ?", (user_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    try:
        deactivate_resume_memories(user_id)
    except Exception:
        logger.exception("删除简历时停用记忆失败")
    return deleted


def has_resume(user_id: int) -> bool:
    """检查用户是否有简历

    Returns:
        True 如果用户有简历
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_resumes WHERE user_id = ? LIMIT 1",
            (user_id,)
        ).fetchone()

    return row is not None


def save_optimization(
    user_id: int,
    position: str,
    points: list[str],
    optimized_text: str,
) -> bool:
    """保存简历优化结果（覆盖旧结果）

    Args:
        user_id: 用户 ID
        position: 优化时使用的目标岗位
        points: 优化要点列表
        optimized_text: 优化版简历全文

    Returns:
        True 表示保存成功
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE user_resumes
            SET optimized_text = ?,
                optimization_points = ?,
                optimized_position = ?,
                optimized_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (
                optimized_text,
                json.dumps(points, ensure_ascii=False),
                position,
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_optimization(user_id: int) -> Optional[dict]:
    """获取用户最新的简历优化结果

    Returns:
        {position, points, optimized_text, optimized_at} 或 None
    """
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT optimized_text, optimization_points, optimized_position, optimized_at
            FROM user_resumes WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    if not row or row[0] is None:
        return None

    try:
        points = json.loads(row[1]) if row[1] else []
    except (json.JSONDecodeError, TypeError):
        points = []

    return {
        "optimized_text": row[0],
        "points": points,
        "position": row[2],
        "optimized_at": row[3],
    }
