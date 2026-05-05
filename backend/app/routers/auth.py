import logging
from fastapi import APIRouter, HTTPException, Depends, Response, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.core.auth import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    decode_token, get_current_user, get_refresh_token,
    store_refresh_token, get_refresh_token_jti, delete_refresh_token,
    cleanup_expired_refresh_tokens, REFRESH_TOKEN_EXPIRE_DAYS, REFRESH_TOKEN_REMEMBER_DAYS,
)
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class BankModeRequest(BaseModel):
    bank_mode: str  # 'public' / 'personal' / 'mixed'


def _set_refresh_cookie(response: Response, token: str, remember: bool = False):
    days = REFRESH_TOKEN_REMEMBER_DAYS if remember else REFRESH_TOKEN_EXPIRE_DAYS
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=days * 86400,
        path="/",
    )


def _clear_refresh_cookie(response: Response):
    response.delete_cookie(key="refresh_token", path="/")


def _issue_token_pair(user: dict, response: Response, remember: bool = False) -> dict:
    """签发 access + refresh token，设置 cookie，返回响应体"""
    days = REFRESH_TOKEN_REMEMBER_DAYS if remember else REFRESH_TOKEN_EXPIRE_DAYS
    token_data = {"user_id": user['id'], "username": user['username']}
    access_token = create_access_token(token_data)
    refresh_token, jti = create_refresh_token(token_data, days=days)
    store_refresh_token(user['id'], jti, days=days)
    _set_refresh_cookie(response, refresh_token, remember=remember)
    return {
        "token": access_token,
        "user": {
            "id": user['id'],
            "username": user['username'],
            "is_admin": bool(user.get('is_admin', False)),
            "bank_mode": user.get('bank_mode', 'public') or 'public'
        }
    }


@router.post("/register")
async def register(req: RegisterRequest, response: Response):
    if len(req.username) < 2 or len(req.username) > 32:
        raise HTTPException(status_code=400, detail="用户名长度需在 2-32 之间")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")

    password_hash = hash_password(req.password)

    def _create():
        with get_db_connection() as conn:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (req.username,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="用户名已存在")
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, bank_mode) VALUES (?, ?, 0, 'public')",
                (req.username, password_hash)
            )
            conn.commit()
            return cursor.lastrowid

    try:
        user_id = await run_db(_create)
    except HTTPException:
        raise
    except Exception:
        logger.exception("注册失败")
        raise HTTPException(status_code=500, detail="注册失败")

    return _issue_token_pair({"id": user_id, "username": req.username, "is_admin": False, "bank_mode": "public"}, response, remember=False)


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash, is_admin, bank_mode FROM users WHERE username = ?",
                (req.username,)
            ).fetchone()

    user = await run_db(_query)
    if not user or not verify_password(req.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    cleanup_expired_refresh_tokens()
    return _issue_token_pair(dict(user), response, remember=req.remember_me)


@router.post("/refresh")
async def refresh_token(response: Response, rt: str = Depends(get_refresh_token)):
    """
    用 HttpOnly cookie 中的 refresh token 换取新 token pair。
    不依赖 access token（页面刷新后 access token 已在内存中丢失，但 cookie 仍有效）。
    Refresh token 轮转：旧的立即作废，签发新的。
    """
    payload = decode_token(rt, expected_type="refresh")
    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="无效的 refresh token")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 refresh token")

    record = get_refresh_token_jti(jti)
    if not record or record['user_id'] != user_id:
        raise HTTPException(status_code=401, detail="refresh token 已失效，请重新登录")

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, is_admin, bank_mode FROM users WHERE id = ?", (user_id,)
            ).fetchone()

    user = await run_db(_query)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    delete_refresh_token(jti)
    return _issue_token_pair(dict(user), response)


@router.post("/logout")
async def logout(response: Response, rt: str = Depends(get_refresh_token)):
    """注销：删除 refresh token，清除 cookie"""
    payload = decode_token(rt, expected_type="refresh")
    jti = payload.get("jti")
    if jti:
        delete_refresh_token(jti)
    _clear_refresh_cookie(response)
    return {"status": "success"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.put("/bank-mode")
async def update_bank_mode(req: BankModeRequest, current_user: dict = Depends(get_current_user)):
    if req.bank_mode not in ('public', 'personal', 'mixed'):
        raise HTTPException(status_code=400, detail="无效的题库模式，可选: public / personal / mixed")

    def _update():
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET bank_mode = ? WHERE id = ?", (req.bank_mode, current_user['id']))
            conn.commit()

    await run_db(_update)
    return {"status": "success", "bank_mode": req.bank_mode}


@router.post("/login-form")
async def login_form(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    接受 application/x-www-form-urlencoded 的登录请求。
    用于浏览器密码管理器检测（隐藏 iframe 提交），确保返回 200 触发「保存密码」提示。
    真正的认证由前端 AJAX 的 /api/auth/login 完成。
    """
    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,)
            ).fetchone()

    user = await run_db(_query)
    if not user or not verify_password(password, user['password_hash']):
        # 返回 200 而非 401，让浏览器认为提交成功从而触发保存密码
        return HTMLResponse(content="<html><body>ok</body></html>")

    return HTMLResponse(content="<html><body>ok</body></html>")
