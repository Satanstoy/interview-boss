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
PREFLIGHT_STAGE = "credential_preflight"
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
        "AND j.upload_attempt_id IS ? "
        "AND j.status IN ('pending', 'queued', 'running') "
        "AND json_extract(p.payload, '$.credential_scope') = ? ORDER BY j.id LIMIT 1",
        (root_import_id, PREFLIGHT_JOB_TYPE, attempt_id, credential_scope),
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


def create_initial_submit_job_if_ready(
    conn, *, root_import_id: str, attempt_id: int
) -> int | None:
    """Atomically create the first business job after all required probes pass."""

    import json

    from app.services.job_lifecycle import get_successful_upload_preflight
    from app.services.upload_lifecycle import FIRST_WORK_KEY, SUBMIT_PHASES, UPLOAD_JOB_TYPE
    from app.services.upload_policy import initial_preflight_scopes

    root = conn.execute(
        "SELECT * FROM upload_imports WHERE id = ?", (root_import_id,)
    ).fetchone()
    if root is None:
        return None
    attempt = conn.execute(
        "SELECT id FROM upload_attempts WHERE id = ? AND import_id = ? AND status = 'active'",
        (attempt_id, root_import_id),
    ).fetchone()
    if attempt is None:
        return None

    try:
        policy = json.loads(root["policy_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        policy = {}
    required_scopes = initial_preflight_scopes(policy)
    for scope in required_scopes:
        if get_successful_upload_preflight(
            conn,
            root_import_id=root_import_id,
            attempt_id=attempt_id,
            credential_scope=scope,
        ) is None:
            return None

    existing = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND upload_attempt_id = ? "
        "AND job_type = ? ORDER BY id LIMIT 1",
        (root_import_id, attempt_id, UPLOAD_JOB_TYPE),
    ).fetchone()
    if existing:
        return int(existing["id"])

    payload = json.loads(root["payload_json"] or "{}")
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, progress_total, "
        "root_import_id, upload_attempt_id, work_key, idempotency_key) "
        "VALUES (?, 'pending', ?, ?, ?, ?, ?, ?)",
        (
            UPLOAD_JOB_TYPE,
            int(root["requester_id"]),
            len(SUBMIT_PHASES),
            root_import_id,
            attempt_id,
            FIRST_WORK_KEY,
            f"initial:{root_import_id}:{attempt_id}:{FIRST_WORK_KEY}",
        ),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, json.dumps(payload, ensure_ascii=False)),
    )
    conn.execute(
        "UPDATE upload_imports SET status = 'queued', error_code = NULL, "
        "error_message = NULL, revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND current_attempt_no = ?",
        (root_import_id, root["current_attempt_no"]),
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
    lease_generation: int | None = None,
) -> PreflightOutcome:
    """执行一次预检：解析 scope 凭据 → 探测 → 落阶段结果（幂等）。

    ``probe(credential)`` 默认使用 ``app.services.upload_credentials`` 的
    真实探测客户端；测试注入 stub 验证 401/404/超时分支。
    """

    import json
    from app.services.job_lifecycle import JobFenceError, assert_job_fence

    def begin_business_settlement():
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        if lease_generation is not None:
            assert_job_fence(conn, job_id, lease_generation)

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
            stage=PREFLIGHT_STAGE,
            user_config_loader=user_config_loader,
            global_config_loader=global_config_loader,
        )
    except UploadCredentialError as exc:
        error_code = exc.code
        begin_business_settlement()
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
        complete_llm_call,
        reserve_llm_call,
    )

    call_key = f"preflight:{root_import_id or job_id}:{credential_scope}:{uuid4().hex}"
    payer_type = "user" if credential_scope == "user" else "system"
    begin_business_settlement()
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
    except UploadCredentialError as exc:
        conn.rollback()
        begin_business_settlement()
        _mark_blocked(conn, root_import_id, job_id, exc.code, str(exc), unit_key=preflight_unit)
        return PreflightOutcome(status="blocked", error_code=exc.code, message=str(exc))
    except Exception:
        conn.rollback()
        raise
    # Publish the reservation before provider I/O; never hold SQLite's writer
    # lock while waiting for a remote ping. Settlement begins a new transaction.
    conn.commit()

    from app.services.upload_llm_accounting import _is_unknown_provider_outcome
    from app.services.upload_retry_budget import normalize_upload_error_code, safe_upload_error_message

    provider_error = None
    try:
        result = probe_fn(credential)
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise RuntimeError("探测未返回有效状态")
    except Exception as exc:
        provider_error = exc
        result = {}

    error_code = normalize_upload_error_code(provider_error) if provider_error else None
    cause = (provider_error.__cause__ or provider_error) if provider_error else None
    ledger_status = (
        "unknown" if cause and _is_unknown_provider_outcome(cause)
        else "failed" if provider_error else "succeeded"
    )
    complete_llm_call(
        conn, call_key=call_key, status=ledger_status, error_code=error_code,
        input_tokens=None if provider_error else int(result.get("input_tokens") or 0),
        output_tokens=None if provider_error else int(result.get("output_tokens") or 0),
    )
    conn.commit()
    try:
        begin_business_settlement()
    except JobFenceError:
        conn.rollback()
        raise
    if provider_error:
        safe_message = safe_upload_error_message(error_code)
        _mark_blocked(conn, root_import_id, job_id, error_code, safe_message, unit_key=preflight_unit)
        return PreflightOutcome(status="blocked", error_code=error_code, message=safe_message)

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
    conn.execute(
        "UPDATE jobs SET status = 'completed', progress_current = 1, "
        "progress_total = 1, completed_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )
    if root_import_id and upload_attempt_id is not None:
        # 只有本 attempt 的全部 policy scopes 通过后，才在同一事务
        # 创建首个业务 job 并解除 needs_action。
        create_initial_submit_job_if_ready(
            conn,
            root_import_id=root_import_id,
            attempt_id=int(upload_attempt_id),
        )
        # contracts §5：修复阻塞 scope 后从同一 root 恢复。初始阶段尚未
        # 全通过时仍保留 needs_action；公共阶段（私人阶段已结束）只需该
        # 阶段 scope 通过即可放行待派发的聚类工作。
        release_root_after_preflight_success(
            conn,
            root_import_id=root_import_id,
            attempt_id=int(upload_attempt_id),
        )
    return PreflightOutcome(
        status="ok",
        provider=credential.provider,
        model=credential.model,
        latency_ms=latency,
    )


def release_root_after_preflight_success(
    conn, *, root_import_id: str, attempt_id: int
) -> bool:
    """预检成功后解除 ``needs_action``（contracts §5：修复正确 scope 后从同一 root 恢复）。

    释放门槛按**当前阶段**判定，而不是一律要求全部初始 scope：

    - 该 attempt 仍有待派发的聚类工作 → 只要求这些 job payload 里的 scope 预检成功
      （私人阶段已结束，重跑初始 scope 无意义）；
    - 否则 → 要求 policy 的全部初始 scope 预检成功（AC-004：预检未全通过不得派发提取）。

    额外安全条件：本 attempt 上**任何已登记的预检 scope 都必须成功**，避免某个
    scope 仍失败时提前把 root 从 needs_action 放行。

    返回是否解除了阻塞。
    """

    import json as _json

    from app.services.job_lifecycle import get_successful_upload_preflight
    from app.services.upload_policy import initial_preflight_scopes

    root = conn.execute(
        "SELECT status, policy_json FROM upload_imports WHERE id = ?",
        (root_import_id,),
    ).fetchone()
    if root is None or root["status"] != "needs_action":
        return False

    registered_scopes = {
        str(row["scope"])
        for row in conn.execute(
            "SELECT json_extract(p.payload, '$.credential_scope') AS scope "
            "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
            "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' "
            "AND j.upload_attempt_id IS ?",
            (root_import_id, attempt_id),
        ).fetchall()
        if row["scope"]
    }

    pending_scopes = {
        str(row["scope"])
        for row in conn.execute(
            "SELECT json_extract(p.payload, '$.credential_scope') AS scope "
            "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
            "WHERE j.root_import_id = ? AND j.upload_attempt_id IS ? "
            "AND j.job_type = 'cluster_batch' "
            "AND j.status IN ('pending', 'queued', 'running')",
            (root_import_id, attempt_id),
        ).fetchall()
        if row["scope"]
    }

    if pending_scopes:
        required = set(pending_scopes)
    else:
        try:
            policy = _json.loads(root["policy_json"] or "{}")
        except (TypeError, ValueError):
            policy = {}
        required = set(initial_preflight_scopes(policy))
    required |= registered_scopes

    if not required:
        return False
    for scope in sorted(required):
        if get_successful_upload_preflight(
            conn,
            root_import_id=root_import_id,
            attempt_id=attempt_id,
            credential_scope=scope,
        ) is None:
            return False

    conn.execute(
        "UPDATE upload_imports SET status = 'queued', error_code = NULL, "
        "error_message = NULL, revision = revision + 1, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'needs_action'",
        (root_import_id,),
    )
    return True


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
            "error_message = ?, revision = revision + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
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
