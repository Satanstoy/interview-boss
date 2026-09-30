"""凭据预检 job 与真实 provider 探测（R01 / AC-004、AC-013）。

在 accept 的同一事务里为每个新 root 创建 ``credential_preflight`` job
（job_type 注册进 dispatcher）；worker 执行时按 policy scope 解析凭据并
做真实模型 ping：

- 成功 → ``upload_stage_results`` 的 ``preflight`` 阶段标记 succeeded，
  根任务保持可派发（queued）；
- 401 / 配置缺失 → ``MODEL_AUTH_INVALID`` / ``MODEL_CONFIG_MISSING``，根
  ``needs_action``，**不派发提取**（配置修复后走同 root 恢复）；
- provider 404 / 超时 → ``UPSTREAM_UNAVAILABLE``，阻塞但可确定性失败。

探测使用与提取完全相同的 scope 凭据（user 绝不借用 global），
``probe`` 可注入以便本地 stub 验证 401/404/超时。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

logger = logging.getLogger("interview-boss")

PREFLIGHT_JOB_TYPE = "credential_preflight"
PREFLIGHT_STAGE = "preflight"
PREFLIGHT_PIPELINE_VERSION = "upload-pipeline-v1"


@dataclass(frozen=True)
class PreflightOutcome:
    """一次探测的判定结果（不包含任何 Key）。"""

    status: str  # ok | blocked
    error_code: str | None = None
    message: str = ""
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None


def create_credential_preflight_job(
    conn,
    *,
    root_import_id: str,
    requester_id: int,
    credential_scope: str,
    user_id: int | None,
    attempt_id: int | None,
) -> int:
    """在调用方事务内为 root/scope 创建幂等预检 job（每个 scope 最多一个在途）。"""

    existing = conn.execute(
        "SELECT j.id FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = ? AND j.job_type = ? "
        "AND j.status IN ('pending', 'queued', 'running') "
        "AND json_extract(p.payload, '$.credential_scope') = ? ORDER BY j.id LIMIT 1",
        (root_import_id, PREFLIGHT_JOB_TYPE, credential_scope),
    ).fetchone()
    if existing:
        return int(existing["id"])

    payload = {
        "root_import_id": root_import_id,
        "requester_id": requester_id,
        "credential_scope": credential_scope,
        "user_id": user_id,
    }
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, "
        "root_import_id, upload_attempt_id, work_key, idempotency_key) "
        "VALUES (?, 'pending', 1, ?, ?, ?, ?, ?)",
        (
            PREFLIGHT_JOB_TYPE,
            requester_id,
            root_import_id,
            attempt_id,
            f"preflight:credential:v1:{credential_scope}",
            f"preflight:{root_import_id}:{credential_scope}:{attempt_id or 0}:{uuid4().hex}",
        ),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, _json_dumps(payload)),
    )
    return job_id


def _json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def run_credential_preflight(
    conn,
    *,
    job_id: int,
    probe=None,
    user_config_loader=None,
    global_config_loader=None,
) -> PreflightOutcome:
    """执行一次预检：解析 scope 凭据 → 探测 → 落阶段结果（幂等）。

    ``probe(credential)`` 默认使用 ``app.services.upload_credentials`` 的
    真实探测客户端；测试注入 stub 验证 401/404/超时分支。
    """

    import json

    from app.services.upload_credentials import (
        UploadCredentialError,
        resolve_upload_credentials,
    )
    from app.services.upload_repository import save_stage_result

    job = conn.execute(
        "SELECT * FROM jobs WHERE id = ? AND job_type = ?",
        (job_id, PREFLIGHT_JOB_TYPE),
    ).fetchone()
    if job is None:
        raise ValueError(f"预检 job 不存在: {job_id}")
    payload_row = conn.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
    ).fetchone()
    payload = json.loads(payload_row["payload"]) if payload_row else {}
    root_import_id = payload.get("root_import_id")
    credential_scope = payload.get("credential_scope", "user")
    user_id = payload.get("user_id")
    upload_attempt_id = job["upload_attempt_id"]
    preflight_unit = (
        f"credential:v1:scope:{credential_scope}:attempt:{int(upload_attempt_id or 0)}:"
        f"job:{int(job_id)}:run:{int(job['attempts'] or 0)}"
    )

    # 解析凭据：与提取阶段同规则（绝不跨 scope 回退；scope 只来自服务端 policy）
    try:
        credential = resolve_upload_credentials(
            credential_scope=credential_scope,
            user_id=int(user_id) if user_id is not None and credential_scope == "user" else None,
            stage="preflight",
            user_config_loader=user_config_loader,
            global_config_loader=global_config_loader,
        )
    except UploadCredentialError as exc:
        error_code = exc.code
        _mark_blocked(
            conn,
            root_import_id,
            job_id,
            error_code,
            str(exc),
            unit_key=preflight_unit,
        )
        return PreflightOutcome(status="blocked", error_code=error_code, message=str(exc))

    probe_fn = probe or _default_probe
    # AC-004：预检的物理调用独立记账（不存 Key/认证头，绑定指纹）；同一
    # root+stage 每次预检一个 call_key，配额由账本层原子预留。
    from app.services.upload_credentials import (
        CallLedgerConflict,
        complete_llm_call,
        reserve_llm_call,
    )

    call_key = (
        f"preflight:{root_import_id or job_id}:{credential_scope}:"
        f"{int(_monotonic() * 1000)}"
    )
    payer_type = "user" if credential_scope == "user" else "system"
    try:
        reserve_llm_call(
            conn,
            root_import_id=root_import_id,
            stage=PREFLIGHT_STAGE,
            unit_key=f"initial:{credential_scope}:attempt:{int(upload_attempt_id or 0)}",
            call_key=call_key,
            credential_scope=credential_scope,
            payer_type=payer_type,
            payer_user_id=int(user_id) if credential_scope == "user" else None,
            provider=credential.provider,
            model=credential.model,
            config_fingerprint=credential.config_fingerprint,
        )
    except CallLedgerConflict:
        # 同 call_key 已登记（幂等重跑），沿用既有行
        pass
    except Exception as exc:
        logger.warning("预检记账预留失败（不阻断探测，配额层兜底）: %s", exc)

    try:
        result = probe_fn(credential)
        if isinstance(result, dict) and result.get("status") == "ok":
            latency = int(result.get("latency_ms") or 0)
            save_stage_result(
                conn,
                import_id=root_import_id,
                stage=PREFLIGHT_STAGE,
                unit_key=preflight_unit,
                input_version=1,
                pipeline_version=PREFLIGHT_PIPELINE_VERSION,
                status="succeeded",
                result_json=_json_dumps(
                    {
                        "provider": result.get("provider", credential.provider),
                        "model": result.get("model") or credential.model,
                        "api_format": result.get("api_format") or credential.api_format,
                        "credential_scope": credential_scope,
                        "config_fingerprint": credential.config_fingerprint,
                        "latency_ms": latency,
                    }
                ),
                job_id=job_id,
            )
            try:
                complete_llm_call(
                    conn,
                    call_key=call_key,
                    status="succeeded",
                    input_tokens=int(result.get("input_tokens") or 0),
                    output_tokens=int(result.get("output_tokens") or 0),
                )
            except Exception as exc:
                logger.warning("预检记账完成失败（不阻断）: %s", exc)
            conn.execute(
                "UPDATE jobs SET status = 'completed', progress_current = 1, "
                "progress_total = 1, completed_at = CURRENT_TIMESTAMP, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,),
            )
            # 预检通过：清除 needs_action 阻塞，恢复提取派发（配置修复后同 root 继续）
            if root_import_id:
                conn.execute(
                    "UPDATE upload_imports SET status = 'queued', error_code = NULL, "
                    "error_message = NULL, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = 'needs_action'",
                    (root_import_id,),
                )
            return PreflightOutcome(
                status="ok",
                provider=credential.provider,
                model=credential.model,
                latency_ms=latency,
            )
        raise RuntimeError("探测未返回有效状态")
    except Exception as exc:
        text = str(exc).lower()
        if "401" in text or "invalid api key" in text or "unauthorized" in text:
            error_code = "MODEL_AUTH_INVALID"
        elif "404" in text or "not found" in text or "connection refused" in text:
            error_code = "UPSTREAM_UNAVAILABLE"
        elif "timeout" in text or "timed out" in text or "超时" in text:
            error_code = "UPSTREAM_TIMEOUT"
        else:
            error_code = "UPSTREAM_UNAVAILABLE"
        try:
            complete_llm_call(
                conn, call_key=call_key, status="failed", error_code=error_code
            )
        except Exception as ledger_exc:
            logger.warning("预检失败记账完成失败（不阻断）: %s", ledger_exc)
        _mark_blocked(
            conn,
            root_import_id,
            job_id,
            error_code,
            str(exc),
            unit_key=preflight_unit,
        )
        return PreflightOutcome(status="blocked", error_code=error_code, message=str(exc))


def _mark_blocked(
    conn,
    root_import_id: str,
    job_id: int,
    error_code: str,
    message: str,
    *,
    unit_key: str = "credential:v1",
):
    """预检失败：记录 failed 阶段结果 + 根 needs_action + job 终态失败。"""

    from app.services.upload_repository import save_stage_result

    if root_import_id:
        save_stage_result(
            conn,
            import_id=root_import_id,
            stage=PREFLIGHT_STAGE,
            unit_key=unit_key,
            input_version=1,
            pipeline_version=PREFLIGHT_PIPELINE_VERSION,
            status="failed",
            error_code=error_code,
            retryable=False,
            job_id=job_id,
        )
        conn.execute(
            "UPDATE upload_imports SET status = 'needs_action', error_code = ?, "
            "error_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (error_code, message[:500], root_import_id),
        )
    conn.execute(
        "UPDATE jobs SET status = 'failed', last_error = ?, "
        "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (message[:500], job_id),
    )


def _default_probe(credential):
    """真实 provider ping：调用用户选择的模型，而非仅查询模型列表。"""

    from app.services.llm import build_bare_client

    import asyncio

    started = _monotonic()

    async def _ping():
        from app.services.llm_protocol import _is_endpoint_mismatch

        client = build_bare_client(
            api_key=credential.api_key,
            base_url=credential.base_url,
            timeout=credential.timeout or 15,
            provider=credential.provider,
            api_format=credential.api_format,
        )
        try:
            if credential.api_format:
                formats = [credential.api_format]
            elif credential.provider == "anthropic":
                formats = ["anthropic"]
            else:
                # Auto-configured OpenAI-compatible providers are tried with
                # the two supported wire protocols. Only a clear route/protocol
                # mismatch falls through; auth/model/timeout errors stay fatal.
                formats = ["chat", "responses"]

            response = None
            selected_format = None
            for index, api_format in enumerate(formats):
                try:
                    if api_format == "anthropic":
                        response = await client.messages.create(
                            model=credential.model,
                            max_tokens=1,
                            messages=[{"role": "user", "content": "ping"}],
                        )
                    elif api_format == "responses":
                        response = await client.responses.create(
                            model=credential.model,
                            input="ping",
                            max_output_tokens=1,
                        )
                    else:
                        response = await client.chat.completions.create(
                            model=credential.model,
                            messages=[{"role": "user", "content": "ping"}],
                            max_tokens=1,
                        )
                    selected_format = api_format
                    break
                except Exception as exc:
                    if index + 1 < len(formats) and _is_endpoint_mismatch(exc):
                        continue
                    raise

            usage = getattr(response, "usage", None)
            if selected_format == "anthropic":
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            elif selected_format == "responses":
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
            else:
                input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            return {
                "status": "ok",
                "latency_ms": int((_monotonic() - started) * 1000),
                "provider": credential.provider,
                "model": credential.model,
                "api_format": selected_format,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "fingerprint": credential.config_fingerprint,
            }
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                await close()

    try:
        # Worker 调用本同步边界时已在 asyncio.to_thread 中，故可安全建 event loop。
        return asyncio.run(_ping())
    except Exception as exc:
        raise RuntimeError(f"{exc}") from exc


def _monotonic():
    import time

    return time.monotonic()
