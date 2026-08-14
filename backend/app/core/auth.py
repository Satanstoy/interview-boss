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
    if len(_env_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET 长度不足 32 字节（当前 "
            f"{len(_env_secret)}）。生产环境禁止弱密钥，请使用 64 字节以上的"
            "随机字符串，或删除 .env 中的 JWT_SECRET 让系统自动生成。"
        )
    SECRET_KEY = _env_secret
else:
    # 先尝试从 .env 文件读取（避免多进程竞态各自生成不同密钥）
    try:
        from pathlib import Path

        _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if _env_path.exists():
            with open(_env_path) as f:
                for line in f:
                    if line.strip().startswith("JWT_SECRET="):
                        _env_secret = (
                            line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                        )
                        break
    except Exception:
        pass

    if _env_secret and len(_env_secret) >= 32:
        SECRET_KEY = _env_secret
    else:
        SECRET_KEY = os.urandom(64).hex()
        try:
            from pathlib import Path

            _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
            from dotenv import set_key

            set_key(str(_env_path), "JWT_SECRET", SECRET_KEY)
            logger.info(
                "JWT_SECRET 未设置，已自动生成并写入 .env（重启后会话不再丢失）"
            )
        except Exception as e:
            logger.warning(
                f"JWT_SECRET 已生成但写入 .env 失败: {e}，重启后旧 token 将失效"
            )

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
    except JWTError:
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
    except JWTError as e:
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
