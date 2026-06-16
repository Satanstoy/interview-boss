"""对话 API — 会话管理 + 消息流式输出"""

import io
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from app.core.auth import get_current_user
from app.db.connection import run_db
from app.services import chat_service

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/chat")


# ── 请求模型 ──


class CreateConversationRequest(BaseModel):
    mode: str = Field(..., pattern="^(jd_resume|free_practice)$")
    title: Optional[str] = None
    jd_id: Optional[int] = None
    resume_text: Optional[str] = None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    model: Optional[str] = None


# ── 会话管理 ──


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest, user: dict = Depends(get_current_user)
):
    """创建新对话会话"""
    try:
        # 处理 "__saved__" 标记：从数据库加载已保存的简历
        resume_text = req.resume_text
        if resume_text == "__saved__":
            from app.services import resume_service

            saved = await run_db(lambda: resume_service.get_resume_text(user["id"]))
            resume_text = saved if saved else None

        result = await run_db(
            lambda: chat_service.create_conversation(
                user_id=user["id"],
                mode=req.mode,
                title=req.title,
                jd_id=req.jd_id,
                resume_text=resume_text,
            )
        )

        # 如果上传了简历，保存到长期记忆
        if resume_text and resume_text != "__saved__":
            await run_db(
                lambda: chat_service.save_resume_memory(user["id"], resume_text)
            )

        # 自动生成面试官开场白
        opening = chat_service.generate_opening_message(req.mode)
        await run_db(
            lambda: chat_service.save_message(result["id"], "assistant", opening)
        )
        result["opening_message"] = opening

        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"创建对话失败: {e}")
        raise HTTPException(status_code=500, detail="创建对话失败")


@router.get("/conversations")
async def list_conversations(
    status: str = "active",
    user: dict = Depends(get_current_user),
):
    """获取用户的对话列表"""
    try:
        conversations = await run_db(
            lambda: chat_service.get_conversations(user["id"], status)
        )
        return {"status": "success", "data": conversations}
    except Exception as e:
        logger.error(f"获取对话列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取对话列表失败")


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str, user: dict = Depends(get_current_user)
):
    """获取对话详情"""
    conv = await run_db(
        lambda: chat_service.get_conversation(conversation_id, user["id"])
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"status": "success", "data": conv}


@router.put("/conversations/{conversation_id}/title")
async def update_title(
    conversation_id: str, body: dict, user: dict = Depends(get_current_user)
):
    """更新对话标题"""
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    conv = await run_db(
        lambda: chat_service.get_conversation(conversation_id, user["id"])
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    await run_db(lambda: chat_service.update_conversation_title(conversation_id, title))
    return {"status": "success"}


@router.put("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str, user: dict = Depends(get_current_user)
):
    """归档对话"""
    success = await run_db(
        lambda: chat_service.archive_conversation(conversation_id, user["id"])
    )
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"status": "success"}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str, user: dict = Depends(get_current_user)
):
    """删除对话"""
    success = await run_db(
        lambda: chat_service.delete_conversation(conversation_id, user["id"])
    )
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"status": "success"}


