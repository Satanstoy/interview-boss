import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from enum import Enum
from fastapi import APIRouter, HTTPException, Depends, Response, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter
from app.core.request_ip import get_client_ip
from app.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    create_email_bind_token,
    decode_email_bind_token,
    decode_token,
    get_current_user,
    get_refresh_token,
    store_refresh_token,
    consume_refresh_token,
    delete_refresh_token,
    is_family_invalidated,
    invalidate_family,
    REFRESH_TOKEN_EXPIRE_DAYS,
    REFRESH_TOKEN_REMEMBER_DAYS,
)
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter(prefix="/api/auth", tags=["auth"])

limiter = Limiter(key_func=get_client_ip)

# ── 账号锁定机制：连续失败 5 次后锁定 15 分钟（持久化到 SQLite）──
MAX_LOGIN_FAILURES = 5
LOCKOUT_DURATION = 900  # 15 分钟


def _check_lockout(username: str):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT failure_count, locked_until FROM login_failures WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return
        entry = dict(row)
    # locked_until 为 ISO 文本（迁移 084 由 REAL epoch 统一而来），'' 表示未锁定
    locked = entry.get("locked_until") or ""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if locked and locked > now:
        try:
            remaining = max(
                1,
                int(
                    (
                        datetime.strptime(locked, "%Y-%m-%d %H:%M:%S")
                        - datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
                    ).total_seconds()
                ),
            )
        except ValueError:
            remaining = LOCKOUT_DURATION
        raise HTTPException(
            status_code=429, detail=f"账号已被临时锁定，请 {remaining} 秒后重试"
        )
    # 仅当「曾锁定且已过期」才重置计数；未锁定（''）保留失败计数累积，
    # 否则每次登录前都会清空记录，锁定机制永不触发
    if locked:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM login_failures WHERE username = ?", (username,))
            conn.commit()


