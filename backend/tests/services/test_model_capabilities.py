"""上下文窗口能力解析、主动探测与缓存测试。"""

from types import SimpleNamespace

import pytest


def _response(prompt_tokens: int):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, input_tokens=prompt_tokens)
    )


class _FakeChat:
    def __init__(self, limit_tokens: int = 8192, chars_per_token: float = 4.0):
        self.limit_tokens = limit_tokens
        self.chars_per_token = chars_per_token
        self.calls: list[dict] = []

        class _Completions:
            pass

        self.completions = _Completions()
        self.completions.create = self.create

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = kwargs["messages"][0]["content"]
        prompt_tokens = max(1, round(len(content) / self.chars_per_token))
        if prompt_tokens + kwargs.get("max_tokens", 1) > self.limit_tokens:
            raise RuntimeError(
                f"maximum context length is {self.limit_tokens} tokens"
            )
        return _response(prompt_tokens)


class _FakeClient:
    def __init__(self, limit_tokens: int = 8192, chars_per_token: float = 4.0):
        self.chat = _FakeChat(limit_tokens, chars_per_token)


def test_capability_cache_key_is_stable_and_does_not_contain_secret():
    from app.services.model_capabilities import capability_cache_key

    first = capability_cache_key(
        "https://api.example.test/v1/", "mimo-v2.5", "chat"
    )
    second = capability_cache_key(
        "https://api.example.test/v1", "mimo-v2.5", "chat"
    )

    assert first == second
    assert "api.example.test" not in first
    assert "secret" not in capability_cache_key(
        "https://user:secret@api.example.test/v1", "mimo-v2.5", "chat"
    )


def test_extract_model_limits_accepts_generic_provider_metadata():
    from app.services.model_capabilities import extract_model_limits

    limits = extract_model_limits(
        {
            "id": "mimo-v2.5",
            "capabilities": {
                "limits": {
                    "max_context_window_tokens": 32768,
                    "max_prompt_tokens": 28672,
                    "max_output_tokens": 4096,
                }
            },
        }
    )

    assert limits == {
        "context_window_tokens": 32768,
        "input_token_limit": 28672,
        "output_token_limit": 4096,
    }


@pytest.mark.asyncio
async def test_explicit_context_override_wins_without_network_call():
    from app.services.model_capabilities import CapabilityResolver

    async def fail_metadata(*_args, **_kwargs):
        raise AssertionError("metadata should not be requested for an explicit override")

    resolver = CapabilityResolver(metadata_fetcher=fail_metadata)
    capability = await asyncio_resolve(resolver, 65536)

    assert capability.context_window_tokens == 65536
    assert capability.source == "override"
    assert capability.confidence == "explicit"


async def asyncio_resolve(resolver, override):
    return await resolver.resolve(
        client=object(),
        model="mimo-v2.5",
        base_url="https://api.example.test/v1",
        api_format="chat",
        context_window_override=override,
    )


@pytest.mark.asyncio
async def test_active_probe_exponentially_grows_then_binary_searches():
    from app.services.model_capabilities import probe_context_window

    client = _FakeClient(limit_tokens=8192)
    result = await probe_context_window(
        client,
        "mimo-v2.5",
        api_format="chat",
        initial_probe_tokens=512,
        max_probe_tokens=16384,
    )

    assert result.status == "verified"
    assert result.context_window_tokens is not None
    assert 7800 <= result.context_window_tokens <= 8192
    assert result.calls <= 16
    assert result.observed_prompt_tokens is not None


@pytest.mark.asyncio
async def test_context_error_is_distinguished_from_auth_or_network_error():
    from app.services.model_capabilities import is_context_limit_error, probe_context_window

    assert is_context_limit_error(
        RuntimeError("maximum context length is 8192 tokens")
    )
    assert not is_context_limit_error(RuntimeError("401 authentication failed"))
    assert not is_context_limit_error(RuntimeError("connection reset by peer"))

    class _BrokenChat:
        async def create(self, **_kwargs):
            raise RuntimeError("401 authentication failed")

    client = SimpleNamespace(chat=SimpleNamespace(completions=_BrokenChat()))
    result = await probe_context_window(client, "mimo-v2.5", max_probe_tokens=2048)

    assert result.status == "failed"
    assert result.context_window_tokens is None


