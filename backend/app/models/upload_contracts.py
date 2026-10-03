"""上传/发布契约 DTO（严格模型）。

两类用途：

1. **根任务快照**（``UploadSnapshot``）：任务中心与 SSE 的唯一对外协议；未知字段一律拒绝，
   防止私人原文、Key 或内部字段被顺手序列化出去。
2. **审核投影请求**（``ReviewProjectionRequest``）：管理员审核的严格 allow-list；
   company/round/source_url 默认不公开，只有显式确认值才公开，null 表示删除公开字段。

字段名与主 spec 的 contracts.md §3.1 / §4.2 对齐。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UploadStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    NEEDS_ACTION = "needs_action"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    COMPLETED = "completed"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED_FOR_PROCESSING = "approved_for_processing"
    QUEUED = "queued"
    PROCESSING = "processing"
    PUBLISHED = "published"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"


class ErrorCode(str, Enum):
    MODEL_AUTH_INVALID = "MODEL_AUTH_INVALID"
    MODEL_CONFIG_MISSING = "MODEL_CONFIG_MISSING"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    SOURCE_DELETED = "SOURCE_DELETED"
    SOURCE_EXPIRED = "SOURCE_EXPIRED"
    POSITION_RETIRED = "POSITION_RETIRED"
    TAXONOMY_CHANGED = "TAXONOMY_CHANGED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    UPSTREAM_RATE_LIMIT = "UPSTREAM_RATE_LIMIT"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    STATE_CONFLICT = "STATE_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    LEGACY_MAPPING_AMBIGUOUS = "LEGACY_MAPPING_AMBIGUOUS"
    PIPELINE_VERSION_UNSUPPORTED = "PIPELINE_VERSION_UNSUPPORTED"
    INVALID_TARGET = "INVALID_TARGET"
    INVALID_INPUT = "INVALID_INPUT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 契约 §4.4：不是所有错误都值得自动重试。
RETRYABLE_ERROR_CODES = frozenset(
    {
        ErrorCode.UPSTREAM_RATE_LIMIT,
        ErrorCode.UPSTREAM_TIMEOUT,
        ErrorCode.UPSTREAM_UNAVAILABLE,
        ErrorCode.MODEL_OUTPUT_INVALID,
        ErrorCode.INTERNAL_ERROR,
    }
)

# 审核投影 allow-list：来源字段按源类型区分，未列出的字段一律 422。
REVIEW_SOURCE_ALLOWED_FIELDS: dict[str, set[str]] = {
    "interview": {
        "company",
        "round",
        "focus",
        "difficulty",
        "season",
        "source_url",
    },
    "jd": {
        "company",
        "job_title",
        "tech_stack",
        "bonus",
        "position",
        "salary",
        "source_url",
    },
}

REVIEW_ITEM_ALLOWED_FIELDS: dict[str, set[str]] = {
    "interview": {"question", "cat1", "cat2", "tags", "difficulty"},
    "jd": set(),
}

_INTERVIEW_SOURCE_KEYS = ("company", "round", "focus", "difficulty", "season", "source_url")
_JD_SOURCE_KEYS = (
    "company",
    "job_title",
    "tech_stack",
    "bonus",
    "position",
    "salary",
    "source_url",
)


class ReviewFieldError(ValueError):
    """审核字段不在 allow-list 内，或字段值本身不合法。"""

    code = "INVALID_INPUT"

    def __init__(self, message: str, *, field_name: str | None = None):
        self.field_name = field_name
        super().__init__(message)


def _normalize_text(value: Any) -> str | None:
    """空串/纯空白规范化为 None（null 表示不公开，不能回落原始值）。"""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ReviewFieldError("source_url 只允许经过校验的 http(s) 链接", field_name="source_url")
    return value


class UploadErrorDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    retryable: bool
    action: str | None = None
    scope: str | None = None


class UploadProgressDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str = "questions"
    completed: int = 0
    total: int | None = None


class UploadCountsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extracted: int = 0
    retained: int = 0
    excluded: int = 0
    needs_review: int = 0
    resolved: int = 0
    answered: int = 0
    failed: int = 0
    total: int | None = None


class UploadResultDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interview_id: int | None = None
    position_id: int | None = None
    question_ids: list[int] = Field(default_factory=list)
    contribution_request_id: int | None = None


class UploadSnapshot(BaseModel):
    """根任务快照；SSE 的 ``snapshot`` 事件数据即此模型。"""

    model_config = ConfigDict(extra="forbid")

    import_id: str
    revision: int = Field(ge=0)
    status: UploadStatus
    target_intent: str = "private"
    attempt_no: int = 0
    review_status: ReviewStatus | None = None
    stage: str | None = None
    progress: UploadProgressDTO | None = None
    counts: UploadCountsDTO | None = None
    result: UploadResultDTO | None = None
    error: UploadErrorDTO | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    recovery_available: bool = True
    recovery_message: str | None = None
    updated_at: str | None = None


class ReviewSourceFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = None
    round: str | None = None
    focus: str | None = None
    difficulty: str | None = None
    season: str | None = None
    source_url: str | None = None
    job_title: str | None = None
    tech_stack: str | None = None
    bonus: str | None = None
    position: str | None = None
    salary: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        return _normalize_text(value)

    @field_validator("source_url")
    @classmethod
    def _check_url(cls, value):
        return _validate_source_url(value)


class ReviewItemFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    question: str | None = None
    cat1: str | None = None
    cat2: str | None = None
    tags: Any | None = None
    difficulty: str | None = None

    @field_validator("question", "cat1", "cat2", "difficulty", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        return _normalize_text(value)


class ReviewFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: ReviewSourceFields = Field(default_factory=ReviewSourceFields)
    items: list[ReviewItemFields] = Field(default_factory=list)


class ReviewProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    excluded_item_ids: list[int] = Field(default_factory=list)
    review_fields: ReviewFields = Field(default_factory=ReviewFields)


def _check_allowed_keys(mapping: Mapping, allowed: set[str], where: str) -> None:
    unknown = [key for key in mapping if key not in allowed]
    if unknown:
        raise ReviewFieldError(
            f"{where} 出现不允许的字段: {', '.join(sorted(str(k) for k in unknown))}",
            field_name=where,
        )


def build_review_projection_request(
    payload: Mapping[str, Any] | None, *, source_type: str = "interview"
) -> ReviewProjectionRequest:
    """把审核请求体解析成严格投影模型；未知字段一律拒绝。

    投影里的 ``null`` 表示“删除该公开字段”，调用方不得回落到原始 snapshot。
    """

    if source_type not in REVIEW_SOURCE_ALLOWED_FIELDS:
        raise ReviewFieldError(f"不支持的 source_type: {source_type!r}", field_name="source_type")

    data = dict(payload or {})
    review_fields = data.get("review_fields") or {}
    if not isinstance(review_fields, Mapping):
        raise ReviewFieldError("review_fields 必须是对象", field_name="review_fields")

    source = review_fields.get("source") or {}
    if not isinstance(source, Mapping):
        raise ReviewFieldError("review_fields.source 必须是对象", field_name="source")
    _check_allowed_keys(source, REVIEW_SOURCE_ALLOWED_FIELDS[source_type], "review_fields.source")
    _check_allowed_keys(review_fields, {"source", "items"}, "review_fields")

    items = review_fields.get("items") or []
    if not isinstance(items, list):
        raise ReviewFieldError("review_fields.items 必须是数组", field_name="items")
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ReviewFieldError("review_fields.items 每项必须是对象", field_name="items")
        _check_allowed_keys(
            item,
            REVIEW_ITEM_ALLOWED_FIELDS[source_type] | {"item_id"},
            f"review_fields.items[{index}]",
        )

    return ReviewProjectionRequest.model_validate(data)
