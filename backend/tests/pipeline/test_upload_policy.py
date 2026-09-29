"""UR-003 / AC-003：四格提交策略与严格 DTO。

四格 = {普通用户 U1, 管理员 A} × {private, share}；两个入口 = 新任务接口 api 与旧 SSE 适配器。
policy 是纯函数：只接受服务端已认证的主体事实，不读取请求体里声称的 is_admin/owner_id/credential_scope。
"""

from __future__ import annotations

import pytest

from app.models.upload_contracts import (
    REVIEW_SOURCE_ALLOWED_FIELDS,
    ErrorCode,
    ReviewFieldError,
    ReviewProjectionRequest,
    UploadErrorDTO,
    UploadSnapshot,
    UploadStatus,
    build_review_projection_request,
)
from app.services.upload_policy import (
    ClientPolicyFieldError,
    InvalidTargetError,
    UPLOAD_PIPELINE_VERSION_V1,
    UploadPolicy,
    resolve_upload_policy,
    sanitize_client_policy_fields,
)

ENTRIES = ("api", "legacy_sse")

# ── 四格期望表 ────────────────────────────────────────────────


def _resolve(actor_id, actor_is_admin, target_intent, entry, **overrides):
    kwargs = dict(
        actor_id=actor_id,
        actor_is_admin=actor_is_admin,
        target_intent=target_intent,
        source_type="interview",
        position_id=7,
        position_name="后端",
        entry=entry,
    )
    kwargs.update(overrides)
    return resolve_upload_policy(**kwargs)


@pytest.mark.parametrize("entry", ENTRIES)
def test_user_private_uses_personal_scope(entry):
    policy = _resolve(101, False, "private", entry)
    assert policy.requester_id == 101
    assert policy.write_scope == "private"
    assert policy.owner_id == 101
    assert policy.credential_scope == "user"
    assert policy.payer_type == "user"
    assert policy.payer_user_id == 101
    assert policy.request_public_review is False
    assert policy.public_review_required is False
    assert policy.post_approval_credential_scope is None
    assert policy.source_type == "interview"
    assert policy.position_id == 7 and policy.position_name == "后端"


@pytest.mark.parametrize("entry", ENTRIES)
def test_user_share_saves_private_then_requests_review(entry):
    policy = _resolve(101, False, "share", entry)
    # 审核前：私人保存 + 待审快照，凭据仍是本人
    assert policy.write_scope == "private"
    assert policy.owner_id == 101
    assert policy.credential_scope == "user"
    assert policy.payer_type == "user"
    assert policy.payer_user_id == 101
    assert policy.request_public_review is True
    assert policy.public_review_required is True
    # 批准后才切公共处理凭据，且必须是显式的
    assert policy.post_approval_credential_scope == "global"
    assert policy.audit_public_import is False


@pytest.mark.parametrize("entry", ENTRIES)
def test_admin_private_is_not_special(entry):
    policy = _resolve(201, True, "private", entry)
    assert policy.requester_id == 201
    assert policy.write_scope == "private"
    assert policy.owner_id == 201
    assert policy.credential_scope == "user"
    assert policy.payer_type == "user"
    assert policy.payer_user_id == 201
    assert policy.request_public_review is False
    assert policy.public_review_required is False


@pytest.mark.parametrize("entry", ENTRIES)
def test_admin_share_is_public_with_system_credential(entry):
    policy = _resolve(201, True, "share", entry)
    assert policy.write_scope == "public"
    assert policy.owner_id is None
    assert policy.credential_scope == "global"
    assert policy.payer_type == "system"
    assert policy.payer_user_id is None
    # 管理员显式公共导入不经过审核闸门，但必须留下审批审计
    assert policy.public_review_required is False
    assert policy.request_public_review is False
    assert policy.audit_public_import is True
    assert policy.post_approval_credential_scope is None


def test_entry_does_not_change_policy_outcome():
    api = _resolve(101, False, "share", "api")
    legacy = _resolve(101, False, "share", "legacy_sse")
    api_json = {k: v for k, v in api.to_policy_json().items() if k != "entry"}
    legacy_json = {k: v for k, v in legacy.to_policy_json().items() if k != "entry"}
    assert api_json == legacy_json
    assert api.entry == "api" and legacy.entry == "legacy_sse"


def test_jd_source_type_is_recorded_without_question_stages():
    policy = _resolve(101, False, "private", "api", source_type="jd")
    assert policy.source_type == "jd"
    assert policy.is_question_pipeline is False


@pytest.mark.parametrize("bad_target", ["public", "invalid", "", "Share", "PRIVATE"])
def test_invalid_target_is_rejected_not_coerced(bad_target):
    with pytest.raises(InvalidTargetError) as exc:
        _resolve(101, False, bad_target, "api")
    assert exc.value.code == "INVALID_TARGET"


@pytest.mark.parametrize("entry", ENTRIES)
def test_missing_actor_is_rejected(entry):
    with pytest.raises(ValueError):
        _resolve(None, False, "private", entry)


