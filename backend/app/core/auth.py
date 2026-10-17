import os
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import bcrypt
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

class JWTSecretConfigurationError(RuntimeError):
    """A signing-key configuration error with a stable diagnostic category."""

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        super().__init__(f"JWT_SECRET configuration {reason}: {detail}")


def _production_environment(values: dict[str, str]) -> bool:
    return str(values.get("ENV", "")).strip().lower() in {"production", "prod"}


def _parse_dotenv_secret(content: str) -> str | None:
    for line in content.splitlines():
        candidate = line.strip()
        if candidate.startswith("JWT_SECRET="):
            return candidate.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _validate_jwt_secret(value: str) -> str:
    secret = str(value).strip()
    if not secret:
        raise JWTSecretConfigurationError("empty", "provide a non-empty signing key")
    if len(secret) < 32:
        raise JWTSecretConfigurationError(
            "format", "signing key must contain at least 32 characters"
        )
    return secret


def _load_jwt_secret(
    values: dict[str, str] | None = None,
    env_path: Path | None = None,
) -> str:
    """Load a signing key without silently persisting a generated replacement.

    Production requires an explicitly configured key. Development/test runs
    may use a process-local ephemeral key, which is intentionally not written
    to disk and therefore cannot masquerade as durable configuration.
    """
    environ = os.environ if values is None else values
    production = _production_environment(environ)
    if "JWT_SECRET" in environ:
        return _validate_jwt_secret(environ.get("JWT_SECRET", ""))

    path = env_path or Path(__file__).resolve().parent.parent.parent / ".env"
    try:
        file_secret = _parse_dotenv_secret(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        if production:
            raise JWTSecretConfigurationError("missing", "JWT_SECRET is not configured") from exc
        file_secret = None
    except PermissionError as exc:
        raise JWTSecretConfigurationError("permission", f"cannot read {path}") from exc
    except OSError as exc:
        raise JWTSecretConfigurationError("io", f"cannot read {path}") from exc

    if file_secret is None:
        if production:
            raise JWTSecretConfigurationError("missing", "JWT_SECRET is not configured")
        return secrets.token_hex(64)
    return _validate_jwt_secret(file_secret)


SECRET_KEY = _load_jwt_secret()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
REFRESH_TOKEN_REMEMBER_DAYS = 30
TOKEN_ISSUER = "interview-boss"

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def _generate_jti() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    to_encode.update(
        {
            "exp": now
            + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)),
            "iss": TOKEN_ISSUER,
            "sub": str(data.get("user_id", "")),
            "type": "access",
            "iat": now,
        }
    )
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    data: dict,
    jti: Optional[str] = None,
    days: int = REFRESH_TOKEN_EXPIRE_DAYS,
    family_id: str = "",
) -> tuple[str, str]:
    """返回 (token, jti) 二元组，方便调用方直接拿到 jti 做服务端记录"""
    now = datetime.now(timezone.utc)
    _jti = jti or _generate_jti()
    to_encode = {
        "user_id": data["user_id"],
        "exp": now + timedelta(days=days),
        "iss": TOKEN_ISSUER,
        "sub": str(data.get("user_id", "")),
        "type": "refresh",
        "jti": _jti,
        "iat": now,
    }
    if family_id:
        to_encode["family_id"] = family_id
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM), _jti


EMAIL_BIND_TOKEN_EXPIRE_MINUTES = 30


def create_email_bind_token(user_id: int, username: str) -> str:
    """签发临时 token（type=email_bind），仅用于绑定邮箱，30 分钟有效"""
    now = datetime.now(timezone.utc)
    to_encode = {
        "user_id": user_id,
        "username": username,
        "exp": now + timedelta(minutes=EMAIL_BIND_TOKEN_EXPIRE_MINUTES),
        "iss": TOKEN_ISSUER,
        "sub": str(user_id),
        "type": "email_bind",
        "iat": now,
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_email_bind_token(token: str) -> dict:
    """解码邮箱绑定临时 token，过期或无效抛 401"""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=TOKEN_ISSUER,
            options={"require_sub": True},
        )
    except jwt.exceptions.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="临时令牌已过期或无效，请重新登录",
        )
    if payload.get("type") != "email_bind":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌类型不匹配"
        )
    return payload


