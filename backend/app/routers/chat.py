"""对话 API — 会话管理 + 消息流式输出"""

import json
import logging
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from app.core.auth import get_current_user
from app.db.connection import run_db, get_user_job_position
from app.models.schemas import CreateConversationRequest
from app.services import chat_service, resume_service
from app.services.llm_quota import check_and_record

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/chat")

# PDF 提取上传大小上限（字节），在 file.read() 之前用 Content-Length 提前拦截
_MAX_PDF_UPLOAD_BYTES = 10 * 1024 * 1024


def _current_position_name(user_id: int) -> str:
    _, position = get_user_job_position(user_id)
    return position


# ── 请求模型 ──


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    model: Optional[str] = None
    client_request_id: Optional[str] = Field(None, min_length=1, max_length=128)
    existing_user_message_id: Optional[int] = Field(None, gt=0)
    regenerate_message_id: Optional[int] = Field(None, gt=0)


class RegenerateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Optional[str] = None
    client_request_id: Optional[str] = Field(None, min_length=1, max_length=128)


class CancelTurnRequest(BaseModel):
    reason: str = Field(default="client_stop", min_length=1, max_length=120)


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
                job_position=_current_position_name(user["id"]),
                difficulty=req.difficulty or "mid",
                experience_id=req.experience_id,
                distribution_override=req.distribution_override.model_dump()
                if req.distribution_override
                else None,
                first_message=req.first_message,
                client_request_id=req.client_request_id,
            )
        )

        # 如果上传了简历，保存到长期记忆
        if resume_text and resume_text != "__saved__":
            await run_db(
                lambda: chat_service.save_resume_memory(user["id"], resume_text)
            )

        # 只有没有 first_message 时才生成开场白
        if not req.first_message:
            opening = chat_service.generate_opening_message(req.mode)
            await run_db(
                lambda: chat_service.save_message(result["id"], "assistant", opening)
            )
            result["opening_message"] = opening
        else:
            result["opening_message"] = None

        return {"status": "success", "data": result}
    except ValueError as e:
        logger.warning(f"创建对话参数无效: {e}")
        raise HTTPException(status_code=404, detail=str(e))
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
            lambda: chat_service.get_conversations(
                user["id"], status, _current_position_name(user["id"])
            )
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
        lambda: chat_service.get_conversation(
            conversation_id, user["id"], _current_position_name(user["id"])
        )
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
        lambda: chat_service.get_conversation(
            conversation_id, user["id"], _current_position_name(user["id"])
        )
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
        lambda: chat_service.archive_conversation(
            conversation_id, user["id"], _current_position_name(user["id"])
        )
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
        lambda: chat_service.delete_conversation(
            conversation_id, user["id"], _current_position_name(user["id"])
        )
    )
    if not success:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"status": "success"}


# ── 消息 ──


def _metadata_events_from_done(meta: dict) -> list[dict]:
    """Split run_chat done metadata into public SSE events."""
    events: list[dict] = []
    if meta.get("candidate_questions"):
        events.append(
            {"type": "candidates", "questions": meta.get("candidate_questions", [])}
        )
    if "selected_question" in meta:
        events.append(
            {
                "type": "selected_question",
                "question": meta.get("selected_question"),
                "source": meta.get("question_source", ""),
                "reason": meta.get("question_source_reason", ""),
            }
        )
    question_plan = meta.get("question_plan")
    if isinstance(question_plan, dict):
        events.append(
            {
                "type": "question_plan",
                "question_id": question_plan.get("question_id"),
                "source": question_plan.get("source", ""),
                "selection_reason": question_plan.get("selection_reason", ""),
                "adherence": question_plan.get("adherence", {}),
                "repaired": bool(question_plan.get("repaired", False)),
                "fallback_used": bool(question_plan.get("fallback_used", False)),
            }
        )

    basis_type = meta.get("basis_type")
    if basis_type:
        events.append(
            {
                "type": "basis",
                "basis_type": basis_type,
                "basis_question_ids": meta.get("basis_question_ids", []),
                "basis_confidence": meta.get("basis_confidence", 0.0),
                "should_show_references": meta.get("should_show_references", False),
                "selected_basis_questions": meta.get("selected_basis_questions", []),
                "resume_ref": meta.get("resume_ref", ""),
                "jd_ref": meta.get("jd_ref", ""),
            }
        )
    if meta.get("resume_ref"):
        events.append({"type": "resume_ref", "name": meta["resume_ref"]})
    if meta.get("jd_ref"):
        events.append({"type": "jd_ref", "title": meta["jd_ref"]})
    return events


