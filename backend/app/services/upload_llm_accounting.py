"""Context and provider-boundary accounting for upload model requests."""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Callable

from app.services.upload_stage_names import canonical_upload_stage
from app.services.upload_retry_budget import RetryBudget


class UploadRetryBudgetExceeded(RuntimeError):
    """No provider request may be sent after this upload unit used its budget."""

    code = "MODEL_OUTPUT_INVALID"
    retryable = False


@dataclass
class UploadLLMContext:
    root_import_id: str
    stage: str
    unit_key: str
    credential_scope: str
    user_id: int | None
    credential: object | None = None
    api_format: str | None = None
    retry_budget: RetryBudget | None = None


_current_upload_llm_context: contextvars.ContextVar[UploadLLMContext | None] = (
    contextvars.ContextVar("current_upload_llm_context", default=None)
)


def current_upload_llm_context() -> UploadLLMContext | None:
    return _current_upload_llm_context.get()


@contextmanager
def upload_llm_context(
    *,
    root_import_id: str | None,
    stage: str,
    unit_key: str = "",
    credential_scope: str = "user",
    user_id: int | None = None,
):
    if not root_import_id:
        yield None
        return
    context = UploadLLMContext(
        root_import_id=str(root_import_id),
        stage=canonical_upload_stage(stage),
        unit_key=str(unit_key or ""),
        credential_scope=credential_scope,
        user_id=int(user_id) if user_id is not None else None,
    )
    token = _current_upload_llm_context.set(context)
    try:
        yield context
    finally:
        _current_upload_llm_context.reset(token)


@contextmanager
def upload_retry_budget_scope(max_attempts: int = 3):
    """Share one physical-call budget across a model call and its repairs."""

    context = current_upload_llm_context()
    if context is None:
        yield None
        return

    previous_budget = context.retry_budget
    budget = RetryBudget(max_attempts=max_attempts)
    context.retry_budget = budget
    try:
        yield budget
    finally:
        context.retry_budget = previous_budget


def upload_llm_stage(
    stage: str, *, unit_key: str = "", checkpoint_result: bool = False
):
    """Decorate one upload graph node with its durable stage and credential scope."""

    def decorate(function):
        @wraps(function)
        async def wrapped(state, *args, **kwargs):
            root_import_id = state.get("import_id")
            if not root_import_id:
                return await function(state, *args, **kwargs)
            with upload_llm_context(
                root_import_id=root_import_id,
                stage=stage,
                unit_key=unit_key,
                credential_scope=state.get("credential_scope", "user"),
                user_id=state.get("user_id"),
            ):
                result = await function(state, *args, **kwargs)

            if checkpoint_result and root_import_id:
                data = result.get("extracted_data") or state.get("extracted_data")
                job_id = state.get("job_id")
                lease_generation = state.get("_lease_generation")
                if data and job_id is not None and lease_generation is not None:
                    import json

                    from app.services.upload_repository import (
                        persist_succeeded_stage_checkpoint,
                    )

                    checkpoint = json.dumps(
                        {
                            "doc_type": result.get("doc_type")
                            or state.get("doc_type", ""),
                            "data": data,
                            "url": result.get("saved_url") or state.get("url", ""),
                        },
                        ensure_ascii=False,
                    )

                    def _persist_checkpoint():
                        from app.db.connection import get_db_connection

                        conn = get_db_connection()
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            saved = persist_succeeded_stage_checkpoint(
                                conn,
                                import_id=str(root_import_id),
                                stage="extract",
                                unit_key="document",
                                result_json=checkpoint,
                                job_id=int(job_id),
                                lease_generation=int(lease_generation),
                            )
                            if not saved:
                                raise RuntimeError(
                                    "上传 worker generation 已失效，不能提交提取检查点"
                                )
                            conn.commit()
                        except Exception:
                            conn.rollback()
                            raise

                    await asyncio.to_thread(_persist_checkpoint)

            return result

        return wrapped

    return decorate


def _token_count(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _usage_tokens(response) -> tuple[int | None, int | None]:
    from app.services.llm_usage import normalize_cache_usage

    usage = normalize_cache_usage(getattr(response, "usage", None))
    return _token_count(usage.get("input_tokens")), _token_count(
        usage.get("output_tokens")
    )


def _is_unknown_provider_outcome(error: BaseException) -> bool:
    name = type(error).__name__.lower()
    return any(
        marker in name
        for marker in ("timeout", "connection", "connecterror", "networkerror")
    )


async def call_provider_with_upload_ledger(
    request: Callable[[], object], *, model: str, provider: str
):
    """Reserve before a physical provider attempt and settle it from the response.

    This wrapper sits at the provider ``create`` call, inside tenacity's retry
    body. Every retry therefore receives a new key and its own atomic quota
    reservation.
    """
    context = current_upload_llm_context()
    if context is None:
        return await request()

    if context.retry_budget is not None and context.retry_budget.exhausted:
        raise UploadRetryBudgetExceeded(
            f"上传阶段 {context.stage}/{context.unit_key} 的物理模型调用预算已耗尽"
        )

    from app.db.connection import get_db_connection, run_db
    from app.services import llm_quota
    from app.services.upload_credentials import (
        UploadCredentialError,
        complete_llm_call,
        reserve_llm_call,
        resolve_upload_credentials,
    )

    credential = context.credential
    if credential is None:
        credential = resolve_upload_credentials(
            credential_scope=context.credential_scope,
            user_id=(
                context.user_id if context.credential_scope == "user" else None
            ),
            stage=context.stage,
            unit_key=context.unit_key,
        )
        context.credential = credential
    if credential.scope != context.credential_scope:
        raise UploadCredentialError(
            "CREDENTIAL_SCOPE_MISMATCH",
            scope=context.credential_scope,
            message="上传模型调用凭据作用域不匹配",
        )

    call_key = uuid.uuid4().hex
    effective_provider = str(provider or credential.provider)
    effective_model = str(model or credential.model)

    def reserve():
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                reserve_llm_call(
                    conn,
                    root_import_id=context.root_import_id,
                    stage=context.stage,
                    unit_key=context.unit_key,
                    call_key=call_key,
                    credential_scope=credential.scope,
                    payer_type=credential.payer_type,
                    payer_user_id=credential.payer_user_id,
                    provider=effective_provider,
                    model=effective_model,
                    api_format=context.api_format or credential.api_format,
                    config_fingerprint=credential.config_fingerprint,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    await run_db(reserve)
    # Count only after a durable ledger reservation exists and before sending
    # the request. A lost provider response still consumes one physical try.
    if context.retry_budget is not None:
        context.retry_budget.physical_attempts += 1

    async def settle(status, *, input_tokens=None, output_tokens=None, error_code=None):
        def persist():
            with get_db_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    complete_llm_call(
                        conn,
                        call_key=call_key,
                        status=status,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        error_code=error_code,
                    )
                    if (
                        credential.payer_type == "user"
                        and input_tokens is not None
                        and output_tokens is not None
                    ):
                        conn.execute(
                            "UPDATE llm_usage SET total_tokens = total_tokens + ? "
                            "WHERE user_id = ? AND day = ?",
                            (
                                input_tokens + output_tokens,
                                credential.payer_user_id,
                                llm_quota._today(),
                            ),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        await run_db(persist)

    try:
        response = await request()
    except Exception as error:
        await settle(
            "unknown" if _is_unknown_provider_outcome(error) else "failed",
            error_code=type(error).__name__[:80],
        )
        raise

    input_tokens, output_tokens = _usage_tokens(response)
    await settle(
        "succeeded", input_tokens=input_tokens, output_tokens=output_tokens
    )
    return response