def decode_token(token: str, expected_type: str = "access") -> dict:
    """解码并严格校验 JWT claims"""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=TOKEN_ISSUER,
            options={"require_sub": True},
        )
    except jwt.exceptions.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 已过期或无效"
        )

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 类型不匹配"
        )

    return payload


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """从 Authorization header 获取并验证 access token"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(credentials.credentials, expected_type="access")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 token"
        )
    # 防御性检查：非 access token（如 email_bind / refresh）不能通过 get_current_user
    if payload.get("type") not in (None, "access"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token 类型不匹配"
        )

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, username, is_admin, share_default, current_position_id, bank_mode FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

    user = await run_db(_query)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在"
        )
    result = dict(user)
    from app.db.connection import get_user_job_position

    pos_id, pos_name = await run_db(lambda: get_user_job_position(user_id))
    result["current_position_id"] = pos_id
    result["current_position"] = pos_name
    return result


async def get_admin_user(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )
    return current_user


async def get_refresh_token(request: Request) -> str:
    """从 HttpOnly cookie 提取 refresh token"""
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token 不存在，请重新登录",
        )
    return token


MAX_REFRESH_TOKENS_PER_USER = 10


def store_refresh_token(
    user_id: int,
    jti: str,
    days: int = REFRESH_TOKEN_EXPIRE_DAYS,
    remember: bool = False,
    ip_address: str = "",
    user_agent: str = "",
    family_id: str = "",
):
    """存储 refresh token 的 jti 到数据库"""
    if not family_id:
        import secrets

        family_id = secrets.token_urlsafe(16)
    with get_db_connection() as conn:
        # Per-user token limit: evict oldest if exceeded
        count = conn.execute(
            "SELECT COUNT(*) FROM refresh_tokens WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        if count >= MAX_REFRESH_TOKENS_PER_USER:
            oldest = conn.execute(
                "SELECT jti FROM refresh_tokens WHERE user_id = ? ORDER BY created_at ASC LIMIT ?",
                (user_id, count - MAX_REFRESH_TOKENS_PER_USER + 1),
            ).fetchall()
            for row in oldest:
                conn.execute("DELETE FROM refresh_tokens WHERE jti = ?", (row[0],))
        expires = datetime.now(timezone.utc) + timedelta(days=days)
        # created_at 显式写 ISO（与 expires_at 同格式），避免与 DEFAULT CURRENT_TIMESTAMP 双格式混存
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, jti, expires_at, created_at, remember, ip_address, user_agent, family_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                jti,
                expires.isoformat(),
                now_iso,
                1 if remember else 0,
                ip_address,
                user_agent,
                family_id,
            ),
        )
        conn.commit()
    return family_id


def consume_refresh_token(jti: str, user_id: int) -> Optional[dict]:
    """原子轮转 refresh token（DELETE-then-check 合并为单条语句）。

    并发同 jti 的两个刷新请求只能有一个成功：单条
    `DELETE ... WHERE jti=? AND expires_at>? AND user_id=? RETURNING *`
    同时完成有效性校验与消费，以返回行数判定（1 行 = 有效且已轮转；
    0 行 = 已用/过期/用户不匹配）。返回值即被消费的记录（remember/family
    等供轮转后续使用），无记录返回 None，调用方应 401。
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "DELETE FROM refresh_tokens WHERE jti = ? AND expires_at > ? AND user_id = ? "
            "RETURNING *",
            (jti, datetime.now(timezone.utc).isoformat(), user_id),
        ).fetchone()
        conn.commit()
        return dict(row) if row else None


def get_refresh_token_jti(jti: str) -> Optional[dict]:
    """查询 refresh token jti 是否存在且有效"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE jti = ? AND expires_at > ?",
            (jti, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        return dict(row) if row else None


def delete_refresh_token(jti: str):
    """删除 refresh token（用于注销和 token 轮转）"""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM refresh_tokens WHERE jti = ?", (jti,))
        conn.commit()


def cleanup_expired_refresh_tokens():
    """清理过期的 refresh token 记录"""
    with get_db_connection() as conn:
        conn.execute(
            "DELETE FROM refresh_tokens WHERE expires_at < ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()


def is_family_invalidated(family_id: str) -> bool:
    """检查 token family 是否已被撤销"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM invalidated_families WHERE family_id = ?", (family_id,)
        ).fetchone()
        return row is not None


def invalidate_family(family_id: str):
    """撤销整个 token family（重放攻击响应）"""
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO invalidated_families (family_id) VALUES (?)",
            (family_id,),
        )
        conn.execute("DELETE FROM refresh_tokens WHERE family_id = ?", (family_id,))
        conn.commit()
