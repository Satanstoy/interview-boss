"""用户简历管理服务 — PDF 解析 + CRUD

使用 pypdf 提取 PDF 文本，存储到 user_resumes 表。
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

    Args:
        pdf_bytes: PDF 文件的字节内容

    Returns:
        提取的纯文本内容

    Raises:
        ValueError: 如果不是有效的 PDF 文件
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception:
        raise ValueError("无效的 PDF 文件，无法解析")

    text_parts = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text.strip())

    return "\n\n".join(text_parts)


def save_resume(user_id: int, filename: str, raw_text: str) -> int:
    """保存用户简历（覆盖旧简历）

    Args:
        user_id: 用户 ID
        filename: 原始文件名
        raw_text: 提取的纯文本

    Returns:
        简历记录 ID
    """
    with get_db_connection() as conn:
        # 删除旧简历
        conn.execute("DELETE FROM user_resumes WHERE user_id = ?", (user_id,))
        # 插入新简历
        cursor = conn.execute(
            "INSERT INTO user_resumes (user_id, filename, raw_text) VALUES (?, ?, ?)",
            (user_id, filename, raw_text)
        )
        conn.commit()
        return cursor.lastrowid


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

    Returns:
        是否成功删除
    """
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM user_resumes WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


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
    points: list,
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
        conn.execute(
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
        return conn.total_changes > 0


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
