"""Answer worker provider failures keep the upload error actionable."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Error code: 500 - internal provider error", "UPSTREAM_UNAVAILABLE"),
        ("Error code: 502 - bad gateway", "UPSTREAM_UNAVAILABLE"),
        ("Error code: 503 - service unavailable", "UPSTREAM_UNAVAILABLE"),
        ("Error code: 504 - gateway timeout", "UPSTREAM_TIMEOUT"),
    ],
)
def test_provider_server_errors_normalize_to_retryable_upstream_error(message, expected):
    from app.worker import _normalize_error_code

    assert _normalize_error_code(message) == expected
