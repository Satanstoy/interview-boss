"""邮箱绑定端点"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from app.core.request_ip import get_client_ip
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db
from app.services.email_service import send_verification_code, verify_code

logger = logging.getLogger("interview-boss")

router = APIRouter()
limiter = Limiter(key_func=get_client_ip)


class BindEmailRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        # 与 auth.py 邮箱口径一致：小写 + 去空白（email 唯一索引 BINARY，防大小写变体绕过）
        return v.strip().lower()


class SendBindCodeRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        return v.strip().lower()


def _check_email_taken(email: str, exclude_user_id: int = None) -> bool:
    """检查邮箱是否已被其他用户使用"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return False
        if exclude_user_id and row['id'] == exclude_user_id:
            return False
        return True


def _update_user_email(user_id: int, email: str):
    """更新用户的邮箱"""
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (email, user_id))
        conn.commit()


@router.post("/api/profile/bind-email")
async def bind_email(req: BindEmailRequest, user: dict = Depends(get_current_user)):
    """绑定/更换邮箱"""
    valid = await verify_code(req.email, req.code, "bind")
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    if _check_email_taken(req.email, exclude_user_id=user['id']):
        raise HTTPException(status_code=409, detail="该邮箱已被其他用户绑定")

    _update_user_email(user['id'], req.email)
    return {"success": True, "message": "邮箱绑定成功", "email": req.email}


@router.get("/api/profile/email")
async def get_email(user: dict = Depends(get_current_user)):
    """获取当前绑定的邮箱"""
    def _query():
        with get_db_connection() as conn:
            row = conn.execute("SELECT email FROM users WHERE id = ?", (user['id'],)).fetchone()
            return row['email'] if row else None

    email = await run_db(_query)
    return {"email": email}


@router.post("/api/profile/send-bind-code")
@limiter.limit("3/minute")
async def send_bind_code(request: Request, req: SendBindCodeRequest, user: dict = Depends(get_current_user)):
    """发送绑定邮箱的验证码"""
    result = await send_verification_code(req.email, "bind")
    if not result["success"]:
        status = 503 if "未配置" in result["message"] else 429
        raise HTTPException(status_code=status, detail=result["message"])
    return result