def test_admin_flag_comes_from_server_not_request():
    """客户端声称自己是管理员不改变策略：伪造字段必须被显式拒绝。"""
    for forged in (
        {"is_admin": 1},
        {"owner_id": 999},
        {"credential_scope": "global"},
        {"payer_type": "system"},
        {"write_scope": "public"},
    ):
        with pytest.raises(ClientPolicyFieldError):
            sanitize_client_policy_fields(forged)

    # 空请求体与普通表单字段不触发拒绝
    assert sanitize_client_policy_fields({"url": "https://example.com", "target": "share"}) == {}


def test_policy_is_immutable_and_versioned():
    policy = _resolve(101, False, "private", "api")
    assert policy.pipeline_version == UPLOAD_PIPELINE_VERSION_V1
    assert policy.input_version == 1
    with pytest.raises(Exception):
        policy.owner_id = 5  # type: ignore[misc]


def test_policy_json_is_serializable_and_has_no_secrets():
    policy = _resolve(201, True, "share", "api")
    payload = policy.to_policy_json()
    assert payload["credential_scope"] == "global"
    assert payload["payer"] == {"type": "system", "user_id": None}
    assert "key" not in json_keys(payload)
    assert "api_key" not in json_keys(payload)


def json_keys(value):
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys |= json_keys(item)
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys |= json_keys(item)
        return keys
    return set()


# ── 严格 DTO ─────────────────────────────────────────────────


def test_review_request_rejects_unknown_top_level_field():
    with pytest.raises(Exception):
        build_review_projection_request(
            {"expected_revision": 1, "surprise": True},
            source_type="interview",
        )


def test_review_request_rejects_unknown_source_field():
    with pytest.raises(ReviewFieldError):
        build_review_projection_request(
            {
                "expected_revision": 1,
                "review_fields": {"source": {"company": "某公司", "owner_id": 5}},
            },
            source_type="interview",
        )


def test_review_request_rejects_unknown_item_field():
    with pytest.raises(ReviewFieldError):
        build_review_projection_request(
            {
                "expected_revision": 1,
                "review_fields": {"items": [{"item_id": 11, "answer": "x"}]},
            },
            source_type="interview",
        )


def test_review_request_defaults_hide_identifying_source_fields():
    req = build_review_projection_request({"expected_revision": 3}, source_type="interview")
    assert req.expected_revision == 3
    assert req.review_fields.source.company is None
    assert req.review_fields.source.round is None
    assert req.review_fields.source.source_url is None
    assert req.excluded_item_ids == []


def test_review_request_normalizes_blank_strings_to_none():
    req = build_review_projection_request(
        {
            "expected_revision": 1,
            "review_fields": {
                "source": {"company": "", "round": "   ", "focus": "数据库"},
                "items": [{"item_id": 11, "question": "  "}],
            },
        },
        source_type="interview",
    )
    assert req.review_fields.source.company is None
    assert req.review_fields.source.round is None
    assert req.review_fields.source.focus == "数据库"
    assert req.review_fields.items[0].question is None


def test_review_allowlist_differs_for_jd():
    assert REVIEW_SOURCE_ALLOWED_FIELDS["interview"] >= {"company", "round", "source_url"}
    assert "tech_stack" in REVIEW_SOURCE_ALLOWED_FIELDS["jd"]
    with pytest.raises(ReviewFieldError):
        build_review_projection_request(
            {"expected_revision": 1, "review_fields": {"source": {"round": "一面"}}},
            source_type="jd",
        )


def test_review_source_url_must_be_http():
    with pytest.raises(Exception):
        build_review_projection_request(
            {
                "expected_revision": 1,
                "review_fields": {"source": {"source_url": "javascript:alert(1)"}},
            },
            source_type="interview",
        )


def test_snapshot_rejects_unknown_status_and_extra_fields():
    with pytest.raises(Exception):
        UploadSnapshot(import_id="i1", revision=1, status="totally_done")
    with pytest.raises(Exception):
        UploadSnapshot(import_id="i1", revision=1, status=UploadStatus.QUEUED, payload="secret")


def test_snapshot_round_trip_keeps_error_protocol():
    snap = UploadSnapshot(
        import_id="i1",
        revision=4,
        status=UploadStatus.NEEDS_ACTION,
        error=UploadErrorDTO(
            code=ErrorCode.MODEL_AUTH_INVALID,
            message="请更新个人模型配置后继续",
            retryable=False,
            action="configure_user_model",
            scope="user",
        ),
        allowed_actions=["configure_user_model", "retry_after_configuration"],
    )
    dumped = snap.model_dump(mode="json")
    assert dumped["status"] == "needs_action"
    assert dumped["error"]["code"] == "MODEL_AUTH_INVALID"
    assert dumped["error"]["retryable"] is False


def test_error_code_enum_rejects_unknown_code():
    with pytest.raises(Exception):
        UploadErrorDTO(code="SOMETHING_ELSE", message="x", retryable=False)
