"""UR-003：上传提交策略解析（纯函数，无 DB、无模型调用）。

职责：把“服务端已认证的主体事实 + 用户明确选择的意图”解析成一次可持久化的策略：

- ``write_scope``：这次写入落在私人库还是公共库
- ``owner_id``：写入归属（公共为 None）
- ``credential_scope`` / ``payer``：谁来付这次模型调用
- ``request_public_review`` / ``public_review_required``：是否必须先过管理员审核

边界（对应主 spec §3）：

- 普通用户 share＝先私人保存 + 待审快照，审核前用本人凭据；批准后才切 global。
- 管理员 share＝显式公共导入，从提取开始就用 global，但必须留审批审计。
- 管理员 private 与普通用户 private 完全一致（管理员身份不隐式改归属或付费方）。
- 客户端传入的 is_admin/owner_id/credential_scope 等策略字段一律拒绝，不静默忽略。
"""

from __future__ import annotations

from dataclasses import dataclass, field

UPLOAD_PIPELINE_VERSION_V1 = "upload-pipeline-v1"

TARGET_INTENTS = ("private", "share")
SOURCE_TYPES = ("interview", "jd", "auto")
ENTRIES = ("api", "legacy_sse")

# 只能由服务端计算的字段；客户端提交即 400，避免“前端说自己是管理员”。
CLIENT_FORBIDDEN_POLICY_FIELDS = frozenset(
    {
        "actor_id",
        "is_admin",
        "owner_id",
        "credential_scope",
        "llm_scope",
        "payer_type",
        "payer_user_id",
        "write_scope",
        "requester_id",
        "request_public_review",
        "public_review_required",
        "post_approval_credential_scope",
        "audit_public_import",
        "policy_json",
    }
)


class ClientPolicyFieldError(ValueError):
    """客户端试图提交服务端策略字段。"""

    code = "INVALID_TARGET"

    def __init__(self, fields: list[str]):
        self.fields = sorted(fields)
        super().__init__(f"不允许客户端提交策略字段: {', '.join(self.fields)}")


class InvalidTargetError(ValueError):
    """target 不是受支持的枚举值；必须 400，不能静默改成 private。"""

    code = "INVALID_TARGET"

    def __init__(self, target):
        self.target = target
        super().__init__(f"不支持的提交目标: {target!r}")


def sanitize_client_policy_fields(fields: dict | None) -> dict:
    """校验请求体里没有任何策略字段；返回服务端策略覆盖项（恒为空）。"""

    if not fields:
        return {}
    forged = [key for key in fields if str(key).lower() in CLIENT_FORBIDDEN_POLICY_FIELDS]
    if forged:
        raise ClientPolicyFieldError(forged)
    return {}


@dataclass(frozen=True)
class UploadPolicy:
    """一次上传的完整服务端策略快照（可序列化进 policy_json）。"""

    requester_id: int
    target_intent: str
    write_scope: str
    owner_id: int | None
    credential_scope: str
    payer_type: str
    payer_user_id: int | None
    request_public_review: bool
    public_review_required: bool
    post_approval_credential_scope: str | None
    audit_public_import: bool
    source_type: str
    position_id: int | None
    position_name: str
    entry: str = "api"
    input_version: int = 1
    pipeline_version: str = UPLOAD_PIPELINE_VERSION_V1
    policy_version: int = 1
    extra: dict = field(default_factory=dict)

    @property
    def is_question_pipeline(self) -> bool:
        """JD 走同一任务外壳但没有题目 resolution/聚类阶段。"""

        return self.source_type != "jd"

    def to_policy_json(self) -> dict:
        """策略的持久化形式；不含任何 Key、认证头或原文。"""

        return {
            "policy_version": self.policy_version,
            "pipeline_version": self.pipeline_version,
            "input_version": self.input_version,
            "requester_id": self.requester_id,
            "target_intent": self.target_intent,
            "write_scope": self.write_scope,
            "owner_id": self.owner_id,
            "credential_scope": self.credential_scope,
            "payer": {"type": self.payer_type, "user_id": self.payer_user_id},
            "request_public_review": self.request_public_review,
            "public_review_required": self.public_review_required,
            "post_approval_credential_scope": self.post_approval_credential_scope,
            "audit_public_import": self.audit_public_import,
            "source_type": self.source_type,
            "position": {"id": self.position_id, "name": self.position_name},
            "entry": self.entry,
            "extra": dict(self.extra),
        }


def resolve_upload_policy(
    *,
    actor_id: int | None,
    actor_is_admin: bool,
    target_intent: str,
    source_type: str = "interview",
    position_id: int | None = None,
    position_name: str = "",
    entry: str = "api",
    input_version: int = 1,
    extra: dict | None = None,
) -> UploadPolicy:
    """把四格策略规则解析成不可变策略对象。

    只信任 ``actor_id`` / ``actor_is_admin``（来自服务端认证依赖），
    其余参数是用户意图与服务端快照，不接受请求体里的策略字段。
    """

    if actor_id is None or not isinstance(actor_id, int) or actor_id <= 0:
        raise ValueError("actor_id 必须来自服务端认证主体")

    if entry not in ENTRIES:
        raise ValueError(f"不支持的入口: {entry!r}")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"不支持的 source_type: {source_type!r}")
    if input_version < 1:
        raise ValueError("input_version 必须 >= 1")
    if isinstance(target_intent, str) and target_intent in TARGET_INTENTS:
        normalized_target = target_intent
    else:
        raise InvalidTargetError(target_intent)

    is_share = normalized_target == "share"
    if not is_share:
        # 私人：管理员与普通用户完全同规则
        return UploadPolicy(
            requester_id=actor_id,
            target_intent="private",
            write_scope="private",
            owner_id=actor_id,
            credential_scope="user",
            payer_type="user",
            payer_user_id=actor_id,
            request_public_review=False,
            public_review_required=False,
            post_approval_credential_scope=None,
            audit_public_import=False,
            source_type=source_type,
            position_id=position_id,
            position_name=position_name,
            entry=entry,
            input_version=input_version,
            extra=dict(extra or {}),
        )

    if actor_is_admin:
        # 显式公共导入：视为已记录的审批，从提取开始用 global，不假装成私人消费
        return UploadPolicy(
            requester_id=actor_id,
            target_intent="share",
            write_scope="public",
            owner_id=None,
            credential_scope="global",
            payer_type="system",
            payer_user_id=None,
            request_public_review=False,
            public_review_required=False,
            post_approval_credential_scope=None,
            audit_public_import=True,
            source_type=source_type,
            position_id=position_id,
            position_name=position_name,
            entry=entry,
            input_version=input_version,
            extra=dict(extra or {}),
        )

    # 普通用户 share：先私人保存 + 待审快照；批准后才用 global 处理公共内容
    return UploadPolicy(
        requester_id=actor_id,
        target_intent="share",
        write_scope="private",
        owner_id=actor_id,
        credential_scope="user",
        payer_type="user",
        payer_user_id=actor_id,
        request_public_review=True,
        public_review_required=True,
        post_approval_credential_scope="global",
        audit_public_import=False,
        source_type=source_type,
        position_id=position_id,
        position_name=position_name,
        entry=entry,
        input_version=input_version,
        extra=dict(extra or {}),
    )
