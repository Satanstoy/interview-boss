"""Tests for the real Agent answer API client wrapper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script_module():
    path = Path(__file__).parents[2] / "scripts" / "generate_agent_reference_answers.py"
    spec = importlib.util.spec_from_file_location("agent_answer_refresh_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_batch_stream_wrapper_reads_response_from_context_manager():
    module = _load_script_module()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield "data: " + json.dumps({"type": "init", "total": 1})
            yield "data: " + json.dumps({"type": "done", "failed": 0})

    class FakeStreamContext:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def stream(self, method, url, **kwargs):
            assert method == "POST"
            assert url.endswith("/api/master-bank/batch-generate-answers")
            assert kwargs["json"]["ids"] == [7001]
            return FakeStreamContext()

    assert module._stream_batch_generation(
        FakeClient(), "http://example.test", "token", [7001], False
    ) == 0

