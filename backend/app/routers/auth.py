import logging
import re
import time
from enum import Enum
from fastapi import APIRouter, HTTPException, Depends, Response, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.auth import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    decode_token, get_current_user, get_refresh_token,
    store_refresh_token, get_refresh_token_jti, delete_refresh_token,
    is_family_invalidated, invalidate_family,
    REFRESH_TOKEN_EXPIRE_DAYS, REFRESH_TOKEN_REMEMBER_DAYS,
)
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter(prefix="/api/auth", tags=["auth"])

limiter = Limiter(key_func=get_remote_address)

# ── 账号锁定机制：连续失败 5 次后锁定 15 分钟（持久化到 SQLite）──
MAX_LOGIN_FAILURES = 5
LOCKOUT_DURATION = 900  # 15 分钟


def _check_lockout(username: str):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT failure_count, locked_until FROM login_failures WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return
        entry = dict(row)
    now = time.time()
    if entry.get("locked_until", 0) > now:
        remaining = int(entry["locked_until"] - now)
        raise HTTPException(
            status_code=429,
            detail=f"账号已被临时锁定，请 {remaining} 秒后重试"
        )
    # 锁定已过期，重置
    with get_db_connection() as conn:
        conn.execute("DELETE FROM login_failures WHERE username = ?", (username,))
        conn.commit()


def _record_failure(username: str):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT failure_count FROM login_failures WHERE username = ?", (username,)
        ).fetchone()
        if row:
            new_count = row["failure_count"] + 1
            locked_until = time.time() + LOCKOUT_DURATION if new_count >= MAX_LOGIN_FAILURES else 0
            conn.execute(
                "UPDATE login_failures SET failure_count = ?, locked_until = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                (new_count, locked_until, username)
            )
        else:
            conn.execute(
                "INSERT INTO login_failures (username, failure_count, locked_until) VALUES (?, 1, 0)",
                (username,)
            )
        conn.commit()
    if row and row["failure_count"] + 1 >= MAX_LOGIN_FAILURES:
        logger.warning(f"账号 '{username}' 连续失败 {row['failure_count'] + 1} 次，已锁定 {LOCKOUT_DURATION}s")


def _clear_failures(username: str):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM login_failures WHERE username = ?", (username,))
        conn.commit()


def _require_custom_header(request: Request):
    """CSRF 防护：要求请求携带自定义头 X-Requested-With。
    跨域页面无法在简单请求中设置自定义头，因此可阻止 CSRF。
    同时也接受 Content-Type: application/json（前端所有 API 调用均使用 JSON）。
    """
    if request.headers.get("X-Requested-With"):
        return
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        return
    raise HTTPException(status_code=403, detail="缺少必要的请求头，请通过前端发起请求")


RESERVED_USERNAMES = {'admin', 'root', 'system', 'null', 'undefined', 'superuser', 'moderator', 'guest', 'test'}


