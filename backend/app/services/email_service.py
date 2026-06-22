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


def _store_code(email: str, code: str, purpose: str, ttl_seconds: int = 300):
    """存储验证码到 SQLite，确保多 worker 进程共享。"""
    normalized_email = _normalize_email(email)
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


def _mark_code_used(email: str, purpose: str):
    """标记验证码已使用"""
    normalized_email = _normalize_email(email)
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE email_verification_codes
        SET used = 1
        WHERE id = (
            SELECT id FROM email_verification_codes
            WHERE email = ? AND purpose = ? AND used = 0
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        )
        """,
        (normalized_email, purpose)
    )
    conn.commit()


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
    stored = _get_stored_code(email, purpose)
    if not stored:
        return False

    # 检查是否已使用
    if stored["used"]:
        return False

    # 检查是否过期
    if datetime.now() > stored["expires_at"]:
        return False

    # 检查验证码
    if stored["code"] != code:
        return False

    # 标记已使用
    _mark_code_used(email, purpose)
    return True
