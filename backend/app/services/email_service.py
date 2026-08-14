"""
邮箱验证码服务
发送验证码、校验验证码、SMTP发送
"""
import random
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from app.db.connection import get_db_connection

# 连续失败多少次后作废该验证码（audit D4：每邮箱失败锁定）
LOCKOUT_THRESHOLD = 5
# 用于在 email_verification_codes 中记录（email, purpose）失败计数的保留行标记，
# 避免与真实验证码混淆。不新增表列（保持迁移零改动），复用该表作为只读账本。
_LOCKOUT_MARKER = "__lockout__"
_LOCKOUT_TTL_SECONDS = 3600


def generate_verification_code() -> str:
    """生成6位数字验证码"""
    return f"{random.randint(0, 999999):06d}"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _parse_db_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _get_smtp_config() -> Optional[dict]:
    """获取SMTP配置，未配置返回None"""
    host = os.environ.get("SMTP_HOST")
    port = os.environ.get("SMTP_PORT")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    if not all([host, port, username, password]):
        return None
    return {
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "from_addr": os.environ.get("SMTP_FROM", username),
        "from_name": os.environ.get("SMTP_FROM_NAME", "InterviewBoss"),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
    }


async def _smtp_send(to_addr: str, subject: str, body: str) -> bool:
    """通过SMTP发送邮件"""
    config = _get_smtp_config()
    if not config:
        return False
    import smtplib
    from email.mime.text import MIMEText

    from email.utils import formataddr
    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((config.get("from_name", "InterviewBoss"), config["from_addr"]))
    msg["To"] = to_addr

    def _send():
        if config["use_tls"]:
            server = smtplib.SMTP_SSL(config["host"], config["port"])
        else:
            server = smtplib.SMTP(config["host"], config["port"])
            server.starttls()
        server.login(config["username"], config["password"])
        server.sendmail(config["from_addr"], [to_addr], msg.as_string())
        server.quit()

    try:
        await asyncio.to_thread(_send)
        return True
    except Exception:
        return False


# ── 每邮箱失败计数账本（不使用 added column，复用 email_verification_codes 表）──


def _get_failure_count(email: str, purpose: str) -> int:
    """读取 (email, purpose) 已累计的连续失败次数；账本过期则视为 0。"""
    normalized_email = _normalize_email(email)
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT used AS cnt, expires_at
        FROM email_verification_codes
        WHERE email = ? AND purpose = ? AND code = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (normalized_email, purpose, _LOCKOUT_MARKER),
    ).fetchone()
    if not row:
        return 0
    if _parse_db_datetime(row["expires_at"]) < datetime.now():
        return 0
    try:
        return int(row["cnt"])
    except (TypeError, ValueError):
        return 0


def _reset_failure_count(email: str, purpose: str):
    """清除 (email, purpose) 的失败计数账本。"""
    normalized_email = _normalize_email(email)
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM email_verification_codes WHERE email = ? AND purpose = ? AND code = ?",
        (normalized_email, purpose, _LOCKOUT_MARKER),
    )
    conn.commit()


def _record_failure(email: str, purpose: str, count: int):
    """把 (email, purpose) 的失败计数写入账本（单行覆盖）。"""
    normalized_email = _normalize_email(email)
    expires_at = (datetime.now() + timedelta(seconds=_LOCKOUT_TTL_SECONDS)).isoformat()
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM email_verification_codes WHERE email = ? AND purpose = ? AND code = ?",
        (normalized_email, purpose, _LOCKOUT_MARKER),
    )
    # 计数存于 used 列，code 恒为保留标记 _LOCKOUT_MARKER 以便唯一识别账本行。
    # used 非 0 也避免被 _store_code 的"作废旧码"UPDATE 波及；该行不是真实验证码。
    conn.execute(
        """
        INSERT INTO email_verification_codes (email, code, purpose, expires_at, used)
        VALUES (?, ?, ?, ?, ?)
        """,
        (normalized_email, _LOCKOUT_MARKER, purpose, expires_at, count),
    )
    conn.commit()


def _store_code(email: str, code: str, purpose: str, ttl_seconds: int = 300):
    """存储验证码到 SQLite，确保多 worker 进程共享。"""
    normalized_email = _normalize_email(email)
    # 发送新码即重置该邮箱+purpose 的失败计数（audit D4）
    _reset_failure_count(normalized_email, purpose)
    expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
    conn = get_db_connection()
    conn.execute(
        "UPDATE email_verification_codes SET used = 1 WHERE email = ? AND purpose = ? AND used = 0",
        (normalized_email, purpose)
    )
    conn.execute(
        """
        INSERT INTO email_verification_codes (email, code, purpose, expires_at, used)
        VALUES (?, ?, ?, ?, 0)
        """,
        (normalized_email, code, purpose, expires_at.isoformat())
    )
    conn.commit()


