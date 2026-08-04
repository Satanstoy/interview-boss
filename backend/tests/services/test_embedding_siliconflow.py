"""Tests for embedding_service siliconflow backend and dimension reporting."""

from __future__ import annotations

import importlib
from unittest import mock

import numpy as np
import pytest


def _reload_module(**env_overrides):
    import app.services.embedding_service as mod

    with mock.patch.dict("os.environ", env_overrides):
        importlib.reload(mod)
        yield mod
    importlib.reload(mod)


class TestSiliconflowBackend:
    """SiliconFlow API backend (BAAI/bge-m3, 1024-dim)."""

    def test_siliconflow_backend_returns_correct_dimension(self):
        """siliconflow backend yields 1024-dim normalized vectors."""
        fake_embedding = [0.1] * 1024

        for mod in _reload_module(
            EMBEDDING_BACKEND="siliconflow",
            SILICONFLOW_API_KEY="test-key",
            SILICONFLOW_BASE_URL="https://api.siliconflow.cn/v1",
            EMBEDDING_API_MODEL="BAAI/bge-m3",
            EMBEDDING_API_BATCH="32",
        ):
            fake_resp = mock.MagicMock()
            fake_resp.data = [mock.MagicMock(embedding=fake_embedding)]

            with mock.patch.object(mod, "_get_siliconflow_client") as m_client:
                client = mock.MagicMock()
                client.embeddings.create.return_value = fake_resp
                m_client.return_value = client

                result = mod.encode_texts(["test question"])

            assert result.shape == (1, 1024)
            assert result.dtype == np.float32
            norm = float(np.linalg.norm(result[0]))
            assert abs(norm - 1.0) < 1e-5, "vectors must be L2-normalized"

    def test_siliconflow_batch_split_calls_create_per_chunk(self):
        """When texts exceed EMBEDDING_API_BATCH, multiple create() calls are made."""
        fake_embedding = [0.0] * 1023 + [1.0]

        for mod in _reload_module(
            EMBEDDING_BACKEND="siliconflow",
            SILICONFLOW_API_KEY="test-key",
            EMBEDDING_API_MODEL="BAAI/bge-m3",
            EMBEDDING_API_BATCH="2",
        ):

            def _fake_create(model, input):
                resp = mock.MagicMock()
                resp.data = [mock.MagicMock(embedding=fake_embedding) for _ in input]
                return resp

            with mock.patch.object(mod, "_get_siliconflow_client") as m_client:
                client = mock.MagicMock()
                client.embeddings.create.side_effect = _fake_create
                m_client.return_value = client

                result = mod.encode_texts(["a", "b", "c", "d", "e"])

            assert result.shape == (5, 1024)
            assert client.embeddings.create.call_count == 3
            sent_inputs = [
                c.kwargs.get("input") for c in client.embeddings.create.call_args_list
            ]
            assert sent_inputs == [["a", "b"], ["c", "d"], ["e"]]

    def test_siliconflow_empty_input_returns_empty(self):
        for mod in _reload_module(
            EMBEDDING_BACKEND="siliconflow",
            SILICONFLOW_API_KEY="test-key",
        ):
            result = mod.encode_texts([])
            assert result.shape[0] == 0

    def test_siliconflow_api_error_raises(self):
        for mod in _reload_module(
            EMBEDDING_BACKEND="siliconflow",
            SILICONFLOW_API_KEY="test-key",
        ):
            with mock.patch.object(mod, "_get_siliconflow_client") as m_client:
                client = mock.MagicMock()
                client.embeddings.create.side_effect = RuntimeError("api down")
                m_client.return_value = client
                with pytest.raises(RuntimeError, match="api down"):
                    mod.encode_texts(["x"])

    def test_siliconflow_client_caching(self):
        """Same key+url+model reuses the cached OpenAI sync client."""
        with mock.patch.dict(
            "os.environ",
            {
                "SILICONFLOW_API_KEY": "test-key",
                "SILICONFLOW_BASE_URL": "https://api.siliconflow.cn/v1",
                "EMBEDDING_API_MODEL": "BAAI/bge-m3",
            },
        ):
            for mod in _reload_module():
                mod._SILICONFLOW_CLIENTS.clear()
                with mock.patch("openai.OpenAI") as m_openai:
                    c1 = mock.MagicMock(name="c1")
                    c2 = mock.MagicMock(name="c2")
                    m_openai.side_effect = [c1, c2]
                    got1 = mod._get_siliconflow_client()
                    got2 = mod._get_siliconflow_client()
                    assert got1 is got2
                    m_openai.assert_called_once()

    def test_siliconflow_client_keyed_cache_rebuilds_on_config_change(self):
        """Changing api_key/base_url/model creates a NEW client."""
        with mock.patch.dict(
            "os.environ",
            {
                "SILICONFLOW_API_KEY": "test-key",
                "SILICONFLOW_BASE_URL": "https://api.siliconflow.cn/v1",
                "EMBEDDING_API_MODEL": "BAAI/bge-m3",
            },
        ):
            for mod in _reload_module():
                mod._SILICONFLOW_CLIENTS.clear()
                with mock.patch("openai.OpenAI") as m_openai:
                    c1 = mock.MagicMock(name="c1")
                    c2 = mock.MagicMock(name="c2")
                    m_openai.side_effect = [c1, c2]

                    with mock.patch.object(mod, "_SILICONFLOW_API_KEY", "key-A"):
                        got_a = mod._get_siliconflow_client()
                    with mock.patch.object(mod, "_SILICONFLOW_API_KEY", "key-B"):
                        got_b = mod._get_siliconflow_client()
                    with mock.patch.object(mod, "_SILICONFLOW_API_KEY", "key-A"):
                        got_a2 = mod._get_siliconflow_client()

                    assert got_a is not got_b
                    assert got_a2 is got_a
                    assert m_openai.call_count == 2

    def test_auto_falls_back_to_hash_when_no_onnx_no_key(self):
        """auto with no onnx and no siliconflow key falls back to hash."""
        for mod in _reload_module(
            EMBEDDING_BACKEND="auto",
            EMBEDDING_OFFLINE="1",
        ):
            mod._SESSION = None
            mod._TOKENIZER = None
            with mock.patch.dict(
                "os.environ", {"SILICONFLOW_API_KEY": ""}, clear=False
            ):
                result = mod.encode_texts(["test"])
            assert result.shape[0] == 1

    def test_auto_uses_siliconflow_when_configured_and_onnx_missing(self):
        """auto with siliconflow key but no onnx uses siliconflow backend."""
        fake_embedding = [0.5] * 1024
        for mod in _reload_module(
            EMBEDDING_BACKEND="auto",
            EMBEDDING_OFFLINE="1",
            SILICONFLOW_API_KEY="test-key",
            SILICONFLOW_BASE_URL="https://api.siliconflow.cn/v1",
            EMBEDDING_API_MODEL="BAAI/bge-m3",
        ):
            mod._SESSION = None
            mod._TOKENIZER = None
            fake_resp = mock.MagicMock()
            fake_resp.data = [mock.MagicMock(embedding=fake_embedding)]
            with mock.patch.object(mod, "_get_siliconflow_client") as m_client:
                client = mock.MagicMock()
                client.embeddings.create.return_value = fake_resp
                m_client.return_value = client
                result = mod.encode_texts(["question"])
            assert result.shape == (1, 1024)


class TestGetEmbeddingDimension:
    def test_dimension_onnx_default(self):
        for mod in _reload_module(EMBEDDING_BACKEND="onnx"):
            assert mod.get_embedding_dimension() == 512

    def test_dimension_hash_default(self):
        for mod in _reload_module(EMBEDDING_BACKEND="hash"):
            assert mod.get_embedding_dimension() == 512

    def test_dimension_siliconflow(self):
        for mod in _reload_module(
            EMBEDDING_BACKEND="siliconflow", SILICONFLOW_API_KEY="k"
        ):
            assert mod.get_embedding_dimension() == 1024

    def test_dimension_siliconflow_overrides_env_dim(self):
        """Even if EMBEDDING_DIMENSION env is set, siliconflow forces 1024."""
        for mod in _reload_module(
            EMBEDDING_BACKEND="siliconflow",
            SILICONFLOW_API_KEY="k",
            EMBEDDING_DIMENSION="256",
        ):
            assert mod.get_embedding_dimension() == 1024