async def _replay_completed_turn(turn: dict):
    """Replay a committed assistant result without invoking the pipeline again."""
    yield f"data: {json.dumps({'type': 'turn_started', 'turn_id': turn['id'], 'fence': turn['fence'], 'client_request_id': turn['client_request_id'], 'replay': True}, ensure_ascii=False)}\n\n"
    if turn.get("assistant_content"):
        yield f"data: {json.dumps({'type': 'chunk', 'content': turn['assistant_content'], 'replace': True}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'done', 'metadata': turn.get('assistant_metadata') or {}, 'replay': True}, ensure_ascii=False)}\n\n"


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, user: dict = Depends(get_current_user)):
    """获取对话的消息历史"""
    conv = await run_db(
        lambda: chat_service.get_conversation(
            conversation_id, user["id"], _current_position_name(user["id"])
        )
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = await run_db(lambda: chat_service.get_messages(conversation_id))
    return {"status": "success", "data": messages}


@router.post("/conversations/{conversation_id}/turns/{turn_id}/cancel")
async def cancel_turn(
    conversation_id: str,
    turn_id: str,
    req: CancelTurnRequest = CancelTurnRequest(),
    user: dict = Depends(get_current_user),
):
    """Immediately invalidate a running turn; repeated cancellation is safe."""
    try:
        turn = await run_db(
            lambda: chat_service.cancel_chat_turn(
                turn_id,
                conversation_id,
                user["id"],
                req.reason,
            )
        )
    except chat_service.TurnNotFound:
        raise HTTPException(status_code=404, detail="TURN_NOT_FOUND")

    return {
        "status": "success",
        "data": {
            "turn_id": turn.id,
            "fence": turn.fence,
            "status": turn.status,
        },
    }


@router.get("/conversations/{conversation_id}/turns/{turn_id}")
async def get_turn_status(
    conversation_id: str,
    turn_id: str,
    user: dict = Depends(get_current_user),
):
    """Return an owned turn snapshot for SSE retry reconciliation."""
    turn = await run_db(
        lambda: chat_service.get_chat_turn(
            turn_id,
            conversation_id=conversation_id,
            user_id=user["id"],
        )
    )
    if not turn:
        raise HTTPException(status_code=404, detail="TURN_NOT_FOUND")
    return {"status": "success", "data": turn}


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    req: SendMessageRequest,
    user: dict = Depends(get_current_user),
):
    """发送消息并获取 AI 流式回复（SSE）"""
    conv = await run_db(
        lambda: chat_service.get_conversation(
            conversation_id, user["id"], _current_position_name(user["id"])
        )
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if (conv.get("metadata") or {}).get("sealed"):
        raise HTTPException(status_code=409, detail="IMPORTED_RECORD_SEALED")

    # per-user 每日 LLM 配额：超限直接拒绝，避免预留回合后无法真正调用 LLM
    if not await check_and_record(user["id"]):
        raise HTTPException(status_code=429, detail="今日 AI 调用次数已达上限")

    client_request_id = req.client_request_id or str(uuid.uuid4())
    turn_content = req.content

    # 回合占用和用户消息必须在同一个事务内完成，避免并发请求先后通过检查。
    try:
        if req.regenerate_message_id:
            turn, turn_content = await run_db(
                lambda: chat_service.reserve_chat_revision(
                    conversation_id,
                    user["id"],
                    req.regenerate_message_id,
                    client_request_id,
                    model=req.model,
                )
            )
        else:
            request_fingerprint = chat_service.build_turn_request_fingerprint(
                req.content,
                model=req.model,
            )
            turn = await run_db(
                lambda: chat_service.reserve_chat_turn(
                    conversation_id,
                    user["id"],
                    client_request_id,
                    req.content,
                    request_fingerprint,
                    existing_user_message_id=req.existing_user_message_id,
                )
            )
    except chat_service.ConversationNotWritable:
        raise HTTPException(status_code=409, detail="CONVERSATION_NOT_WRITABLE")
    except chat_service.TurnInProgress:
        raise HTTPException(status_code=409, detail="TURN_IN_PROGRESS")
    except chat_service.TurnIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TURN_IDEMPOTENCY_CONFLICT",
                "turn_id": exc.turn_id,
                "status": exc.status,
            },
        )
    except chat_service.ConversationNotFound:
        raise HTTPException(status_code=404, detail="对话不存在")
    except chat_service.TurnNotFound:
        raise HTTPException(status_code=404, detail="消息不可重新生成")
    except chat_service.TurnUserMessageConflict:
        raise HTTPException(status_code=409, detail="TURN_USER_MESSAGE_CONFLICT")

    if not turn.created:
        if turn.status == "completed":
            snapshot = await run_db(
                lambda: chat_service.get_chat_turn(
                    turn.id,
                    conversation_id=conversation_id,
                    user_id=user["id"],
                )
            )
            if snapshot:
                return StreamingResponse(
                    _replay_completed_turn(snapshot),
                    media_type="text/event-stream",
                )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TURN_REQUEST_ALREADY_EXISTS",
                "turn_id": turn.id,
                "status": turn.status,
            },
        )

    # 自动生成标题（第一条消息时，用 LLM 提取主题）
    from app.services.title_service import generate_title, should_generate_title

    if not req.regenerate_message_id and should_generate_title(conv.get("title", "")):
        try:
            title = await generate_title(turn_content, user_id=user["id"])
            await run_db(
                lambda: chat_service.update_conversation_title(conversation_id, title)
            )
        except Exception:
            await run_db(
                lambda: chat_service.fail_chat_turn(
                    turn.id,
                    turn.fence,
                    conversation_id,
                    user["id"],
                    "TITLE_GENERATION_FAILED",
                )
            )
            raise

    async def event_stream():
        """SSE 流式输出 AI 回复"""
        full_response = ""
        try:
            yield f"data: {json.dumps({'type': 'turn_started', 'turn_id': turn.id, 'fence': turn.fence, 'client_request_id': turn.client_request_id}, ensure_ascii=False)}\n\n"

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
                user_message=turn_content,
                mode=conv.get("mode", "free_practice"),
                jd_id=conv.get("jd_id"),
                resume_text=conv.get("resume_text"),
                jd_text=jd_text,
                model=req.model,
                bank_mode="all",
                turn_id=turn.id,
                turn_fence=turn.fence,
            ):
                event_type = event.get("type", "chunk")

                if event_type == "step":
                    step_data: dict = {
                        "type": "step",
                        "step": event.get("step", ""),
                        "message": event.get("message", ""),
                    }
                    if event.get("reason"):
                        step_data["reason"] = event["reason"]
                    if event.get("insight"):
                        step_data["insight"] = event["insight"]
                    if event.get("skill_name"):
                        step_data["skill_name"] = event["skill_name"]
                    yield f"data: {json.dumps(step_data, ensure_ascii=False)}\n\n"

                elif event_type == "tool_step":
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                elif event_type == "chunk":
                    content = event.get("content", "")
                    full_response += content
                    payload = {"type": "chunk", "content": content}
                    if event.get("replace"):
                        full_response = content
                        payload["replace"] = True
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

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

                    try:
                        await run_db(
                            lambda: chat_service.finalize_chat_turn(
                                turn.id,
                                turn.fence,
                                conversation_id,
                                user["id"],
                                clean_for_persist or full_response,
                                {
                                    **meta,
                                    "turn_id": turn.id,
                                    "turn_fence": turn.fence,
                                    "request_fingerprint": turn.request_fingerprint,
                                },
                            )
                        )
                    except chat_service.TurnCancelled:
                        yield f"data: {json.dumps({'type': 'cancelled', 'turn_id': turn.id}, ensure_ascii=False)}\n\n"
                        return

                    for metadata_event in _metadata_events_from_done(meta):
                        yield f"data: {json.dumps(metadata_event, ensure_ascii=False)}\n\n"

                    # 附带 reasoning metadata 给前端，用于思维链/步骤/工具/skill 显示
                    done_payload: dict = {"type": "done"}
                    for key in (
                        "turn_intent",
                        "turn_contract",
                        "writer_trace",
                        "validator_trace",
                        "tool_contract_trace",
                        "generation_error_code",
                        "reasoning_trace",
                        "tool_calls_trace",
                        "skill_trace",
                        "steps",
                        "tool_steps",
                        "thinking",
                        "thinking_duration",
                        "insights",
                    ):
                        val = meta.get(key)
                        if val:
                            done_payload[key] = val
                    yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

                elif event_type == "error":
                    await run_db(
                        lambda: chat_service.fail_chat_turn(
                            turn.id,
                            turn.fence,
                            conversation_id,
                            user["id"],
                            event.get("code") or "PIPELINE_ERROR",
                        )
                    )
                    error_payload = {
                        "type": "error",
                        "message": event.get("message", "未知错误"),
                    }
                    if event.get("code"):
                        error_payload["code"] = event["code"]
                    yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

                elif event_type == "cancelled":
                    yield f"data: {json.dumps({'type': 'cancelled', 'turn_id': turn.id}, ensure_ascii=False)}\n\n"
                    return

        except chat_service.ConversationNotWritable:
            logger.info(
                "Conversation archived before assistant finalize: %s",
                conversation_id,
            )
            yield f"data: {json.dumps({'type': 'error', 'code': 'CONVERSATION_NOT_WRITABLE', 'message': '会话已归档，未保存新的面试官回复。'}, ensure_ascii=False)}\n\n"
        except chat_service.TurnCancelled:
            yield f"data: {json.dumps({'type': 'cancelled', 'turn_id': turn.id}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"Chat 流式输出异常: {e}", exc_info=True)
            try:
                await run_db(
                    lambda: chat_service.fail_chat_turn(
                        turn.id,
                        turn.fence,
                        conversation_id,
                        user["id"],
                        "STREAM_ERROR",
                    )
                )
            except (chat_service.TurnCancelled, chat_service.TurnNotFound):
                pass
            error_msg = "抱歉，处理您的消息时出现错误，请稍后重试。"
            yield f"data: {json.dumps({'type': 'error', 'message': error_msg}, ensure_ascii=False)}\n\n"
        finally:
            try:
                await run_db(
                    lambda: chat_service.cancel_chat_turn(
                        turn.id,
                        conversation_id,
                        user["id"],
                        "stream_closed",
                    )
                )
            except (chat_service.TurnCancelled, chat_service.TurnNotFound):
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.post(
    "/conversations/{conversation_id}/messages/{assistant_message_id}/regenerate"
)
async def regenerate_message(
    conversation_id: str,
    assistant_message_id: int,
    req: RegenerateMessageRequest,
    user: dict = Depends(get_current_user),
):
    """Generate a new assistant revision without appending a user turn."""
    return await send_message(
        conversation_id,
        SendMessageRequest(
            content="regenerate",
            model=req.model,
            client_request_id=req.client_request_id,
            regenerate_message_id=assistant_message_id,
        ),
        user,
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

    # 用 Content-Length 提前拦截超大文件，避免全量读入内存放大
    if file.size and file.size > _MAX_PDF_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，请上传 10MB 以内的 PDF")

    try:
        content = await file.read()
        full_text = resume_service.extract_pdf_text(content)

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
