"""本链路严格凭据解析与调用账本（UR-004 / AC-004、AC-013）。

契约（contracts.md §1.7、§2.2）：

- ``credential_scope`` 只有 ``user`` / ``global``；``payer_type`` 只有 ``user`` / ``system``。
- user scope 只读本人配置：缺失或解密失败一律 ``MODEL_CONFIG_MISSING``，
  **绝不静默回退系统配置**；global scope 反之亦然，不借用任何用户私钥。
- 解析结果只暴露 ``config_fingerprint``（不可逆指纹），绝不序列化 Key。
- 调用账本与配额预留在**同一个外层事务**里写入；本模块内部不 commit。
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field

logger = logging.getLogger("interview-boss")

CREDENTIAL_SCOPES = ("user", "global")
PAYER_TYPES = ("user", "system")

CALL_STATUSES = ("reserved", "succeeded", "failed", "unknown")


class UploadCredentialError(Exception):
    """凭据/预算阻塞；带 code/scope/action，供根任务 needs_action 投影使用。"""

    def __init__(
        self,
        code: str,
        *,
        scope: str,
        action: str | None = None,
        message: str = "",
        retryable: bool = False,
    ):
        self.code = code
        self.scope = scope
        self.action = action
        self.retryable = retryable
        super().__init__(message or code)


class CallLedgerConflict(Exception):
    """同一个物理调用被重复记账（call_key 冲突）。"""

    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, call_key: str):
        self.call_key = call_key
        super().__init__(f"call_key 已存在: {call_key}")


@dataclass(frozen=True)
class ResolvedCredential:
    """一次调用可用的凭据视图；``api_key`` 不进入 repr/model_dump。"""

    scope: str
    payer_type: str
    payer_user_id: int | None
    model: str
    base_url: str
    provider: str
    config_fingerprint: str
    timeout: int = 60
    api_format: str | None = None
    api_key: str = field(default="", repr=False, compare=False)

    def model_dump(self) -> dict:
        return {
            "scope": self.scope,
            "payer_type": self.payer_type,
            "payer_user_id": self.payer_user_id,
            "model": self.model,
            "base_url": self.base_url,
            "provider": self.provider,
            "config_fingerprint": self.config_fingerprint,
        }


def _default_user_loader(user_id: int):
    from app.core.config import get_user_llm_config

    return get_user_llm_config(user_id)


def _default_global_loader():
    from app.core.config import _get_global_llm_config

    return _get_global_llm_config()


def _fingerprint(cfg: dict, provider: str) -> str:
    material = "|".join(
        str(cfg.get(key) or "") for key in ("api_key", "base_url", "model", "api_format")
    )
    return hashlib.sha256(f"{provider}|{material}".encode()).hexdigest()[:32]


def resolve_upload_credentials(
    *,
    credential_scope: str,
    user_id: int | None,
    stage: str,
    unit_key: str | None = None,
    user_config_loader=None,
    global_config_loader=None,
) -> ResolvedCredential:
    """解析本次调用的凭据；任何缺失/异常都显式失败，不跨 scope 回退。"""

    if credential_scope not in CREDENTIAL_SCOPES:
        raise ValueError(f"不支持的 credential_scope: {credential_scope!r}")

    load_user = user_config_loader or _default_user_loader
    load_global = global_config_loader or _default_global_loader

    if credential_scope == "user":
        if not user_id:
            raise ValueError("user scope 必须提供 user_id")
        try:
            cfg = load_user(user_id)
        except Exception:  # 解密/读取失败同样按缺失处理，禁止回退
            logger.warning("个人模型配置读取失败: user_id=%s stage=%s", user_id, stage)
            raise UploadCredentialError(
                "MODEL_CONFIG_MISSING",
                scope="user",
                action="configure_user_model",
                message="个人模型配置不可用，请重新配置后继续",
            ) from None
        if not cfg:
            raise UploadCredentialError(
                "MODEL_CONFIG_MISSING",
                scope="user",
                action="configure_user_model",
                message="请先配置个人模型后继续",
            )
        payer_type, payer_user_id = "user", int(user_id)
    else:
        try:
            cfg = load_global()
        except Exception:
            logger.warning("系统模型配置读取失败: stage=%s", stage)
            raise UploadCredentialError(
                "MODEL_CONFIG_MISSING",
                scope="global",
                action="configure_system_model",
                message="系统模型配置不可用，请管理员配置后继续",
            ) from None
        if not cfg:
            raise UploadCredentialError(
                "MODEL_CONFIG_MISSING",
                scope="global",
                action="configure_system_model",
                message="系统尚未配置模型，请管理员配置后继续",
            )
        payer_type, payer_user_id = "system", None

    api_key = str(cfg.get("api_key") or "")
    base_url = str(cfg.get("base_url") or "")
    model = str(cfg.get("model") or "")
    if not api_key or not base_url or not model:
        raise UploadCredentialError(
            "MODEL_CONFIG_MISSING",
            scope=credential_scope,
            action=(
                "configure_user_model" if credential_scope == "user" else "configure_system_model"
            ),
            message="模型配置不完整，请补充后继续",
        )

    provider = str(cfg.get("provider") or cfg.get("api_format") or "openai")
    return ResolvedCredential(
        scope=credential_scope,
        payer_type=payer_type,
        payer_user_id=payer_user_id,
        model=model,
        base_url=base_url,
        provider=provider,
        config_fingerprint=_fingerprint(cfg, provider),
        timeout=int(cfg.get("timeout") or 60),
        api_format=cfg.get("api_format"),
        api_key=api_key,
    )


def reserve_llm_call(
    conn,
    *,
    root_import_id: str | None,
    stage: str,
    unit_key: str = "",
    call_key: str,
    credential_scope: str,
    payer_type: str,
    payer_user_id: int | None = None,
    provider: str | None = None,
    model: str | None = None,
    config_fingerprint: str | None = None,
    daily_limit: int | None = None,
    day: str | None = None,
    tokens: int = 0,
):
    """在调用方事务内登记一次物理外部尝试，并原子预留配额。

    同一 ``call_key`` 只能登记一次；配额不足抛 ``QUOTA_EXCEEDED``，不写账本。
    """

    if credential_scope not in CREDENTIAL_SCOPES:
        raise ValueError(f"不支持的 credential_scope: {credential_scope!r}")
    if payer_type not in PAYER_TYPES:
        raise ValueError(f"不支持的 payer_type: {payer_type!r}")
    if payer_type == "user" and not payer_user_id:
        raise ValueError("payer_type=user 必须提供 payer_user_id")

    if payer_type == "user":
        from app.services import llm_quota

        allowed = llm_quota.reserve_call(
            conn,
            user_id=int(payer_user_id),
            day=day or llm_quota._today(),
            tokens=tokens,
            limit=daily_limit,
        )
        if not allowed:
            raise UploadCredentialError(
                "QUOTA_EXCEEDED",
                scope=credential_scope,
                action="wait_for_daily_reset",
                message="今日模型调用额度已用完，明日可继续或调整预算",
            )

    try:
        cursor = conn.execute(
            "INSERT INTO upload_llm_calls ("
            "  root_import_id, stage, unit_key, call_key, credential_scope, "
            "  payer_type, payer_user_id, provider, model, config_fingerprint, status"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,'reserved')",
            (
                root_import_id,
                stage,
                unit_key,
                call_key,
                credential_scope,
                payer_type,
                payer_user_id,
                provider,
                model,
                config_fingerprint,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise CallLedgerConflict(call_key) from exc

    return conn.execute(
        "SELECT * FROM upload_llm_calls WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()


def complete_llm_call(
    conn,
    *,
    call_key: str,
    status: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_code: str | None = None,
):
    """结束一次记账；``unknown`` 表示外部请求已发出但响应丢失（不退还额度）。"""

    if status not in CALL_STATUSES:
        raise ValueError(f"不支持的 call 状态: {status!r}")
    cursor = conn.execute(
        "UPDATE upload_llm_calls SET status = ?, input_tokens = ?, output_tokens = ?, "
        "error_code = ?, finished_at = CURRENT_TIMESTAMP WHERE call_key = ?",
        (status, input_tokens, output_tokens, error_code, call_key),
    )
    if cursor.rowcount != 1:
        raise CallLedgerConflict(call_key)
    return conn.execute("SELECT * FROM upload_llm_calls WHERE call_key = ?", (call_key,)).fetchone()