# ── 消息 ──


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, user: dict = Depends(get_current_user)):
    """获取对话的消息历史"""
    conv = await run_db(
        lambda: chat_service.get_conversation(conversation_id, user["id"])
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = await run_db(lambda: chat_service.get_messages(conversation_id))
    return {"status": "success", "data": messages}


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    req: SendMessageRequest,
    user: dict = Depends(get_current_user),
):
    """发送消息并获取 AI 流式回复（SSE）"""
    conv = await run_db(
        lambda: chat_service.get_conversation(conversation_id, user["id"])
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    # 保存用户消息
    user_msg_id = await run_db(
        lambda: chat_service.save_message(conversation_id, "user", req.content)
    )

    # 自动生成标题（第一条消息时，用 LLM 提取主题）
    from app.services.title_service import generate_title, should_generate_title

    if should_generate_title(conv.get("title", "")):
        title = await generate_title(req.content, user_id=user["id"])
        await run_db(
            lambda: chat_service.update_conversation_title(conversation_id, title)
        )

    async def event_stream():
        """SSE 流式输出 AI 回复"""
        full_response = ""
        try:
            # 导入 chat agent
            from app.agents.chat.graph import run_chat

            # 加载 JD 文本（如果关联了 JD）
            jd_text = None
            if conv.get("jd_id"):
                from app.db.connection import get_db_connection

                with get_db_connection() as conn:
                    jd_row = conn.execute(
                        "SELECT content FROM jd WHERE id = ?", (conv["jd_id"],)
                    ).fetchone()
                    if jd_row:
                        jd_text = jd_row[0]

            async for event in run_chat(
                conversation_id=conversation_id,
                user_id=user["id"],
                user_message=req.content,
                mode=conv.get("mode", "free_practice"),
                jd_id=conv.get("jd_id"),
                resume_text=conv.get("resume_text"),
                jd_text=jd_text,
                model=req.model,
                bank_mode=user.get("bank_mode", "public"),
            ):
                event_type = event.get("type", "chunk")

                if event_type == "step":
                    step_data: dict = {"type": "step", "step": event.get("step", ""), "message": event.get("message", "")}
                    if event.get("reason"):
                        step_data["reason"] = event["reason"]
                    if event.get("insight"):
                        step_data["insight"] = event["insight"]
                    yield f"data: {json.dumps(step_data, ensure_ascii=False)}\n\n"

                elif event_type == "chunk":
                    content = event.get("content", "")
                    full_response += content
                    yield f"data: {json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)}\n\n"

                elif event_type == "thinking_start":
                    yield f"data: {json.dumps({'type': 'thinking_start', 'content': ''}, ensure_ascii=False)}\n\n"

                elif event_type == "thinking":
                    yield f"data: {json.dumps({'type': 'thinking', 'content': event.get('content', '')}, ensure_ascii=False)}\n\n"

                elif event_type == "thinking_done":
                    yield f"data: {json.dumps({'type': 'thinking_done', 'duration': event.get('duration', 0), 'content': event.get('content', '')}, ensure_ascii=False)}\n\n"

                elif event_type == "retrieved":
                    yield f"data: {json.dumps({'type': 'retrieved', 'questions': event.get('questions', [])}, ensure_ascii=False)}\n\n"

                elif event_type == "insight":
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                elif event_type == "done":
                    meta = event.get("metadata", {})

                    if meta.get("candidate_questions"):
                        yield f"data: {json.dumps({'type': 'candidates', 'questions': meta.get('candidate_questions', [])}, ensure_ascii=False)}\n\n"
                    if "selected_question" in meta:
                        yield f"data: {json.dumps({'type': 'selected_question', 'question': meta.get('selected_question'), 'source': meta.get('question_source', ''), 'reason': meta.get('question_source_reason', '')}, ensure_ascii=False)}\n\n"

                    basis_type = meta.get("basis_type")
                    if basis_type:
                        yield f"data: {json.dumps({'type': 'basis', 'basis_type': basis_type, 'basis_question_ids': meta.get('basis_question_ids', []), 'basis_confidence': meta.get('basis_confidence', 0.0), 'should_show_references': meta.get('should_show_references', False), 'selected_basis_questions': meta.get('selected_basis_questions', []), 'resume_ref': meta.get('resume_ref', ''), 'jd_ref': meta.get('jd_ref', '')}, ensure_ascii=False)}\n\n"

                    if meta.get("resume_ref"):
                        yield f"data: {json.dumps({'type': 'resume_ref', 'name': meta['resume_ref']}, ensure_ascii=False)}\n\n"
                    if meta.get("jd_ref"):
                        yield f"data: {json.dumps({'type': 'jd_ref', 'title': meta['jd_ref']}, ensure_ascii=False)}\n\n"

                    if full_response:
                        import re as _re

                        clean_for_persist = _re.sub(
                            r"\[BASIS\].*?\[/BASIS\]",
                            "",
                            full_response,
                            flags=_re.DOTALL,
                        ).strip()
                        clean_for_persist = _re.sub(
                            r"\[BASIS\]\{[^}]*\}", "", clean_for_persist
                        ).strip()
                        clean_for_persist = _re.sub(
                            r'"?\\?\[BASIS\\?\].*?\\?\[/BASIS\\?\]"?',
                            "",
                            clean_for_persist,
                            flags=_re.DOTALL,
                        ).strip()
                        await run_db(
                            lambda: chat_service.save_message(
                                conversation_id,
                                "assistant",
                                clean_for_persist or full_response,
                                metadata=meta,
                            )
                        )
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

                elif event_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': event.get('message', '未知错误')}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"Chat 流式输出异常: {e}", exc_info=True)
            error_msg = "抱歉，处理您的消息时出现错误，请稍后重试。"
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── 记忆管理 ──


@router.get("/memories")
async def get_memories(
    memory_type: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """获取用户记忆"""
    memories = await run_db(lambda: chat_service.get_memories(user["id"], memory_type))
    return {"status": "success", "data": memories}


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, user: dict = Depends(get_current_user)):
    """停用一条记忆"""
    success = await run_db(
        lambda: chat_service.deactivate_memory(memory_id, user["id"])
    )
    if not success:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"status": "success"}


# ── PDF 提取 ──


@router.post("/extract-pdf")
async def extract_pdf(
    file: UploadFile = File(...), user: dict = Depends(get_current_user)
):
    """从上传的 PDF 中提取文本"""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    try:
        content = await file.read()
        reader = __import__("pypdf").PdfReader(io.BytesIO(content))

        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text.strip())

        full_text = "\n\n".join(text_parts)

        if not full_text.strip():
            raise HTTPException(
                status_code=400, detail="无法从 PDF 中提取文本，可能是扫描件"
            )

        # 限制长度
        if len(full_text) > 50000:
            full_text = full_text[:50000] + "\n\n...(文本过长，已截断)"

        return {"status": "success", "text": full_text}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PDF 提取失败: {e}")
        raise HTTPException(status_code=500, detail="PDF 提取失败")
