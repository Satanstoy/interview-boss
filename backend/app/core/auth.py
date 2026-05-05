import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

# ── Secret Key: 优先读环境变量，否则自动生成并持久化到 .env ──
_env_secret = os.getenv("JWT_SECRET")
if _env_secret:
    SECRET_KEY = _env_secret
    if len(_env_secret) < 32:
        logger.warning("JWT_SECRET 长度不足 32 字节，建议使用 64 字节以上的随机字符串")
else:
    SECRET_KEY = os.urandom(64).hex()
    # 自动持久化到 .env，避免重启后所有会话失效
    try:
        from pathlib import Path
        _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        from dotenv import set_key
        set_key(str(_env_path), "JWT_SECRET", SECRET_KEY)
        logger.info("JWT_SECRET 未设置，已自动生成并写入 .env（重启后会话不再丢失）")
    except Exception as e:
        logger.warning(f"JWT_SECRET 已生成但写入 .env 失败: {e}，重启后旧 token 将失效")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
REFRESH_TOKEN_REMEMBER_DAYS = 30
TOKEN_ISSUER = "interview-boss"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _generate_jti() -> str:
    import secrets
    return secrets.token_urlsafe(32)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    to_encode.update({
        "exp": now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)),
        "iss": TOKEN_ISSUER,
        "sub": str(data.get("user_id", "")),
        "type": "access",
        "iat": now,
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict, jti: Optional[str] = None, days: int = REFRESH_TOKEN_EXPIRE_DAYS) -> tuple[str, str]:
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
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM), _jti


def decode_token(token: str, expected_type: str = "access") -> dict:
    """解码并严格校验 JWT claims"""
    try:
        payload = jwt.decode(
            token, SECRET_KEY, algorithms=[ALGORITHM],
            issuer=TOKEN_ISSUER, options={"require_sub": True}
        )
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 已过期或无效")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token 类型不匹配")

    return payload


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """从 Authorization header 获取并验证 access token"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(credentials.credentials, expected_type="access")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的 token")

    def _query():
        with get_db_connection() as conn:
            return conn.execute("SELECT id, username, is_admin, bank_mode FROM users WHERE id = ?", (user_id,)).fetchone()

    user = await run_db(_query)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return dict(user)


async def get_admin_user(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


async def get_refresh_token(request: Request) -> str:
    """从 HttpOnly cookie 提取 refresh token"""
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token 不存在，请重新登录")
    return token


def store_refresh_token(user_id: int, jti: str, days: int = REFRESH_TOKEN_EXPIRE_DAYS, remember: bool = False):
    """存储 refresh token 的 jti 到数据库"""
    with get_db_connection() as conn:
        expires = datetime.now(timezone.utc) + timedelta(days=days)
        conn.execute(
            "INSERT INTO refresh_tokens (user_id, jti, expires_at, remember) VALUES (?, ?, ?, ?)",
            (user_id, jti, expires.isoformat(), 1 if remember else 0)
        )
        conn.commit()


def get_refresh_token_jti(jti: str) -> Optional[dict]:
    """查询 refresh token jti 是否存在且有效"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM refresh_tokens WHERE jti = ? AND expires_at > ?",
            (jti, datetime.now(timezone.utc).isoformat())
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
            (datetime.now(timezone.utc).isoformat(),)
        )
        conn.commit()
