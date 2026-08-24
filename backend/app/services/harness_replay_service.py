"""Read-only Harness 2.0 replay, Golden Trace and Shadow Eval services.

Replay intentionally has no provider dependency.  It consumes the immutable
Attempt/Artifact/Event records written by the production Harness and returns a
trace that can be judged or compared without mutating Session, Ledger,
Transcript, or the user-facing event stream.
"""

from __future__ import annotations

import inspect
import json
import copy
import hashlib
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.db.connection import get_db_connection


class HarnessArtifactScopeError(PermissionError):
    """A caller attempted to read artifacts outside its projection scope."""


_IDENTITY_FIELDS = (
    "harness_version",
    "prompt_schema",
    "stable_prefix_hash",
    "context_pack_hash",
    "skill_hashes",
    "provider",
    "model",
    "sampling_hash",
    "request_hash",
)

GOLDEN_TRACE_SCENARIOS = (
    "normal",
    "incomplete_answer",
    "off_topic",
    "refusal",
    "skip_question",
    "end_interview",
    "multilingual",
    "question_bank_empty",
    "provider_timeout",
    "schema_error",
    "prompt_injection",
    "edit_revision",
    "sse_recovery",
)

_GOLDEN_TRACE_PATH = (
    Path(__file__).resolve().parents[3]
    / "evals"
    / "golden-traces"
    / "interview-harness-2.0.json"
)