def _record_failure(username: str):
    locked_until = (
        datetime.now(timezone.utc) + timedelta(seconds=LOCKOUT_DURATION)
    ).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        # 原子 upsert：并发登录失败不会因 SELECT-then-INSERT 竞态丢失计数或撞唯一索引
        conn.execute(
            """
            INSERT INTO login_failures (username, failure_count, locked_until)
            VALUES (?, 1, '')
            ON CONFLICT(username) DO UPDATE SET
                failure_count = login_failures.failure_count + 1,
                locked_until = CASE
                    WHEN login_failures.failure_count + 1 >= ? THEN ?
                    ELSE ''
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (username, MAX_LOGIN_FAILURES, locked_until),
        )
        conn.commit()
        count_row = conn.execute(
            "SELECT failure_count FROM login_failures WHERE username = ?", (username,)
        ).fetchone()
    if count_row and count_row["failure_count"] >= MAX_LOGIN_FAILURES:
        logger.warning(
            f"账号 '{username}' 连续失败 {count_row['failure_count']} 次，已锁定 {LOCKOUT_DURATION}s"
        )


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


def _is_same_origin_request(request: Request) -> bool:
    """校验请求的 Origin/Referer 与本站同源（用于 form-urlencoded 的 CSRF 豁免端点）。

    login-form 因供浏览器密码管理器（隐藏 iframe 提交、无法带自定义头）使用而豁免
    CSRF 中间件；为封堵跨站表单可触发的锁定 DoS，这里补一道同源校验：跨站页面
    提交的 Origin/Referer 与本站 host 不一致则拒绝。
    Origin 缺失时回退 Referer；两者皆无（非浏览器客户端）按同源放行。
    比较口径：仅比 host（及非默认端口），忽略 scheme 差异（http/https 视为同源）。
    """
    from urllib.parse import urlsplit

    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        origin_host = (parsed.hostname or "").lower()
        if parsed.port and parsed.port not in (80, 443):
            origin_host = f"{origin_host}:{parsed.port}"
    except ValueError:
        return False

    host_header = (request.headers.get("host", "") or "").lower()
    if not host_header:
        return True
    # Host 头形如 "example.com" 或 "example.com:8443"，直接与 origin host（已含非默认端口）比较
    return origin_host == host_header


RESERVED_USERNAMES = {
    "admin",
    "root",
    "system",
    "null",
    "undefined",
    "superuser",
    "moderator",
    "guest",
    "test",
}


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_一-鿿]{2,32}$")


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)
    email: str = Field(..., min_length=5, max_length=120)

    @field_validator("username")
    @classmethod
    def username_format(cls, v):
        # 归一化：去首尾空白 + 小写（users.username 唯一约束为 BINARY，防 Alice/alice 双账户）
        v = v.strip().lower()
        if not _USERNAME_RE.match(v):
            raise ValueError("用户名仅允许 2-32 个字母、数字、下划线或中文")
        return v

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v):
        categories = 0
        if any(c.isupper() for c in v):
            categories += 1
        if any(c.islower() for c in v):
            categories += 1
        if any(c.isdigit() for c in v):
            categories += 1
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?/~`" for c in v):
            categories += 1
        if categories < 2:
            raise ValueError("密码需包含大写字母、小写字母、数字、特殊字符中的至少两种")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        if not _EMAIL_RE.match(v):
            raise ValueError("请输入有效的邮箱地址")
        return v.lower().strip()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)
    remember_me: bool = False


class ShareDefault(str, Enum):
    share = "share"
    private = "private"


class ShareDefaultRequest(BaseModel):
    share_default: ShareDefault


def _is_secure(request: Request) -> bool:
    """根据请求协议决定 cookie 是否需要 secure 标志"""
    proto = request.headers.get("x-forwarded-proto", "")
    if proto:
        return proto.lower() == "https"
    return request.url.scheme == "https"


def _set_refresh_cookie(
    response: Response, token: str, request: Request, remember: bool = False
):
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
    response.delete_cookie(
        key="refresh_token",
        path="/",
        httponly=True,
        secure=_is_secure(request),
        samesite="lax",
    )


def _issue_token_pair(
    user: dict,
    response: Response,
    request: Request,
    remember: bool = False,
    ip_address: str = "",
    user_agent: str = "",
    family_id: str = "",
) -> dict:
    """签发 access + refresh token，设置 cookie，返回响应体"""
    import secrets

    days = REFRESH_TOKEN_REMEMBER_DAYS if remember else REFRESH_TOKEN_EXPIRE_DAYS
    token_data = {"user_id": user["id"], "username": user["username"]}
    access_token = create_access_token(token_data)
    if not family_id:
        family_id = secrets.token_urlsafe(16)
    refresh_token, jti = create_refresh_token(
        token_data, days=days, family_id=family_id
    )
    store_refresh_token(
        user["id"],
        jti,
        days=days,
        remember=remember,
        ip_address=ip_address,
        user_agent=user_agent,
        family_id=family_id,
    )
    _set_refresh_cookie(response, refresh_token, request, remember=remember)
    # 获取用户真实当前岗位：个人岗位优先，其次 current_position_id，最后全局 fallback
    from app.db.connection import get_user_job_position

    pos_id, pos_name = get_user_job_position(user["id"])
    return {
        "token": access_token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "is_admin": bool(user.get("is_admin", False)),
            "share_default": user.get("share_default", "private") or "private",
            "current_position_id": pos_id,
            "current_position": pos_name,
        },
    }


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, req: RegisterRequest, response: Response):
    if req.username.lower() in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail="该用户名为系统保留，请更换")

    def _create():
        with get_db_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE username = ?", (req.username,)
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="用户名已存在")
            email_taken = conn.execute(
                "SELECT id FROM users WHERE email = ?", (req.email,)
            ).fetchone()
            if email_taken:
                raise HTTPException(status_code=409, detail="该邮箱已被注册")
            password_hash = hash_password(req.password)
            try:
                cursor = conn.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin, share_default) VALUES (?, ?, ?, 0, 'private')",
                    (req.username, password_hash, req.email),
                )
            except sqlite3.IntegrityError:
                # 并发下另一个请求在检查与 INSERT 之间抢先插入了同 username/email，
                # 撞唯一索引；读取当前状态区分冲突来源后映射为 409。
                if conn.execute(
                    "SELECT id FROM users WHERE username = ?", (req.username,)
                ).fetchone():
                    raise HTTPException(status_code=409, detail="用户名已存在")
                raise HTTPException(status_code=409, detail="该邮箱已被注册")
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
        {
            "id": user_id,
            "username": req.username,
            "is_admin": False,
            "share_default": "private",
        },
        response,
        request,
        remember=False,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest, response: Response):
    # 与注册同一归一化口径：去空白 + 小写（迁移 085 已回填存量用户名）
    username = req.username.strip().lower()
    _check_lockout(username)

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash, is_admin, share_default, current_position_id, email FROM users WHERE username = ?",
                (username,),
            ).fetchone()

    user = await run_db(_query)
    if not user:
        # Dummy bcrypt to prevent timing oracle (user enumeration)
        verify_password(
            req.password, "$2b$12$eiMGPX1FDYPSJnrbi.E9Ee6eXtF/sNWWAxyCmK5Al2yYy4/wj0QAm"
        )
        _record_failure(username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(req.password, user["password_hash"]):
        _record_failure(username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _clear_failures(username)

    # 未绑定邮箱的老用户：返回临时 token，要求绑定邮箱
    if not user["email"]:
        temp_token = create_email_bind_token(user["id"], user["username"])
        return {
            "need_email_bind": True,
            "temp_token": temp_token,
            "message": "请先绑定邮箱后再使用系统",
            "user": {"id": user["id"], "username": user["username"]},
        }

    return _issue_token_pair(
        dict(user),
        response,
        request,
        remember=req.remember_me,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )


@router.post("/refresh")
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    response: Response,
    _csrf: None = Depends(_require_custom_header),
    rt: str = Depends(get_refresh_token),
):
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

    # 原子轮转：单条 DELETE（jti + expires_at>now + user_id）同时校验与消费。
    # 并发同 jti 的多个请求只有一个能拿到 1 行（返回记录），其余拿到 None（已轮转/过期）→ 401。
    record = consume_refresh_token(jti, user_id)
    if not record:
        # JTI 已被消费或不属于该用户或已过期 — 可能是重放攻击
        if family_id:
            invalidate_family(family_id)
            logger.warning(
                f"检测到可能的 token 重放攻击: user_id={user_id}, family_id={family_id}"
            )
        _clear_refresh_cookie(response, request)
        raise HTTPException(status_code=401, detail="refresh token 已失效，请重新登录")

    remember = bool(record.get("remember", 0))
    # 使用已有的 family_id（如果 DB 中有则优先用 DB 中的）
    db_family_id = record.get("family_id", "") or family_id

    # B2: IP/UA 异常检测 — 记录安全日志但不阻断（避免误伤移动用户）
    current_ip = request.client.host if request.client else ""
    current_ua = request.headers.get("user-agent", "")
    stored_ip = record.get("ip_address", "")
    stored_ua = record.get("user_agent", "")
    if stored_ip and current_ip and stored_ip != current_ip:
        logger.warning(
            f"Refresh Token IP 不一致: user_id={user_id}, 存储IP={stored_ip}, 当前IP={current_ip}"
        )
    if stored_ua and current_ua and stored_ua != current_ua:
        logger.warning(f"Refresh Token UA 不一致: user_id={user_id}")

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, is_admin, share_default, current_position_id FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

    user = await run_db(_query)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    return _issue_token_pair(
        dict(user),
        response,
        request,
        remember=remember,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        family_id=db_family_id,
    )


@router.post("/logout")
async def logout(
    request: Request, response: Response, _csrf: None = Depends(_require_custom_header)
):
    """注销：删除 refresh token，清除 cookie。幂等：无 cookie 也返回成功。"""
    rt = request.cookies.get("refresh_token")
    if rt:
        try:
            payload = decode_token(rt, expected_type="refresh")
            family_id = payload.get("family_id", "")
            if family_id:
                invalidate_family(family_id)
            else:
                jti = payload.get("jti")
                if jti:
                    delete_refresh_token(jti)
        except HTTPException:
            pass  # Token 可能已过期或无效，仍需清除 cookie
    _clear_refresh_cookie(response, request)
    return {"status": "success"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.put("/share-default")
async def update_share_default(
    req: ShareDefaultRequest, current_user: dict = Depends(get_current_user)
):
    """更新用户导入分享默认值（share=分享到公共题库 / private=仅自己可见）"""

    def _update():
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET share_default = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (req.share_default.value, current_user["id"]),
            )
            conn.commit()

    await run_db(_update)
    return {"status": "success", "share_default": req.share_default.value}


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
    # 该端点因密码管理器表单提交而豁免全局 CSRF，这里补同源校验，
    # 封堵跨站表单可触发的账号锁定 DoS（跨源 Origin/Referer 一律拒绝）。
    if not _is_same_origin_request(request):
        logger.warning("login-form 检测到跨源请求，已拒绝（锁定 DoS 防护）")
        raise HTTPException(status_code=403, detail="跨源表单提交被拒绝")
    username = username.strip().lower()
    _check_lockout(username)

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()

    user = await run_db(_query)
    if not user or not verify_password(password, user["password_hash"]):
        _record_failure(username)
        # 仍然返回 200 触发密码管理器，但失败计数已记录，超过阈值后 /login 会返回 429
        return HTMLResponse(content="<html><body>ok</body></html>")

    _clear_failures(username)
    return HTMLResponse(content="<html><body>ok</body></html>")


# ── 邮箱验证码登录 / 注册 ──────────────────────────────────────────

from app.services.email_service import send_verification_code, verify_code


def _validate_password_complexity(v: str) -> str:
    categories = 0
    if any(c.isupper() for c in v):
        categories += 1
    if any(c.islower() for c in v):
        categories += 1
    if any(c.isdigit() for c in v):
        categories += 1
    if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?/~`" for c in v):
        categories += 1
    if categories < 2:
        raise ValueError("密码需包含大写字母、小写字母、数字、特殊字符中的至少两种")
    return v


class SendCodeRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    purpose: str = Field(..., pattern=r"^(register|login|bind|reset_password)$")

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        if not _EMAIL_RE.match(v):
            raise ValueError("请输入有效的邮箱地址")
        return v.lower().strip()


class EmailRegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def username_format(cls, v):
        # 归一化：去首尾空白 + 小写（users.username 唯一约束为 BINARY，防 Alice/alice 双账户）
        v = v.strip().lower()
        if not _USERNAME_RE.match(v):
            raise ValueError("用户名仅允许 2-32 个字母、数字、下划线或中文")
        return v

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v):
        return _validate_password_complexity(v)

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        if not _EMAIL_RE.match(v):
            raise ValueError("请输入有效的邮箱地址")
        return v.lower().strip()


class EmailLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        if not _EMAIL_RE.match(v):
            raise ValueError("请输入有效的邮箱地址")
        return v.lower().strip()


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        if not _EMAIL_RE.match(v):
            raise ValueError("请输入有效的邮箱地址")
        return v.lower().strip()

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v):
        return _validate_password_complexity(v)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v):
        return _validate_password_complexity(v)


def _check_username_available(username: str) -> bool:
    """检查用户名是否可用"""
    with get_db_connection() as conn:
        return (
            conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            is None
        )


def _check_email_exists(email: str) -> bool:
    """检查邮箱是否已被注册"""
    with get_db_connection() as conn:
        return (
            conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            is not None
        )


def _find_user_by_email(email: str):
    """通过邮箱查找用户"""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, is_admin, share_default, current_position_id FROM users WHERE email = ?",
            (email,),
        ).fetchone()


def _insert_user(username: str, password_hash: str, email: str) -> dict:
    """创建新用户"""
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, email, is_admin, share_default) VALUES (?, ?, ?, 0, 'private')",
                (username, password_hash, email),
            )
        except sqlite3.IntegrityError:
            # 并发下另一个请求在同 email/username 上抢先注册，撞唯一索引 → 409
            if conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone():
                raise HTTPException(status_code=409, detail="用户名已存在")
            raise HTTPException(status_code=409, detail="该邮箱已注册")
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "username": username,
            "is_admin": False,
            "share_default": "private",
        }


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
async def register_with_email(
    request: Request, req: EmailRegisterRequest, response: Response
):
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
        user,
        response,
        request,
        remember=False,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )


@router.post("/login-with-email")
@limiter.limit("10/minute")
async def login_with_email(
    request: Request, req: EmailLoginRequest, response: Response
):
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
        dict(user),
        response,
        request,
        remember=False,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, req: PasswordResetRequest):
    """通过已绑定邮箱验证码重置密码。"""
    valid = await verify_code(req.email, req.code, "reset_password")
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    user = _find_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱未注册")

    password_hash = hash_password(req.new_password)

    def _update():
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (password_hash, user["id"]),
            )
            conn.commit()

    await run_db(_update)
    _clear_failures(user["username"])
    return {"status": "success", "message": "密码已重置，请使用新密码登录"}


@router.post("/change-password")
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """已登录用户修改密码。"""

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, password_hash FROM users WHERE id = ?",
                (current_user["id"],),
            ).fetchone()

    user = await run_db(_query)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not verify_password(req.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if verify_password(req.new_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    password_hash = hash_password(req.new_password)

    def _update():
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (password_hash, user["id"]),
            )
            conn.commit()

    await run_db(_update)
    return {"status": "success", "message": "密码修改成功"}


# ── 临时 token 绑定邮箱（老用户首次登录强制绑定）──────────────────────


class BindEmailWithTokenRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def email_format(cls, v):
        if not _EMAIL_RE.match(v):
            raise ValueError("请输入有效的邮箱地址")
        return v.lower().strip()


@router.post("/bind-email-with-token")
@limiter.limit("5/minute")
async def bind_email_with_token(
    request: Request,
    req: BindEmailWithTokenRequest,
    response: Response,
    temp_token: str = "",
):
    """用临时 token + 验证码绑定邮箱，成功后返回正式 token pair"""
    # 从 header 或 query 参数获取临时 token
    if not temp_token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            temp_token = auth_header[7:]
    if not temp_token:
        temp_token = request.query_params.get("temp_token", "")
    if not temp_token:
        raise HTTPException(status_code=401, detail="缺少临时令牌")

    payload = decode_email_bind_token(temp_token)
    user_id = payload["user_id"]
    username = payload.get("username", "")

    # 验证邮箱验证码
    valid = await verify_code(req.email, req.code, "bind")
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    # 检查邮箱是否已被其他用户占用
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ? AND id != ?", (req.email, user_id)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="该邮箱已被其他用户绑定")
        try:
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (req.email, user_id))
            conn.commit()
        except sqlite3.IntegrityError:
            # 并发下另一请求抢先绑定了该邮箱，撞唯一索引 → 409
            raise HTTPException(status_code=409, detail="该邮箱已被其他用户绑定")

    return _issue_token_pair(
        {
            "id": user_id,
            "username": username,
            "is_admin": False,
            "share_default": "private",
        },
        response,
        request,
        remember=False,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
