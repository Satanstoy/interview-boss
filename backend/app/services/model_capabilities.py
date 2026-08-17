"""Resolve LLM model limits without maintaining a model-name allow-list.

The resolver follows a conservative order:

1. an explicit deployment override;
2. capability metadata returned by the provider;
3. a bounded active probe for custom or incomplete OpenAI-compatible endpoints.

The active probe is intentionally cached by endpoint/model/API format.  It is
not run in the normal request path once a trustworthy result is available.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger("interview-boss")

_PROBE_BLOCK = "context-window-probe-0123456789 "
_DEFAULT_INITIAL_PROBE_TOKENS = 1024
_DEFAULT_MAX_PROBE_TOKENS = 131_072
_DEFAULT_MAX_PROBE_CALLS = 24
_DEFAULT_PROBE_TIMEOUT_SECONDS = 45.0
_MIN_CHARS_PER_TOKEN = 1.0
_MAX_CHARS_PER_TOKEN = 8.0

_CONTEXT_KEYS = {
    "context",
    "context_length",
    "context_window",
    "context_window_tokens",
    "max_context_length",
    "max_context_tokens",
    "max_context_window_tokens",
    "max_model_len",
}
_INPUT_KEYS = {
    "input_token_limit",
    "max_input_tokens",
    "max_prompt_tokens",
    "prompt_token_limit",
}
_OUTPUT_KEYS = {
    "max_completion_tokens",
    "max_output_tokens",
    "output",
    "output_token_limit",
}


@dataclass(frozen=True)
class ModelCapability:
    """The limits that matter when constructing one model request."""

    context_window_tokens: int | None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    source: Literal["override", "metadata", "models_dev", "active_probe", "unknown"] = "unknown"
    confidence: Literal["explicit", "reported", "catalog", "verified", "unverified"] = "unverified"
    probe_status: str | None = None
    observed_prompt_tokens: int | None = None
    chars_per_token: float | None = None
    measured_at: float | None = None
    cache_key: str | None = None


@dataclass(frozen=True)
class ContextProbeResult:
    """Result of the bounded active probe."""

    status: Literal["verified", "bounded", "unverified", "failed"]
    context_window_tokens: int | None
    calls: int
    observed_prompt_tokens: int | None = None
    lower_bound_tokens: int | None = None
    chars_per_token: float | None = None
    error: str | None = None


def _normalise_base_url(base_url: str | None) -> str:
    """Remove credentials and cosmetic trailing slashes before keying a cache."""

    value = (base_url or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if not parsed.hostname:
            return value.rstrip("/")
        host = parsed.hostname.lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = host
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))
    except ValueError:
        # The client will report an invalid URL later; this keeps cache-key
        # construction deterministic without ever retaining credentials.
        return value.rsplit("@", 1)[-1].rstrip("/")


def capability_cache_key(base_url: str | None, model: str, api_format: str) -> str:
    """Return an opaque cache key; API keys never appear in it."""

    raw = "\x1f".join(
        (_normalise_base_url(base_url), (model or "").strip(), (api_format or "chat").lower())
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"llm-capability:{digest}"


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _object_to_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    for method_name in ("model_dump", "to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                dumped = method()
            except Exception:
                continue
            if isinstance(dumped, Mapping):
                return dumped
    if hasattr(value, "__dict__"):
        return vars(value)
    return None


def _iter_fields(value: Any, depth: int = 0):
    """Yield nested object fields while remaining safe for SDK response objects."""

    if depth > 8:
        return
    mapping = _object_to_mapping(value)
    if mapping is None:
        return
    for key, child in mapping.items():
        normalised_key = str(key).strip().lower().replace("-", "_")
        yield normalised_key, child
        if _object_to_mapping(child) is not None:
            yield from _iter_fields(child, depth + 1)


def _first_field(payload: Any, keys: set[str]) -> int | None:
    for key, value in _iter_fields(payload):
        if key in keys:
            result = _positive_int(value)
            if result is not None:
                return result
    return None


def extract_model_limits(metadata: Any) -> dict[str, int | None]:
    """Extract generic limit fields from provider/model metadata.

    This deliberately looks at field names, not model names.  It accepts the
    naming used by OpenCode/models.dev and common OpenAI-compatible gateways.
    """

    return {
        "context_window_tokens": _first_field(metadata, _CONTEXT_KEYS),
        "input_token_limit": _first_field(metadata, _INPUT_KEYS),
        "output_token_limit": _first_field(metadata, _OUTPUT_KEYS),
    }


class CapabilityCache:
    """Small process-local TTL cache with an injectable clock for tests."""

    def __init__(self, ttl_seconds: float = 86_400.0, clock: Callable[[], float] = time.monotonic):
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._clock = clock
        self._items: dict[str, tuple[float, ModelCapability]] = {}

    def get(self, key: str) -> ModelCapability | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, capability = item
        if self._clock() >= expires_at:
            self._items.pop(key, None)
            return None
        return capability

    def set(self, key: str, capability: ModelCapability) -> None:
        self._items[key] = (self._clock() + self.ttl_seconds, capability)

    def clear(self) -> None:
        self._items.clear()


class ModelsDevMetadataSource:
    """Optional OpenCode-compatible model catalog source.

    models.dev is a maintained metadata catalog, not a model-name table inside
    this project.  The payload is fetched at most once per TTL and the lookup
    is performed by the model id supplied by the deployment.
    """

    def __init__(
        self,
        *,
        endpoint: str = "https://models.dev/models.json",
        ttl_seconds: float = 21_600.0,
        fetch_json: Callable[[], Awaitable[Mapping[str, Any]]] | None = None,
    ):
        self.endpoint = endpoint
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self._fetch_json = fetch_json or self._request_json
        self._payload: Mapping[str, Any] | None = None
        self._loaded_at = 0.0

    async def _request_json(self) -> Mapping[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.get(self.endpoint)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("models.dev returned a non-object payload")
        return payload

    async def _payload_or_fetch(self) -> Mapping[str, Any] | None:
        now = time.monotonic()
        if self._payload is not None and now - self._loaded_at < self.ttl_seconds:
            return self._payload
        try:
            payload = await self._fetch_json()
        except Exception as exc:
            logger.info("models.dev metadata unavailable: %s", exc)
            return None
        self._payload = payload
        self._loaded_at = now
        return payload

    async def __call__(self, _client: Any, model: str) -> Mapping[str, Any] | None:
        payload = await self._payload_or_fetch()
        if not payload:
            return None

        target = (model or "").strip().lower()
        if not target:
            return None
        exact = payload.get(target) or payload.get(model)
        if isinstance(exact, Mapping):
            return exact

        # models.json is keyed as provider/model.  Only accept a unique suffix
        # match so two providers exposing the same id cannot silently collide.
        candidates = [
            value
            for key, value in payload.items()
            if str(key).rsplit("/", 1)[-1].lower() == target
            and isinstance(value, Mapping)
        ]
        return candidates[0] if len(candidates) == 1 else None


def _value(response: Any, key: str) -> Any:
    if isinstance(response, Mapping):
        return response.get(key)
    return getattr(response, key, None)


def _input_usage(response: Any) -> int | None:
    usage = _value(response, "usage")
    for key in ("prompt_tokens", "input_tokens", "input_token_count"):
        parsed = _positive_int(_value(usage, key)) if usage is not None else None
        if parsed is not None:
            return parsed
    return None


def is_context_limit_error(exc: BaseException) -> bool:
    """Classify only errors that plausibly describe an input/context overflow."""

    text = str(exc).lower()
    if any(marker in text for marker in ("authentication", "unauthorized", "api key", "rate limit", "connection reset")):
        return False
    context_markers = (
        "context length",
        "context window",
        "maximum context",
        "max_model_len",
        "input token limit",
        "prompt is too long",
        "too many tokens",
        "token limit",
        "request too large",
    )
    return any(marker in text for marker in context_markers)


def _context_limit_from_error(exc: BaseException) -> int | None:
    text = str(exc)
    patterns = (
        r"(?:maximum\s+context\s+length\s+is|context\s+window(?:\s+is)?|max_model_len\s*[=:])\s*([\d,]+)",
        r"(?:maximum\s+of|limit(?:ed)?\s+to)\s*([\d,]+)\s+tokens",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _positive_int(match.group(1))
    return None


def _probe_payload(target_chars: int) -> str:
    target_chars = max(1, int(target_chars))
    repetitions = math.ceil(target_chars / len(_PROBE_BLOCK))
    return (_PROBE_BLOCK * repetitions)[:target_chars]


async def _probe_once(
    client: Any,
    model: str,
    payload: str,
    api_format: str,
    request_timeout: float | None,
) -> tuple[bool, Any | None, BaseException | None]:
    """Send one minimal request without tools or application prompts."""
    try:
        if api_format == "responses":
            request = client.responses.create(
                model=model,
                input=payload,
                max_output_tokens=1,
                temperature=0,
            )
        elif api_format == "anthropic":
            request = client.messages.create(
                model=model,
                messages=[{"role": "user", "content": payload}],
                max_tokens=1,
                temperature=0,
            )
        else:
            request = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": payload}],
                max_tokens=1,
                temperature=0,
            )
        if request_timeout is None:
            response = await request
        else:
            response = await asyncio.wait_for(request, timeout=request_timeout)
        return True, response, None
    except Exception as exc:  # the caller must classify provider exceptions
        return False, None, exc


async def probe_context_window(
    client: Any,
    model: str,
    *,
    api_format: str = "chat",
    initial_probe_tokens: int = _DEFAULT_INITIAL_PROBE_TOKENS,
    max_probe_tokens: int = _DEFAULT_MAX_PROBE_TOKENS,
    max_calls: int = _DEFAULT_MAX_PROBE_CALLS,
    request_timeout: float | None = _DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> ContextProbeResult:
    """Find the accepted input boundary with exponential growth + binary search.

    The probe reports ``verified`` only when the provider rejects a larger
    request as a context overflow and returns a usable input-token count on
    successful requests.  A successful request without usage is merely a
    lower bound and is never promoted to a trusted context size.
    """

    initial_probe_tokens = max(1, int(initial_probe_tokens))
    max_probe_tokens = max(initial_probe_tokens, int(max_probe_tokens))
    max_calls = max(1, int(max_calls))
    chars_per_token = 4.0
    lower_chars = 0
    upper_chars: int | None = None
    best_usage: int | None = None
    best_chars = 0
    calls = 0
    target_tokens = initial_probe_tokens

    while calls < max_calls and target_tokens <= max_probe_tokens:
        target_chars = max(1, round(target_tokens * chars_per_token))
        payload = _probe_payload(target_chars)
        success, response, error = await _probe_once(
            client, model, payload, api_format, request_timeout
        )
        calls += 1

        if not success:
            if not is_context_limit_error(error):
                return ContextProbeResult(
                    status="failed",
                    context_window_tokens=None,
                    calls=calls,
                    observed_prompt_tokens=best_usage,
                    lower_bound_tokens=best_usage,
                    chars_per_token=(best_chars / best_usage if best_usage else None),
                    error=str(error)[:240] if error else "provider request failed",
                )
            parsed_limit = _context_limit_from_error(error)
            if best_usage is None and parsed_limit is not None:
                return ContextProbeResult(
                    status="verified",
                    context_window_tokens=parsed_limit,
                    calls=calls,
                    chars_per_token=chars_per_token,
                )
            upper_chars = len(payload)
            break

        usage = _input_usage(response)
        expected_usage = max(1, round(len(payload) / chars_per_token))
        if usage is not None and usage < max(1, round(expected_usage * 0.6)):
            return ContextProbeResult(
                status="unverified",
                context_window_tokens=None,
                calls=calls,
                observed_prompt_tokens=usage,
                lower_bound_tokens=usage,
                error="provider usage is far below the submitted probe payload",
            )

        lower_chars = len(payload)
        if usage is not None:
            best_usage = max(best_usage or 0, usage)
            best_chars = len(payload) if usage >= (best_usage or usage) else best_chars
            chars_per_token = min(
                _MAX_CHARS_PER_TOKEN,
                max(_MIN_CHARS_PER_TOKEN, len(payload) / max(1, usage)),
            )

        if target_tokens >= max_probe_tokens:
            return ContextProbeResult(
                status="bounded" if usage is not None else "unverified",
                context_window_tokens=None,
                calls=calls,
                observed_prompt_tokens=best_usage,
                lower_bound_tokens=best_usage,
                chars_per_token=(best_chars / best_usage if best_usage else None),
            )
        target_tokens = min(max_probe_tokens, target_tokens * 2)

    if upper_chars is None:
        return ContextProbeResult(
            status="unverified",
            context_window_tokens=None,
            calls=calls,
            observed_prompt_tokens=best_usage,
            lower_bound_tokens=best_usage,
            chars_per_token=(best_chars / best_usage if best_usage else None),
        )

    # Once a failing request brackets a successful request, search by payload
    # size.  The provider's usage field, rather than our character estimate,
    # is the source of truth for the final token boundary.
    while calls < max_calls and upper_chars - lower_chars > len(_PROBE_BLOCK):
        middle_chars = (lower_chars + upper_chars) // 2
        payload = _probe_payload(middle_chars)
        success, response, error = await _probe_once(
            client, model, payload, api_format, request_timeout
        )
        calls += 1
        if not success:
            if not is_context_limit_error(error):
                return ContextProbeResult(
                    status="failed",
                    context_window_tokens=None,
                    calls=calls,
                    observed_prompt_tokens=best_usage,
                    lower_bound_tokens=best_usage,
                    chars_per_token=(best_chars / best_usage if best_usage else None),
                    error=str(error)[:240] if error else "provider request failed",
                )
            upper_chars = middle_chars
            continue

        usage = _input_usage(response)
        expected_usage = max(1, round(len(payload) / chars_per_token))
        if usage is not None and usage < max(1, round(expected_usage * 0.6)):
            return ContextProbeResult(
                status="unverified",
                context_window_tokens=None,
                calls=calls,
                observed_prompt_tokens=usage,
                lower_bound_tokens=usage,
                error="provider usage is far below the submitted probe payload",
            )
        lower_chars = middle_chars
        if usage is not None and (best_usage is None or usage > best_usage):
            best_usage = usage
            best_chars = len(payload)

    if best_usage is None:
        return ContextProbeResult(
            status="unverified",
            context_window_tokens=None,
            calls=calls,
        )
    return ContextProbeResult(
        status="verified",
        # max_output_tokens=1 was included in every request, so the accepted
        # prompt boundary plus one is the conservative total context bound.
        context_window_tokens=best_usage + 1,
        calls=calls,
        observed_prompt_tokens=best_usage,
        lower_bound_tokens=best_usage,
        chars_per_token=best_chars / max(1, best_usage),
    )


MetadataFetcher = Callable[[Any, str], Awaitable[Any | None]]
ProbeFunction = Callable[..., Awaitable[ContextProbeResult]]


class CapabilityResolver:
    """Resolve and cache capability metadata for one endpoint/model pair."""

    def __init__(
        self,
        *,
        metadata_fetcher: MetadataFetcher | None = None,
        catalog_fetcher: MetadataFetcher | None = None,
        probe_fn: ProbeFunction = probe_context_window,
        cache: CapabilityCache | None = None,
    ):
        self.metadata_fetcher = metadata_fetcher
        self.catalog_fetcher = catalog_fetcher
        self.probe_fn = probe_fn
        self.cache = cache or CapabilityCache()

    async def _fetch_metadata(self, client: Any, model: str) -> Any | None:
        if self.metadata_fetcher is not None:
            try:
                return await self.metadata_fetcher(client, model)
            except Exception as exc:
                logger.info("LLM model capability metadata unavailable: %s", exc)
                return None

        models = getattr(client, "models", None)
        retrieve = getattr(models, "retrieve", None)
        if not callable(retrieve):
            return None
        try:
            response = retrieve(model)
            return await response if hasattr(response, "__await__") else response
        except Exception as exc:
            logger.info("LLM model capability metadata unavailable: %s", exc)
            return None

    async def resolve(
        self,
        *,
        client: Any,
        model: str,
        base_url: str | None,
        api_format: str = "chat",
        context_window_override: int | None = None,
        input_token_limit_override: int | None = None,
        output_token_limit_override: int | None = None,
        force_probe: bool = False,
        allow_active_probe: bool = False,
        probe_kwargs: dict[str, Any] | None = None,
    ) -> ModelCapability:
        key = capability_cache_key(base_url, model, api_format)

        if context_window_override:
            capability = ModelCapability(
                context_window_tokens=int(context_window_override),
                input_token_limit=input_token_limit_override,
                output_token_limit=output_token_limit_override,
                source="override",
                confidence="explicit",
                measured_at=time.time(),
                cache_key=key,
            )
            return capability

        if not force_probe:
            cached = self.cache.get(key)
            if cached is not None:
                if input_token_limit_override or output_token_limit_override:
                    return ModelCapability(
                        **{
                            **cached.__dict__,
                            "input_token_limit": input_token_limit_override
                            or cached.input_token_limit,
                            "output_token_limit": output_token_limit_override
                            or cached.output_token_limit,
                        }
                    )
                return cached

        metadata = await self._fetch_metadata(client, model)
        limits = extract_model_limits(metadata) if metadata is not None else {}
        if limits.get("context_window_tokens"):
            capability = ModelCapability(
                context_window_tokens=limits["context_window_tokens"],
                input_token_limit=input_token_limit_override or limits.get("input_token_limit"),
                output_token_limit=output_token_limit_override or limits.get("output_token_limit"),
                source="metadata",
                confidence="reported",
                measured_at=time.time(),
                cache_key=key,
            )
            self.cache.set(key, capability)
            return capability

        if self.catalog_fetcher is not None:
            try:
                catalog_metadata = await self.catalog_fetcher(client, model)
            except Exception as exc:
                logger.info("model catalog capability unavailable: %s", exc)
                catalog_metadata = None
            catalog_limits = (
                extract_model_limits(catalog_metadata)
                if catalog_metadata is not None
                else {}
            )
            if catalog_limits.get("context_window_tokens"):
                capability = ModelCapability(
                    context_window_tokens=catalog_limits["context_window_tokens"],
                    input_token_limit=input_token_limit_override or catalog_limits.get("input_token_limit"),
                    output_token_limit=output_token_limit_override or catalog_limits.get("output_token_limit"),
                    source="models_dev",
                    confidence="catalog",
                    measured_at=time.time(),
                    cache_key=key,
                )
                self.cache.set(key, capability)
                return capability

        if not allow_active_probe and not force_probe:
            return ModelCapability(
                context_window_tokens=None,
                input_token_limit=input_token_limit_override,
                output_token_limit=output_token_limit_override,
                source="unknown",
                confidence="unverified",
                probe_status="not_requested",
                measured_at=time.time(),
                cache_key=key,
            )

        result = await self.probe_fn(
            client,
            model,
            api_format=api_format,
            **(probe_kwargs or {}),
        )
        if result.context_window_tokens:
            capability = ModelCapability(
                context_window_tokens=result.context_window_tokens,
                input_token_limit=input_token_limit_override,
                output_token_limit=output_token_limit_override,
                source="active_probe",
                confidence="verified" if result.status == "verified" else "unverified",
                probe_status=result.status,
                observed_prompt_tokens=result.observed_prompt_tokens,
                chars_per_token=result.chars_per_token,
                measured_at=time.time(),
                cache_key=key,
            )
            if result.status == "verified":
                self.cache.set(key, capability)
            return capability

        return ModelCapability(
            context_window_tokens=None,
            input_token_limit=input_token_limit_override,
            output_token_limit=output_token_limit_override,
            source="unknown",
            confidence="unverified",
            probe_status=result.status,
            observed_prompt_tokens=result.observed_prompt_tokens,
            chars_per_token=result.chars_per_token,
            measured_at=time.time(),
            cache_key=key,
        )
