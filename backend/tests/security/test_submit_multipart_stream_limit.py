"""The upload route must reject oversized multipart files while they are parsed."""

from __future__ import annotations

from fastapi import HTTPException
from starlette.datastructures import Headers

from app.core.multipart_limits import (
    BoundedMultiPartParser,
    UploadLimits,
    active_upload_limits,
)


async def test_oversized_multipart_stops_before_full_file_and_closes_spool(monkeypatch):
    monkeypatch.setenv("AC022_E2E_AUDIT", "1")
    boundary = b"ac022-boundary"
    limit = 2 * 1024 * 1024
    file_content = b"x" * (3 * 1024 * 1024 + 1)
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="files"; filename="oversized.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
        + file_content
        + b"\r\n--" + boundary + b"--\r\n"
    )
    received_bytes = 0

    async def chunks():
        nonlocal received_bytes
        for start in range(0, len(body), 64 * 1024):
            chunk = body[start : start + 64 * 1024]
            received_bytes += len(chunk)
            yield chunk

    headers = Headers(
        {
            "content-type": f"multipart/form-data; boundary={boundary.decode()}",
            "content-length": str(len(body)),
        }
    )
    token = active_upload_limits.set(UploadLimits(max_file_bytes=limit, max_total_bytes=4 * 1024 * 1024))
    try:
        parser = BoundedMultiPartParser(headers, chunks(), max_files=20, max_fields=100)
        try:
            await parser.parse()
        except HTTPException as exc:
            rejection = exc
        else:
            raise AssertionError("oversized file unexpectedly parsed")
    finally:
        active_upload_limits.reset(token)

    assert rejection.status_code == 413
    assert rejection.detail == "图片 oversized.png 超过大小限制（最大 2MB）"
    assert rejection.headers["X-AC022-Limit-Bytes"] == str(limit)
    observed = int(rejection.headers["X-AC022-File-Bytes-Observed"])
    buffered = int(rejection.headers["X-AC022-File-Bytes-Buffered"])
    assert limit < observed < len(file_content)
    assert buffered <= limit
    assert buffered < observed
    assert rejection.headers["X-AC022-Parser-Spool-Rolled"] == "true"
    assert rejection.headers["X-AC022-Parser-Spool-Closed"] == "true"
    assert rejection.headers["X-AC022-Endpoint-File-Read-Bytes"] == "0"
    assert received_bytes < len(body)
