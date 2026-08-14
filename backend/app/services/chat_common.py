"""chat_service 共享基础件.

从 chat_service.py 机械抽取的共享原始块(行为不变):
- 异常类型(会话/回合/副作用乐观锁)
- ChatTurn dataclass 与行转换
- JSON 安全解析
- 刷盘阈值常量

把这些抽到独立模块后,chat_service.py 及各子模块从本模块 import,避免循环依赖。
"""
import json
import hashlib
from dataclasses import dataclass
from typing import Optional


class ConversationNotFound(LookupError):
    """The conversation is missing or does not belong to the caller."""


class ConversationNotWritable(RuntimeError):
    """The conversation exists but is no longer active."""


class TurnInProgress(RuntimeError):
    """Another request already owns the conversation's active turn."""


class TurnCancelled(RuntimeError):
    """The turn fence is no longer valid for persistence."""


class TurnNotFound(LookupError):
    """The turn is missing or does not belong to the caller."""


class TurnIdempotencyConflict(RuntimeError):
    """A request id was reused with a different logical request."""

    def __init__(self, turn_id: str, status: str):
        super().__init__("client request id was reused with a different payload")
        self.turn_id = turn_id
        self.status = status


class TurnUserMessageConflict(RuntimeError):
    """A pre-created user message cannot be claimed by this turn."""


class SideEffectConflict(RuntimeError):
    """An optimistic-concurrency update lost its expected version."""

    def __init__(self, resource: str, current_version: int | None = None):
        super().__init__(f"{resource} version conflict")
        self.resource = resource
        self.current_version = current_version


SIDE_EFFECT_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class ChatTurn:
    id: str
    conversation_id: str
    user_id: int
    client_request_id: str
    fence: int
    status: str
    user_message_id: Optional[int] = None
    assistant_message_id: Optional[int] = None
    request_fingerprint: str = ""
    revision_of_message_id: Optional[int] = None
    created: bool = True


def _chat_turn_from_row(row, *, created: bool = True) -> ChatTurn:
    return ChatTurn(
        id=row["id"],
        conversation_id=row["conversation_id"],
        user_id=int(row["user_id"]),
        client_request_id=row["client_request_id"],
        fence=int(row["fence"]),
        status=row["status"],
        user_message_id=row["user_message_id"],
        assistant_message_id=row["assistant_message_id"],
        request_fingerprint=row["request_fingerprint"] or "",
        revision_of_message_id=row["revision_of_message_id"],
        created=created,
    )


def _safe_json_loads(raw) -> dict:
    """安全解析 JSON 字符串，解析失败返回空字典"""
    if not raw or not str(raw).strip():
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def build_turn_request_fingerprint(
    content: str,
    model: str | None = None,
    revision_of_message_id: int | None = None,
) -> str:
    """Build a stable identity for one logical turn request."""
    payload = {
        "content": str(content or "").strip(),
        "model": str(model or ""),
        "revision_of_message_id": revision_of_message_id,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# 刷盘触发阈值
FLUSH_UTILIZATION_THRESHOLD = 80.0