def load_golden_trace_contract(scenario: str | None = None) -> dict[str, Any]:
    """Load and validate the versioned Golden Trace catalog from the repo."""
    try:
        catalog = json.loads(_GOLDEN_TRACE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Harness 2.0 Golden Trace catalog is unavailable") from exc
    if catalog.get("harness") != "interview-harness@2.0":
        raise ValueError("Golden Trace catalog has the wrong Harness version")
    if catalog.get("trace_schema") != "golden-trace-v1":
        raise ValueError("Golden Trace catalog has the wrong schema")
    entries = catalog.get("scenarios")
    if not isinstance(entries, list):
        raise ValueError("Golden Trace catalog scenarios must be a list")
    by_key = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise ValueError("Golden Trace scenario is malformed")
        gates = entry.get("hard_gates")
        if not isinstance(gates, list) or not all(isinstance(gate, str) for gate in gates):
            raise ValueError(f"Golden Trace hard gates are malformed: {entry.get('key')}")
        by_key[entry["key"]] = dict(entry)
    if tuple(by_key) != GOLDEN_TRACE_SCENARIOS:
        raise ValueError("Golden Trace catalog does not match Harness 2.0 scenarios")
    if scenario is None:
        return {**catalog, "scenarios": [by_key[key] for key in GOLDEN_TRACE_SCENARIOS]}
    if scenario not in by_key:
        raise ValueError(f"unknown Golden Trace scenario: {scenario}")
    return {"harness": catalog["harness"], **by_key[scenario]}


def _decode_content(raw: str, *, allow_sensitive: bool) -> Any:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if isinstance(value, dict) and value.get("encoding") == "fernet":
        if not allow_sensitive:
            raise HarnessArtifactScopeError("sensitive artifact requires audit scope")
        from app.services.encryption import decrypt_value

        try:
            value = json.loads(decrypt_value(value.get("ciphertext") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return value


def list_harness_artifacts(
    *,
    turn_id: str,
    user_id: int,
    conversation_id: str,
    scope: str = "user",
    audit_authorized: bool = False,
) -> list[dict[str, Any]]:
    """Read an artifact projection with an explicit visibility boundary.

    ``user`` only returns user-visible artifacts.  ``audit`` is deliberately
    opt-in and is intended for internal replay/evaluation workers, never a
    normal conversation API response.
    """
    if scope not in {"user", "audit", "model"}:
        raise ValueError("invalid Harness artifact scope")
    if scope != "user" and not audit_authorized:
        raise HarnessArtifactScopeError("audit/model artifact scope is internal only")
    visibility = {"user": "user", "model": "model", "audit": None}[scope]
    with get_db_connection() as conn:
        params: list[Any] = [turn_id, int(user_id), conversation_id]
        where = "turn_id = ? AND user_id = ? AND conversation_id = ?"
        if visibility:
            where += " AND visibility = ?"
            params.append(visibility)
        elif scope == "audit":
            where += " AND visibility IN ('audit', 'model')"
        rows = conn.execute(
            "SELECT * FROM interview_artifacts WHERE "
            + where
            + " ORDER BY rowid ASC",
            params,
        ).fetchall()
    allow_sensitive = scope != "user" and audit_authorized
    result = []
    for row in rows:
        item = dict(row)
        item["content"] = _decode_content(
            item.pop("content_json", "{}"), allow_sensitive=allow_sensitive
        )
        result.append(item)
    return result


def _manifest_from_artifacts(artifacts: list[dict[str, Any]], turn: dict[str, Any]) -> dict[str, Any]:
    manifests = [item["content"] for item in artifacts if item["artifact_type"] == "context_manifest"]
    manifest = dict(manifests[-1]) if manifests and isinstance(manifests[-1], dict) else {}
    manifest.setdefault(
        "harness_version",
        turn.get("harness_version") if turn.get("has_harness_event") else "legacy",
    )
    if turn.get("context_pack_hash"):
        manifest.setdefault("context_pack_hash", turn["context_pack_hash"])
    if turn.get("stable_prefix_hash"):
        manifest.setdefault("stable_prefix_hash", turn["stable_prefix_hash"])
    return manifest


def _manifests_by_attempt(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        if item.get("artifact_type") != "context_manifest" or not item.get("attempt_id"):
            continue
        content = item.get("content")
        if isinstance(content, dict):
            manifests[str(item["attempt_id"])] = content
    return manifests


def _attempt_identity(attempt: dict[str, Any]) -> dict[str, Any]:
    try:
        skill_hashes = json.loads(attempt.get("skill_hashes_json") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        skill_hashes = []
    if not isinstance(skill_hashes, list):
        skill_hashes = []
    return {
        "harness_version": attempt.get("harness_version") or "",
        "prompt_schema": attempt.get("prompt_schema") or "",
        "context_pack_hash": attempt.get("context_pack_hash") or "",
        "skill_hashes": sorted(str(item) for item in skill_hashes),
        "provider": attempt.get("provider") or "",
        "model": attempt.get("model") or "",
        "sampling_hash": attempt.get("sampling_hash") or "",
        "request_hash": attempt.get("request_hash") or "",
    }


def _load_replay_snapshot(
    *, turn_id: str, user_id: int, conversation_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Read Turn, Artifact, Attempt and Event rows from one DB snapshot."""
    with get_db_connection() as conn:
        conn.execute("BEGIN")
        try:
            turn_row = conn.execute(
                "SELECT t.id, t.harness_status, c.harness_version, t.context_pack_hash, "
                "t.stable_prefix_hash, CASE WHEN EXISTS ("
                "SELECT 1 FROM interview_events e WHERE e.turn_id = t.id "
                "AND e.event_type = 'turn.started' "
                "AND json_extract(e.payload_json, '$.harness_version') = '2.0'"
                ") THEN 1 ELSE 0 END AS has_harness_event FROM chat_turns t "
                "JOIN chat_conversations c ON c.id = t.conversation_id "
                "WHERE t.id = ? AND t.user_id = ? AND t.conversation_id = ?",
                (turn_id, int(user_id), conversation_id),
            ).fetchone()
            if not turn_row:
                raise LookupError("turn not found or not owned")

            artifact_rows = conn.execute(
                "SELECT * FROM interview_artifacts WHERE turn_id = ? AND user_id = ? "
                "AND conversation_id = ? AND visibility IN ('audit', 'model') "
                "ORDER BY rowid ASC",
                (turn_id, int(user_id), conversation_id),
            ).fetchall()
            artifacts = []
            for row in artifact_rows:
                item = dict(row)
                item["content"] = _decode_content(
                    item.pop("content_json", "{}"), allow_sensitive=True
                )
                artifacts.append(item)

            attempt_rows = conn.execute(
                "SELECT * FROM interview_attempts WHERE turn_id = ? AND user_id = ? "
                "AND conversation_id = ? ORDER BY rowid ASC",
                (turn_id, int(user_id), conversation_id),
            ).fetchall()
            attempts = [dict(row) for row in attempt_rows]

            event_rows = conn.execute(
                "SELECT event_id, sequence, event_type, action_id, phase, channel, "
                "visibility, schema_version, payload_json, created_at "
                "FROM interview_events WHERE turn_id = ? AND user_id = ? "
                "AND conversation_id = ? ORDER BY sequence ASC",
                (turn_id, int(user_id), conversation_id),
            ).fetchall()
            events = []
            for row in event_rows:
                item = dict(row)
                try:
                    item["payload"] = json.loads(item.pop("payload_json") or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["payload"] = {}
                item["type"] = item["event_type"]
                events.append(item)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return dict(turn_row), artifacts, attempts, events


def recorded_replay(
    *,
    turn_id: str,
    user_id: int,
    conversation_id: str,
    expected_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic replay trace without calling a model/provider."""
    turn, artifacts, attempts, events = _load_replay_snapshot(
        turn_id=turn_id, user_id=user_id, conversation_id=conversation_id
    )
    responses_by_attempt = {
        item["attempt_id"]: item["content"]
        for item in artifacts
        if item["artifact_type"] in {"provider_response", "raw_provider_response"}
        and item.get("attempt_id")
    }
    requests_by_attempt = {
        item["attempt_id"]: item["content"]
        for item in artifacts
        if item["artifact_type"] == "provider_request" and item.get("attempt_id")
    }
    manifest = _manifest_from_artifacts(artifacts, turn)
    manifests_by_attempt = _manifests_by_attempt(artifacts)
    mismatches = []
    if not turn.get("has_harness_event"):
        mismatches.append(
            {
                "code": "LEGACY_PROVENANCE",
                "field": "harness_version",
                "actual": manifest.get("harness_version"),
            }
        )
    expected = expected_manifest or {}
    for field in _IDENTITY_FIELDS:
        if field not in expected:
            continue
        if manifest.get(field) != expected.get(field):
            mismatches.append(
                {"field": field, "expected": expected.get(field), "actual": manifest.get(field)}
            )

    calls = []
    for attempt in attempts:
        attempt_identity = _attempt_identity(attempt)
        attempt_manifest = manifests_by_attempt.get(str(attempt["id"]))
        for field, actual in attempt_identity.items():
            expected_attempt_value = (
                attempt_manifest.get(field) if attempt_manifest is not None else None
            )
            if expected_attempt_value is None:
                continue
            normalized_expected = (
                sorted(str(item) for item in expected_attempt_value)
                if field == "skill_hashes" and isinstance(expected_attempt_value, list)
                else expected_attempt_value
            )
            if actual != normalized_expected:
                mismatches.append(
                    {
                        "source": "attempt",
                        "attempt_id": attempt["id"],
                        "field": field,
                        "expected": normalized_expected,
                        "actual": actual,
                    }
                )
        calls.append(
            {
                "attempt_id": attempt["id"],
                "action_id": attempt["action_id"],
                "attempt_no": int(attempt["attempt_no"]),
                "status": attempt["status"],
                "call_mode": attempt["call_mode"],
                "provider": attempt["provider"],
                "model": attempt["model"],
                "context_pack_hash": attempt["context_pack_hash"],
                "request_hash": attempt["request_hash"],
                "harness_version": attempt.get("harness_version") or "",
                "prompt_schema": attempt.get("prompt_schema") or "",
                "sampling_hash": attempt.get("sampling_hash") or "",
                "skill_hashes": attempt_identity["skill_hashes"],
                "provider_request": requests_by_attempt.get(attempt["id"]),
                "provider_response": responses_by_attempt.get(attempt["id"]),
            }
        )
    return {
        "turn_run_id": turn_id,
        "harness_status": turn["harness_status"],
        "manifest": manifest,
        "mismatches": mismatches,
        "replayable": not mismatches and bool(calls),
        "calls": calls,
        "events": events,
        "snapshot_incomplete": turn.get("harness_status") not in {
            "completed",
            "failed",
            "cancelled",
            "timed_out",
            "budget_exhausted",
        },
    }


def validate_golden_trace(
    replay: dict[str, Any], contract: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Apply deterministic hard gates to a recorded trace."""
    contract = contract if isinstance(contract, dict) else {}
    scenario_contract = {}
    if contract.get("scenario"):
        scenario_contract = load_golden_trace_contract(str(contract["scenario"]))
    violations: list[dict[str, Any]] = []
    if not replay.get("replayable"):
        violations.append({"code": "REPLAY_IDENTITY_MISMATCH", "severity": "hard"})
    allowed_modes = {"observe_propose", "write_response", "repair_response", "validate_output"}
    for call in replay.get("calls") or []:
        if call.get("call_mode") not in allowed_modes:
            violations.append({"code": "ILLEGAL_CALL_MODE", "severity": "hard"})
        if call.get("status") == "succeeded" and call.get("provider_response") is None:
            violations.append({"code": "MISSING_PROVIDER_RESPONSE", "severity": "hard"})
    for event in replay.get("events") or []:
        payload = event.get("payload") or {}
        for key, code in (
            ("unauthorized_tool", "UNAUTHORIZED_TOOL"),
            ("prompt_leak", "PROMPT_LEAK"),
            ("ledger_pollution", "LEDGER_POLLUTION"),
            ("illegal_phase", "ILLEGAL_PHASE"),
            ("wrong_question_binding", "WRONG_QUESTION_BINDING"),
            ("unvalidated_transcript", "UNVALIDATED_TRANSCRIPT"),
        ):
            if payload.get(key):
                violations.append({"code": code, "severity": "hard", "event_id": event.get("event_id")})
    expected_scenario = contract.get("scenario")
    actual_scenario = (replay.get("manifest") or {}).get("scenario")
    if expected_scenario and actual_scenario and expected_scenario != actual_scenario:
        violations.append({"code": "SCENARIO_MISMATCH", "severity": "hard"})
    return {
        "passed": not violations,
        "hard_gate_status": "passed" if not violations else "failed",
        "violations": violations,
        "scenario": actual_scenario or expected_scenario or "unspecified",
        "hard_gates": scenario_contract.get("hard_gates", []),
    }


async def run_shadow_eval(
    replay: dict[str, Any],
    judge: Callable[[dict[str, Any]], Any] | Callable[[dict[str, Any]], Awaitable[Any]],
) -> dict[str, Any]:
    """Run a judge over a detached replay DTO and reject production writes."""
    turn_id = str(replay.get("turn_run_id") or "")
    before = _production_state_digest(turn_id) if turn_id else ""
    detached_replay = copy.deepcopy(replay)
    try:
        result = judge(detached_replay)
        if inspect.isawaitable(result):
            result = await result
    finally:
        after = _production_state_digest(turn_id) if turn_id else ""
        if before != after:
            raise RuntimeError("SHADOW_EVAL_MUTATED_PRODUCTION_STATE")
    return {"read_only": True, "turn_run_id": replay.get("turn_run_id"), "judge": result}


def _production_state_digest(turn_id: str) -> str:
    """Hash production rows touched by a Shadow Judge for mutation detection."""
    with get_db_connection() as conn:
        turn = conn.execute(
            "SELECT conversation_id FROM chat_turns WHERE id = ?", (turn_id,)
        ).fetchone()
        if not turn:
            return "missing"
        conversation_id = turn["conversation_id"]
        snapshots = []
        for table, where, params in (
            ("chat_turns", "id = ?", (turn_id,)),
            ("chat_messages", "conversation_id = ?", (conversation_id,)),
            ("interview_ledgers", "conversation_id = ?", (conversation_id,)),
            ("interview_actions", "turn_id = ?", (turn_id,)),
            ("interview_attempts", "turn_id = ?", (turn_id,)),
            ("interview_artifacts", "turn_id = ?", (turn_id,)),
            ("interview_events", "turn_id = ?", (turn_id,)),
        ):
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {where} ORDER BY rowid ASC", params
            ).fetchall()
            snapshots.append((table, [dict(row) for row in rows]))
    encoded = json.dumps(snapshots, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "GOLDEN_TRACE_SCENARIOS",
    "HarnessArtifactScopeError",
    "load_golden_trace_contract",
    "list_harness_artifacts",
    "recorded_replay",
    "run_shadow_eval",
    "validate_golden_trace",
]