_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_一-鿿]{2,32}$')


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator('username')
    @classmethod
    def username_format(cls, v):
        if not _USERNAME_RE.match(v):
            raise ValueError('用户名仅允许 2-32 个字母、数字、下划线或中文')
        return v

    @field_validator('password')
    @classmethod
    def password_complexity(cls, v):
        categories = 0
        if any(c.isupper() for c in v): categories += 1
        if any(c.islower() for c in v): categories += 1
        if any(c.isdigit() for c in v): categories += 1
        if any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?/~`' for c in v): categories += 1
        if categories < 2:
            raise ValueError('密码需包含大写字母、小写字母、数字、特殊字符中的至少两种')
        return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)
    remember_me: bool = False


class BankMode(str, Enum):
    public = "public"
    personal = "personal"
    mixed = "mixed"


class BankModeRequest(BaseModel):
    bank_mode: BankMode


def _is_secure(request: Request) -> bool:
    """根据请求协议决定 cookie 是否需要 secure 标志"""
    proto = request.headers.get("x-forwarded-proto", "")
    if proto:
        return proto.lower() == "https"
    return request.url.scheme == "https"


def _set_refresh_cookie(response: Response, token: str, request: Request, remember: bool = False):
    days = REFRESH_TOKEN_REMEMBER_DAYS if remember else REFRESH_TOKEN_EXPIRE_DAYS
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=_is_secure(request),
        samesite="lax",
        max_age=days * 86400,
        path="/",
    )


def _clear_refresh_cookie(response: Response, request: Request):
    response.delete_cookie(key="refresh_token", path="/", httponly=True, secure=_is_secure(request), samesite="lax")


def _issue_token_pair(user: dict, response: Response, request: Request, remember: bool = False, ip_address: str = "", user_agent: str = "", family_id: str = "") -> dict:
    """签发 access + refresh token，设置 cookie，返回响应体"""
    import secrets
    days = REFRESH_TOKEN_REMEMBER_DAYS if remember else REFRESH_TOKEN_EXPIRE_DAYS
    token_data = {"user_id": user['id'], "username": user['username']}
    access_token = create_access_token(token_data)
    if not family_id:
        family_id = secrets.token_urlsafe(16)
    refresh_token, jti = create_refresh_token(token_data, days=days, family_id=family_id)
    store_refresh_token(user['id'], jti, days=days, remember=remember, ip_address=ip_address, user_agent=user_agent, family_id=family_id)
    _set_refresh_cookie(response, refresh_token, request, remember=remember)
    # 获取岗位名称
    pos_name = ""
    pos_id = user.get('current_position_id')
    if pos_id:
        with get_db_connection() as conn:
            jp = conn.execute("SELECT name FROM job_positions WHERE id = ?", (pos_id,)).fetchone()
            if jp:
                pos_name = jp['name']
    if not pos_name:
        from app.db.connection import get_current_job_position
        pos_name = get_current_job_position()
    return {
        "token": access_token,
        "user": {
            "id": user['id'],
            "username": user['username'],
            "is_admin": bool(user.get('is_admin', False)),
            "bank_mode": user.get('bank_mode', 'public') or 'public',
            "current_position_id": pos_id,
            "current_position": pos_name
        }
    }


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, req: RegisterRequest, response: Response):
    if req.username.lower() in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail="该用户名为系统保留，请更换")
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

    return _issue_token_pair(
        {"id": user_id, "username": req.username, "is_admin": False, "bank_mode": "public"},
        response, request, remember=False,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", "")
    )


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest, response: Response):
    _check_lockout(req.username)

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash, is_admin, bank_mode, current_position_id FROM users WHERE username = ?",
                (req.username,)
            ).fetchone()

    user = await run_db(_query)
    if not user:
        # Dummy bcrypt to prevent timing oracle (user enumeration)
        verify_password(req.password, "$2b$12$eiMGPX1FDYPSJnrbi.E9Ee6eXtF/sNWWAxyCmK5Al2yYy4/wj0QAm")
        _record_failure(req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, user['password_hash']):
        _record_failure(req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _clear_failures(req.username)
    return _issue_token_pair(
        dict(user), response, request, remember=req.remember_me,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", "")
    )


@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh_token(request: Request, response: Response, _csrf: None = Depends(_require_custom_header), rt: str = Depends(get_refresh_token)):
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

    family_id = payload.get("family_id", "")

    # 检查 family 是否已被撤销（重放攻击响应）
    if family_id and is_family_invalidated(family_id):
        _clear_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="token 已失效，请重新登录")

    record = get_refresh_token_jti(jti)
    if not record or record['user_id'] != user_id:
        # JTI 不在数据库中 — 可能是重放攻击
        if family_id:
            invalidate_family(family_id)
            logger.warning(f"检测到可能的 token 重放攻击: user_id={user_id}, family_id={family_id}")
        _clear_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="refresh token 已失效，请重新登录")

    remember = bool(record.get('remember', 0))
    # 使用已有的 family_id（如果 DB 中有则优先用 DB 中的）
    db_family_id = record.get('family_id', '') or family_id

    # B2: IP/UA 异常检测 — 记录安全日志但不阻断（避免误伤移动用户）
    current_ip = request.client.host if request.client else ""
    current_ua = request.headers.get("user-agent", "")
    stored_ip = record.get('ip_address', '')
    stored_ua = record.get('user_agent', '')
    if stored_ip and current_ip and stored_ip != current_ip:
        logger.warning(f"Refresh Token IP 不一致: user_id={user_id}, 存储IP={stored_ip}, 当前IP={current_ip}")
    if stored_ua and current_ua and stored_ua != current_ua:
        logger.warning(f"Refresh Token UA 不一致: user_id={user_id}")

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, is_admin, bank_mode, current_position_id FROM users WHERE id = ?", (user_id,)
            ).fetchone()

    user = await run_db(_query)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    delete_refresh_token(jti)
    return _issue_token_pair(
        dict(user), response, request, remember=remember,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        family_id=db_family_id
    )


@router.post("/logout")
async def logout(request: Request, response: Response, rt: str = Depends(get_refresh_token), _csrf: None = Depends(_require_custom_header)):
    """注销：删除 refresh token，清除 cookie"""
    try:
        payload = decode_token(rt, expected_type="refresh")
        jti = payload.get("jti")
        if jti:
            delete_refresh_token(jti)
    except HTTPException:
        pass  # Token 可能已过期，仍需清除 cookie
    _clear_refresh_cookie(response, request)
    return {"status": "success"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.put("/bank-mode")
async def update_bank_mode(req: BankModeRequest, current_user: dict = Depends(get_current_user)):
    def _update():
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET bank_mode = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (req.bank_mode.value, current_user['id']))
            conn.commit()

    await run_db(_update)
    return {"status": "success", "bank_mode": req.bank_mode.value}


@router.post("/login-form")
@limiter.limit("10/minute")
async def login_form(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    接受 application/x-www-form-urlencoded 的登录请求。
    用于浏览器密码管理器检测（隐藏 iframe 提交）。
    """
    _check_lockout(username)

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,)
            ).fetchone()

    user = await run_db(_query)
    if not user or not verify_password(password, user['password_hash']):
        _record_failure(username)
        # 仍然返回 200 触发密码管理器，但失败计数已记录，超过阈值后 /login 会返回 429
        return HTMLResponse(content="<html><body>ok</body></html>")

    _clear_failures(username)
    return HTMLResponse(content="<html><body>ok</body></html>")


# ── 邮箱验证码登录 / 注册 ──────────────────────────────────────────

from app.services.email_service import send_verification_code, verify_code


class SendCodeRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    purpose: str = Field(..., pattern=r'^(register|login|bind)$')


class EmailRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator('username')
    @classmethod
    def username_format(cls, v):
        if not _USERNAME_RE.match(v):
            raise ValueError('用户名仅允许 2-32 个字母、数字、下划线或中文')
        return v

    @field_validator('password')
    @classmethod
    def password_complexity(cls, v):
        categories = 0
        if any(c.isupper() for c in v): categories += 1
        if any(c.islower() for c in v): categories += 1
        if any(c.isdigit() for c in v): categories += 1
        if any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?/~`' for c in v): categories += 1
        if categories < 2:
            raise ValueError('密码需包含大写字母、小写字母、数字、特殊字符中的至少两种')
        return v


class EmailLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)


def _check_username_available(username: str) -> bool:
    """检查用户名是否可用"""
    with get_db_connection() as conn:
        return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone() is None


def _check_email_exists(email: str) -> bool:
    """检查邮箱是否已被注册"""
    with get_db_connection() as conn:
        return conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone() is not None


def _find_user_by_email(email: str):
    """通过邮箱查找用户"""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT id, username, is_admin, bank_mode, current_position_id FROM users WHERE email = ?",
            (email,)
        ).fetchone()


def _insert_user(username: str, password_hash: str, email: str) -> dict:
    """创建新用户"""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, email, is_admin, bank_mode) VALUES (?, ?, ?, 0, 'public')",
            (username, password_hash, email)
        )
        conn.commit()
        return {"id": cursor.lastrowid, "username": username, "is_admin": False, "bank_mode": "public"}


@router.post("/send-code")
@limiter.limit("3/minute")
async def send_code(request: Request, req: SendCodeRequest):
    """发送邮箱验证码"""
    result = await send_verification_code(req.email, req.purpose)
    if not result["success"]:
        status = 503 if "未配置" in result["message"] else 429
        raise HTTPException(status_code=status, detail=result["message"])
    return result


@router.post("/register-with-email")
@limiter.limit("5/minute")
async def register_with_email(request: Request, req: EmailRegisterRequest, response: Response):
    """邮箱验证码注册"""
    # 校验验证码
    valid = await verify_code(req.email, req.code, "register")
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    # 检查用户名
    if req.username.lower() in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail="该用户名为系统保留，请更换")
    if not _check_username_available(req.username):
        raise HTTPException(status_code=409, detail="用户名已存在")

    # 检查邮箱
    if _check_email_exists(req.email):
        raise HTTPException(status_code=409, detail="该邮箱已注册")

    # 创建用户
    password_hash = hash_password(req.password)
    user = _insert_user(req.username, password_hash, req.email)

    return _issue_token_pair(
        user, response, request, remember=False,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", "")
    )


@router.post("/login-with-email")
@limiter.limit("10/minute")
async def login_with_email(request: Request, req: EmailLoginRequest, response: Response):
    """邮箱验证码登录"""
    # 校验验证码
    valid = await verify_code(req.email, req.code, "login")
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    # 查找用户
    user = _find_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱未注册")

    return _issue_token_pair(
        dict(user), response, request, remember=False,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", "")
    )
