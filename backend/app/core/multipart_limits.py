"""Bound upload file parsing before FastAPI materializes ``UploadFile`` values."""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette import requests as starlette_requests
from starlette.formparsers import MultiPartException, MultiPartParser


@dataclass(frozen=True)
class UploadLimits:
    max_file_bytes: int
    max_total_bytes: int


active_upload_limits: ContextVar[UploadLimits | None] = ContextVar(
    "active_upload_limits", default=None
)


class MultipartUploadTooLarge(MultiPartException):
    def __init__(self, *, message: str, limit_bytes: int, observed_bytes: int, file):
        super().__init__(message)
        self.limit_bytes = limit_bytes
        self.observed_bytes = observed_bytes
        self.upload_file = file


class BoundedMultiPartParser(MultiPartParser):
    """Stop consuming file-part data as soon as the active route limit is crossed."""

    def __init__(self, *args, **kwargs):
        self.upload_limits = active_upload_limits.get()
        self.current_file_bytes = 0
        self.total_file_bytes = 0
        super().__init__(*args, **kwargs)

    def on_part_begin(self) -> None:
        self.current_file_bytes = 0
        super().on_part_begin()

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        upload_file = self._current_part.file
        if self.upload_limits is not None and upload_file is not None:
            chunk_size = end - start
            next_file_size = self.current_file_bytes + chunk_size
            next_total_size = self.total_file_bytes + chunk_size
            if next_file_size > self.upload_limits.max_file_bytes:
                filename = upload_file.filename or "上传文件"
                max_mb = self.upload_limits.max_file_bytes // (1024 * 1024)
                raise MultipartUploadTooLarge(
                    message=f"图片 {filename} 超过大小限制（最大 {max_mb}MB）",
                    limit_bytes=self.upload_limits.max_file_bytes,
                    observed_bytes=next_file_size,
                    file=upload_file,
                )
            if next_total_size > self.upload_limits.max_total_bytes:
                max_mb = self.upload_limits.max_total_bytes // (1024 * 1024)
                raise MultipartUploadTooLarge(
                    message=f"上传文件总大小超过限制（最大 {max_mb}MB）",
                    limit_bytes=self.upload_limits.max_total_bytes,
                    observed_bytes=next_file_size,
                    file=upload_file,
                )
            self.current_file_bytes = next_file_size
            self.total_file_bytes = next_total_size
        super().on_part_data(data, start, end)

    async def parse(self):
        try:
            return await super().parse()
        except MultipartUploadTooLarge as exc:
            # MultiPartParser.parse has already closed every spool file before
            # re-raising. Keep byte counts in test-only headers so the real HTTP
            # scenario can verify early rejection and cleanup without exposing
            # upload internals in production responses.
            headers = None
            if os.getenv("AC022_E2E_AUDIT") == "1":
                spool = exc.upload_file.file
                headers = {
                    "X-AC022-Limit-Bytes": str(exc.limit_bytes),
                    "X-AC022-File-Bytes-Observed": str(exc.observed_bytes),
                    "X-AC022-File-Bytes-Buffered": str(exc.upload_file.size or 0),
                    "X-AC022-Parser-Spool-Rolled": str(
                        bool(getattr(spool, "_rolled", False))
                    ).lower(),
                    "X-AC022-Parser-Spool-Closed": str(spool.closed).lower(),
                    # The exception is raised during request parsing, before the
                    # submit endpoint receives any UploadFile to read.
                    "X-AC022-Endpoint-File-Read-Bytes": "0",
                }
            raise HTTPException(status_code=413, detail=exc.message, headers=headers) from exc


def install_bounded_multipart_parser() -> None:
    """Make Starlette request.form use the parser that enforces route limits."""

    if starlette_requests.MultiPartParser is not BoundedMultiPartParser:
        starlette_requests.MultiPartParser = BoundedMultiPartParser


class UploadSubmissionRoute(APIRoute):
    """Set file limits before FastAPI parses multipart bodies for submit routes."""

    def get_route_handler(self):
        route_handler = super().get_route_handler()
        if self.path not in {"/api/submit-jobs", "/api/submit-stream-v2"}:
            return route_handler

        from app.core.config import MAX_FILE_SIZE, MAX_TOTAL_UPLOAD_SIZE

        limits = UploadLimits(
            max_file_bytes=MAX_FILE_SIZE,
            max_total_bytes=MAX_TOTAL_UPLOAD_SIZE,
        )

        async def limited_route_handler(request):
            token = active_upload_limits.set(limits)
            try:
                return await route_handler(request)
            finally:
                active_upload_limits.reset(token)

        return limited_route_handler


install_bounded_multipart_parser()
