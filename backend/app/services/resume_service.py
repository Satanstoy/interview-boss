"""用户简历管理服务 — PDF 解析 + CRUD

使用 pdfplumber 提取 PDF 文本，存储到 user_resumes 表。
每个用户仅保留一份最新简历（重复上传覆盖旧的）。
"""
import json
import logging
from io import BytesIO
from typing import Optional
from app.db.connection import get_db_connection, run_db
from app.services.llm import raw_llm_call, stream_llm_messages, _extract_json
from app.core.prompts import (
    build_resume_optimize_points_prompt,
    build_resume_optimize_text_prompt,
)

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
    except Exception as e:
        # audit D14 / spec Task G6 M45：记录 pdfplumber 根因，避免把真实解析错误
        # 掩盖成通用「无效 PDF」而无从排查
        logger.warning("PDF 解析失败: %s", e)
        raise ValueError("无效的 PDF 文件，无法解析") from e


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
        # 插入新简历（显式维护 updated_at，消除死列歧义，audit D9 / spec Task G8 M45）
        cursor = conn.execute(
            "INSERT INTO user_resumes (user_id, filename, raw_text, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
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


def get_resume_meta(user_id: int) -> Optional[dict]:
    """获取简历元数据（轻量级，不 SELECT raw_text，避免每次加载大文本）

    audit D10 / spec Task G2 M45：元数据端点只展示 id/filename/created_at，
    全量 raw_text（≤50KB）不应被拉进内存再丢弃。

    Returns:
        {id, filename, created_at} 或 None
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, filename, created_at FROM user_resumes WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "filename": row[1],
        "created_at": row[2],
    }


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
                optimized_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
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

async def optimize_resume_event_stream(user_id: int, position: str):
    """简历优化 SSE 事件流：points → delta* → done/error

    audit D1 / spec Task D M42：LLM 编排从 router 移入 service，router 只做
    HTTP 感知。签名使用 user_id（而非 user dict），service 可独立测试。
    """
    try:
        raw_text = await run_db(lambda: get_resume_text(user_id))
        if not raw_text:
            yield f"data: {json.dumps({'type': 'error', 'message': '未找到简历，请先上传'})}\n\n"
            return

        # 第一阶段：非流式生成要点 JSON
        try:
            points_raw = await raw_llm_call(
                user_id,
                messages=[{
                    "role": "user",
                    "content": build_resume_optimize_points_prompt(raw_text, position),
                }],
                temperature=0.3,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            points_data = _extract_json(points_raw)
            points = points_data if isinstance(points_data, list) else points_data.get("points", [])
            if not isinstance(points, list):
                points = []
            # audit D14 / spec Task G3 M45：强制 str，避免数字/dict 渲染成 [object Object]
            points = [str(p) for p in points if p is not None]
        except Exception as e:
            logger.warning(f"简历优化要点生成失败，跳过要点: {e}")
            points = []

        yield f"data: {json.dumps({'type': 'points', 'points': points}, ensure_ascii=False)}\n\n"

        # 第二阶段：流式生成优化版全文
        text_chunks = []
        async for chunk in stream_llm_messages(
            messages=[{
                "role": "user",
                "content": build_resume_optimize_text_prompt(raw_text, position),
            }],
            user_id=user_id,
            temperature=0.4,
            # audit D14 / spec Task C M41：显式下发 max_tokens 防服务端默认值截断
            max_tokens=4096,
        ):
            text_chunks.append(chunk)
            yield f"data: {json.dumps({'type': 'delta', 'content': chunk}, ensure_ascii=False)}\n\n"

        optimized_text = "".join(text_chunks)
        if not optimized_text.strip():
            raise RuntimeError("模型未生成优化内容")

        saved = await run_db(lambda: save_optimization(
            user_id, position, points, optimized_text
        ))
        if not saved:
            # audit D14 / spec Task G5 M45：流式中删除了简历则不得谎报「已保存」
            yield f"data: {json.dumps({'type': 'error', 'message': '未找到简历，可能已删除'}, ensure_ascii=False)}\n\n"
            return

        yield f"data: {json.dumps({'type': 'done', 'position': position}, ensure_ascii=False)}\n\n"
    except Exception:
        logger.exception("简历优化失败")
        yield f"data: {json.dumps({'type': 'error', 'message': '优化失败，请稍后重试'}, ensure_ascii=False)}\n\n"