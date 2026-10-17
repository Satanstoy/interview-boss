"""Answer worker provider failures keep the upload error actionable."""

from __future__ import annotations

import pytest
from types import SimpleNamespace


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Error code: 401 - invalid api key", "MODEL_AUTH_INVALID"),
        ("Error code: 403 - forbidden", "PERMISSION_REVOKED"),
        ("Error code: 429 - rate limit", "UPSTREAM_RATE_LIMIT"),
        ("Error code: 500 - internal provider error", "UPSTREAM_UNAVAILABLE"),
        ("Error code: 502 - bad gateway", "UPSTREAM_UNAVAILABLE"),
        ("Error code: 503 - service unavailable", "UPSTREAM_UNAVAILABLE"),
        ("Error code: 504 - gateway timeout", "UPSTREAM_TIMEOUT"),
    ],
)
def test_provider_server_errors_normalize_to_retryable_upstream_error(message, expected):
    from app.worker import _normalize_error_code

    assert _normalize_error_code(message) == expected


def test_structured_schema_error_keeps_its_contract_code():
    from app.services.extraction_integrity import ExtractionSchemaError
    from app.worker import _normalize_error_code

    error = ExtractionSchemaError("private question details must not replace the error code")
    assert _normalize_error_code(error) == "MODEL_OUTPUT_INVALID"


def test_tenacity_retry_wrapper_keeps_the_final_provider_status_code():
    from app.services.upload_retry_budget import normalize_upload_error_code

    provider_error = SimpleNamespace(status_code=429)
    retry_error = SimpleNamespace(
        last_attempt=SimpleNamespace(exception=lambda: provider_error)
    )

    assert normalize_upload_error_code(retry_error) == "UPSTREAM_RATE_LIMIT"


def test_graph_error_message_does_not_expose_raw_exception_text():
    from app.agents.submit.graph import _sanitize_error
    from app.services.extraction_integrity import ExtractionSchemaError

    private_marker = "AC013_PRIVATE_QUESTION_SENTINEL"
    error = ExtractionSchemaError(f"ordinal is invalid: {private_marker}")

    assert private_marker not in _sanitize_error(error)


def test_snapshot_action_matches_the_task_center_action_after_retry_budget_is_exhausted():
    from app.routers.upload_imports import _error_dto
    from app.services.upload_status import allowed_actions

    error = _error_dto(
        "UPSTREAM_RATE_LIMIT",
        "模型服务繁忙，请稍后重试。",
        status="failed",
    )
    actions = allowed_actions("failed", error_code="UPSTREAM_RATE_LIMIT")

    assert error["retryable"] is True
    assert error["action"] == "retry"
    assert error["action"] in actions


def test_permission_error_action_is_represented_in_allowed_actions():
    from app.routers.upload_imports import _error_dto
    from app.services.upload_status import allowed_actions

    error = _error_dto(
        "PERMISSION_REVOKED",
        "当前模型凭据无权访问此服务。",
        status="needs_action",
    )
    actions = allowed_actions("needs_action", error_code="PERMISSION_REVOKED")

    assert error["action"] == "check_permission"
    assert error["action"] in actions
