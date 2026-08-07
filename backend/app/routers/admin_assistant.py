"""管理员 AI 助手 API（仅管理员）：对话 / 确认执行 / 会话历史。

HTTP 感知薄层；业务逻辑在 `app.services.admin_assistant_service`。
所有端点 `Depends(get_admin_user)`——后端鉴权是安全边界。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import get_admin_user
from app.services.admin_assistant_service import (
    confirm_and_execute,
    get_assistant_history,
    run_assistant_turn,
)

router = APIRouter(prefix="/api/admin/assistant", tags=["admin-assistant"])


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = ""  # "" => 确认后续接（无新用户消息，仅回执）


class ConfirmRequest(BaseModel):
    session_id: str
    confirm_id: str
    tool: str
    arguments: dict


@router.post("/chat")
async def chat(body: ChatRequest, admin: dict = Depends(get_admin_user)):
    """发送一条消息给 AI 助手（写操作只暂存为待确认，不执行）。"""
    return await run_assistant_turn(admin, body.session_id, body.message)


@router.post("/confirm")
async def confirm(body: ConfirmRequest, admin: dict = Depends(get_admin_user)):
    """确认并执行 AI 助手暂存的写操作（重新校验 + reviewed_by 留痕）。"""
    return await confirm_and_execute(
        admin, body.session_id, body.confirm_id, body.tool, body.arguments
    )


@router.get("/history")
async def history(session_id: str, admin: dict = Depends(get_admin_user)):
    """读取当前管理员的助手会话日志。"""
    return await get_assistant_history(admin, session_id)