@pytest.mark.asyncio
async def test_resolver_uses_metadata_before_active_probe_and_caches_result():
    from app.services.model_capabilities import CapabilityResolver

    metadata_calls = 0

    async def metadata_fetcher(_client, _model):
        nonlocal metadata_calls
        metadata_calls += 1
        return {"context_length": 32768, "max_output_tokens": 4096}

    resolver = CapabilityResolver(metadata_fetcher=metadata_fetcher)
    first = await resolver.resolve(
        client=object(),
        model="mimo-v2.5",
        base_url="https://api.example.test/v1",
        api_format="chat",
    )
    second = await resolver.resolve(
        client=object(),
        model="mimo-v2.5",
        base_url="https://api.example.test/v1/",
        api_format="chat",
    )

    assert first.context_window_tokens == 32768
    assert first.source == "metadata"
    assert second == first
    assert metadata_calls == 1


@pytest.mark.asyncio
async def test_probe_rejects_silent_truncation_when_usage_is_far_below_payload():
    from app.services.model_capabilities import probe_context_window

    class _TruncatingChat:
        async def create(self, **_kwargs):
            return _response(8)

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=_TruncatingChat())
    )
    result = await probe_context_window(
        client,
        "mimo-v2.5",
        initial_probe_tokens=512,
        max_probe_tokens=1024,
    )

    assert result.status == "unverified"
    assert result.context_window_tokens is None


@pytest.mark.asyncio
async def test_models_dev_source_looks_up_model_by_id_without_local_model_list():
    from app.services.model_capabilities import (
        ModelsDevMetadataSource,
        extract_model_limits,
    )

    async def fake_fetch_json():
        return {
            "xiaomi/mimo-v2.5-pro": {
                "id": "mimo-v2.5-pro",
                "limit": {"context": 1_048_576, "output": 131_072},
            }
        }

    source = ModelsDevMetadataSource(fetch_json=fake_fetch_json)
    metadata = await source(None, "mimo-v2.5-pro")

    assert metadata["limit"]["context"] == 1_048_576
    assert extract_model_limits(metadata) == {
        "context_window_tokens": 1_048_576,
        "input_token_limit": None,
        "output_token_limit": 131_072,
    }


@pytest.mark.asyncio
async def test_resolver_can_disable_active_probe_for_request_path():
    from app.services.model_capabilities import CapabilityResolver

    async def should_not_probe(*_args, **_kwargs):
        raise AssertionError("active probe must be explicit on the request path")

    resolver = CapabilityResolver(probe_fn=should_not_probe)
    capability = await resolver.resolve(
        client=object(),
        model="custom-model",
        base_url="https://custom.example.test/v1",
        allow_active_probe=False,
    )

    assert capability.context_window_tokens is None
    assert capability.source == "unknown"


@pytest.mark.asyncio
async def test_resolver_promotes_models_dev_catalog_to_reported_capability():
    from app.services.model_capabilities import CapabilityResolver

    async def catalog_fetcher(_client, _model):
        return {"limit": {"context": 1_048_576, "output": 131_072}}

    async def should_not_probe(*_args, **_kwargs):
        raise AssertionError("catalog metadata should avoid active probing")

    resolver = CapabilityResolver(
        catalog_fetcher=catalog_fetcher,
        probe_fn=should_not_probe,
    )
    capability = await resolver.resolve(
        client=object(),
        model="mimo-v2.5-pro",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        allow_active_probe=False,
    )

    assert capability.context_window_tokens == 1_048_576
    assert capability.output_token_limit == 131_072
    assert capability.source == "models_dev"
    assert capability.confidence == "catalog"