def _get_stored_code(email: str, purpose: str) -> Optional[dict]:
    """获取存储的验证码"""
    normalized_email = _normalize_email(email)
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT id, code, expires_at, used
        FROM email_verification_codes
        WHERE email = ? AND purpose = ? AND used = 0
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (normalized_email, purpose)
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "code": row["code"],
        "expires_at": _parse_db_datetime(row["expires_at"]),
        "used": bool(row["used"]),
    }


async def send_verification_code(email: str, purpose: str) -> dict:
    """
    发送验证码

    Args:
        email: 目标邮箱
        purpose: 用途 ('register' | 'login' | 'bind' | 'reset_password')

    Returns:
        {"success": bool, "message": str, "expires_in": int}
    """
    # 检查SMTP配置
    if _get_smtp_config() is None:
        return {"success": False, "message": "邮箱服务未配置，请联系管理员", "expires_in": 0}

    # 检查频率限制（60秒）
    stored = _get_stored_code(email, purpose)
    if stored and not stored["used"]:
        remaining = (stored["expires_at"] - datetime.now()).total_seconds()
        # 如果上次发送距今不到60秒，拒绝
        if remaining > 240:  # 300-60=240，即验证码还有超过240秒有效说明刚发
            return {"success": False, "message": "发送过于频繁，请60秒后重试", "expires_in": 0}

    # 生成并存储验证码
    code = generate_verification_code()
    _store_code(email, code, purpose, ttl_seconds=300)

    # 构建邮件内容
    purpose_text = {
        "register": "注册",
        "login": "登录",
        "bind": "绑定邮箱",
        "reset_password": "重置密码",
    }.get(purpose, "验证")
    subject = f"【InterviewBoss】{purpose_text}验证码"
    body = f"""
    <div style="font-family: sans-serif; max-width: 400px; margin: 0 auto;">
        <h2 style="color: #333;">InterviewBoss {purpose_text}</h2>
        <p>您的验证码是：</p>
        <div style="font-size: 32px; font-weight: bold; color: #4F46E5; letter-spacing: 8px; text-align: center; padding: 20px; background: #F3F4F6; border-radius: 8px;">
            {code}
        </div>
        <p style="color: #666; font-size: 14px;">验证码5分钟内有效，请勿泄露给他人。</p>
    </div>
    """

    # 发送邮件
    sent = await _smtp_send(email, subject, body)
    if not sent:
        return {"success": False, "message": "邮件发送失败，请稍后重试", "expires_in": 0}

    return {"success": True, "message": "验证码已发送", "expires_in": 300}


async def verify_code(email: str, code: str, purpose: str) -> bool:
    """
    校验验证码

    Args:
        email: 邮箱
        code: 用户输入的验证码
        purpose: 用途

    Returns:
        True 校验通过, False 校验失败
    """
    normalized_email = _normalize_email(email)

    # audit D4：每邮箱连续失败达阈值后，直接拒绝（作废该码）
    if _get_failure_count(normalized_email, purpose) >= LOCKOUT_THRESHOLD:
        return False

    # audit D14：校验 + 标记已用合并为单条原子 UPDATE。
    # 只有同时满足 email/purpose/未用/验证码正确/未过期才会更新成功（rowcount==1）。
    # 并发两次消费时，仅第一次 UPDATE 命中 used=0，第二次影响 0 行 → 恰好消费一次。
    now_iso = datetime.now().isoformat()
    conn = get_db_connection()
    cur = conn.execute(
        """
        UPDATE email_verification_codes
        SET used = 1
        WHERE email = ? AND purpose = ? AND used = 0 AND code = ?
          AND expires_at > ?
        """,
        (normalized_email, purpose, code, now_iso),
    )
    conn.commit()
    if cur.rowcount == 1:
        # 校验通过并成功消费：清掉该邮箱的失败计数
        _reset_failure_count(normalized_email, purpose)
        return True

    # 校验失败（错误码/已用/过期）：累加失败计数
    _record_failure(normalized_email, purpose, _get_failure_count(normalized_email, purpose) + 1)
    return False