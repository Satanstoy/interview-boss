"""Tests for embedding_service — backend mode selection and fallback behavior."""

from __future__ import annotations

import importlib
from unittest import mock

import pytest


def _reload_module(**env_overrides):
    """Reload embedding_service with custom env vars, then restore."""
    import app.services.embedding_service as mod

    with mock.patch.dict("os.environ", env_overrides):
        importlib.reload(mod)
        yield mod
    # Restore after test
    importlib.reload(mod)


class TestEncodeTextsBackendBehavior:
    """Backend selection tests for encode_texts()."""

    def test_hash_fallback_raises_in_production(self):
        """When EMBEDDING_BACKEND=onnx and model is missing, raise instead of fallback."""
        for mod in _reload_module(EMBEDDING_BACKEND="onnx", EMBEDDING_OFFLINE="1"):
            # Force ONNX session to None so _get_onnx_runtime will fail
            mod._SESSION = None
            mod._TOKENIZER = None

            with pytest.raises(Exception):
                mod.encode_texts(["test"])

    def test_auto_backend_falls_back_to_hash(self):
        """When EMBEDDING_BACKEND=auto, ONNX failure triggers hash fallback."""
        for mod in _reload_module(EMBEDDING_BACKEND="auto", EMBEDDING_OFFLINE="1"):
            mod._SESSION = None
            mod._TOKENIZER = None

            # Should NOT raise — falls back to hash
            result = mod.encode_texts(["test"])
            assert result.shape == (1, mod._SILICONFLOW_DIMENSION)

    def test_explicit_hash_backend(self):
        """When EMBEDDING_BACKEND=hash, always uses hash encoding."""
        for mod in _reload_module(EMBEDDING_BACKEND="hash"):
            result = mod.encode_texts(["hello world"])
            assert result.shape[0] == 1
            assert result.shape[1] == mod._DIMENSION

    def test_empty_texts_returns_empty_array(self):
        """Empty input returns correctly shaped empty array."""
        for mod in _reload_module():
            result = mod.encode_texts([])
            assert result.shape == (0, mod._SILICONFLOW_DIMENSION)

    def test_unsupported_backend_raises(self):
        """Unknown backend value raises ValueError."""
        for mod in _reload_module(EMBEDDING_BACKEND="unknown"):
            with pytest.raises(ValueError, match="Unsupported"):
                mod.encode_texts(["test"])
