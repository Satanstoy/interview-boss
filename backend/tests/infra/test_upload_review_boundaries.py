"""Review regressions against real isolated SQLite; only provider I/O is replaced."""

import json
import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.credential_preflight import run_credential_preflight
from app.services.upload_backfill import apply_backfill, plan_backfill
from app.services.upload_lifecycle import accept_upload


CONFIG = {"api_key": "TEST_PLACEHOLDER", "base_url": "http://127.0.0.1:9", "model": "stub"}


def database(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.executemany("INSERT INTO users(id,username,password_hash) VALUES(?,?,?)",
                     [(101, "review101", "x"), (202, "review202", "x")])
    conn.commit()
    return conn


def accept(conn, *, public=False):
    accepted = accept_upload(
        conn, actor_id=101, actor_is_admin=public, idempotency_key="review-boundary",
        target_intent="share" if public else "private", text="面经 TCP 三次握手",
        credential_loaders={"user": lambda _: CONFIG, "global": lambda: CONFIG},
    )
    conn.commit()
    return accepted


@pytest.mark.parametrize("limit", ["user", "system", "import"])
def test_preflight_budget_denial_never_sends_probe_or_creates_business_job(monkeypatch, limit):
    from app.services import llm_quota, upload_credentials
    conn = database()
    accepted = accept(conn, public=limit == "system")
    if limit == "user":
        monkeypatch.setattr(llm_quota, "DAILY_LLM_CALL_LIMIT", 0)
    elif limit == "system":
        monkeypatch.setattr(upload_credentials, "UPLOAD_SYSTEM_DAILY_CALL_LIMIT", 0)
    else:
        monkeypatch.setattr(upload_credentials, "UPLOAD_MAX_LLM_CALLS_PER_IMPORT", 0)
    calls = []
    outcome = run_credential_preflight(
        conn, job_id=accepted["preflight_job_ids"][0],
        user_config_loader=lambda _: CONFIG, global_config_loader=lambda: CONFIG,
        probe=lambda _: calls.append("sent") or {"status": "ok"},
    )
    assert calls == []
    assert outcome.status == "blocked" and outcome.error_code == "QUOTA_EXCEEDED"
    assert conn.execute("SELECT COUNT(*) FROM upload_llm_calls").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type='submit_import'").fetchone()[0] == 0
    conn.close()


def test_network_probe_has_durable_reservation_without_sqlite_write_lock(tmp_path):
    path = tmp_path / "preflight.db"
    conn = database(path)
    accepted = accept(conn)
    def probe(_):
        other = sqlite3.connect(path, timeout=0.05)
        assert other.execute("SELECT status FROM upload_llm_calls").fetchone() == ("reserved",)
        other.execute("UPDATE users SET username=username WHERE id=202")
        other.commit()
        other.close()
        return {"status": "ok", "input_tokens": 1, "output_tokens": 1}
    outcome = run_credential_preflight(
        conn, job_id=accepted["preflight_job_ids"][0],
        user_config_loader=lambda _: CONFIG, probe=probe,
    )
    assert outcome.status == "ok"
    conn.commit()
    assert conn.execute("SELECT status FROM upload_llm_calls").fetchone()[0] == "succeeded"
    conn.close()


def test_preflight_response_lost_records_unknown():
    conn = database()
    accepted = accept(conn)
    def probe(_):
        raise TimeoutError("request timed out after sending")
    outcome = run_credential_preflight(
        conn, job_id=accepted["preflight_job_ids"][0],
        user_config_loader=lambda _: CONFIG, probe=probe,
    )
    assert outcome.status == "blocked"
    assert conn.execute("SELECT status FROM upload_llm_calls").fetchone()[0] == "unknown"
    conn.close()


def test_preflight_lost_generation_cannot_release_business_work(tmp_path):
    from app.services.job_lifecycle import JobFenceError, claim_job_with_generation
    path = tmp_path / "stale.db"
    conn = database(path)
    accepted = accept(conn)
    job_id = accepted["preflight_job_ids"][0]
    claimed = claim_job_with_generation(conn, job_id, worker_id="review-worker")
    generation = int(claimed["lease_generation"])
    conn.commit()
    def probe(_):
        other = sqlite3.connect(path)
        other.execute("UPDATE jobs SET lease_generation=lease_generation+1 WHERE id=?", (job_id,))
        other.commit()
        other.close()
        return {"status": "ok"}
    with pytest.raises(JobFenceError):
        run_credential_preflight(conn, job_id=job_id, lease_generation=generation,
                                 user_config_loader=lambda _: CONFIG, probe=probe)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type='submit_import'").fetchone()[0] == 0
    assert conn.execute("SELECT status FROM upload_llm_calls").fetchone()[0] == "succeeded"
    conn.close()


def legacy(conn, job_id, owner=101, parent=None, status="failed", interview_id=None):
    conn.execute("INSERT INTO jobs(id,job_type,status,created_by,parent_job_id,result) VALUES(?,'submit_import',?,?,?,?)",
                 (job_id, status, owner, parent, json.dumps({"interview_id": interview_id}) if interview_id else None))


@pytest.mark.parametrize("scenario", ["cross_owner", "multiple_active", "missing_parent", "failed_without_result"])
def test_ambiguous_legacy_chain_is_reported_and_not_linked(scenario):
    conn = database()
    legacy(conn, 10)
    if scenario == "cross_owner":
        legacy(conn, 11, owner=202, parent=10)
    elif scenario == "multiple_active":
        legacy(conn, 11, parent=10, status="running")
        legacy(conn, 12, parent=10, status="queued")
    elif scenario == "missing_parent":
        conn.execute("UPDATE jobs SET parent_job_id=999 WHERE id=10")
    conn.commit()
    before = [tuple(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]
    plan = plan_backfill(conn)
    assert plan["ambiguous"] and not plan["candidates"]
    apply_backfill(conn, manifest=plan, expected_manifest_hash=plan["manifest_hash"])
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0
    assert [tuple(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")] == before
    conn.close()


def test_completed_legacy_result_remains_completed_and_idempotent():
    conn = database()
    conn.execute("INSERT INTO interview(id,url,owner_id,status) VALUES(1,'http://example.test/1',101,'approved')")
    legacy(conn, 10, status="completed", interview_id=1)
    conn.commit()
    plan = plan_backfill(conn)
    assert not plan["ambiguous"]
    first = apply_backfill(conn, manifest=plan, expected_manifest_hash=plan["manifest_hash"])
    second_plan = plan_backfill(conn)
    second = apply_backfill(conn, manifest=second_plan, expected_manifest_hash=second_plan["manifest_hash"])
    assert first["imports_created"] == 1 and second["imports_created"] == 0
    assert tuple(conn.execute("SELECT requester_id,status,interview_id FROM upload_imports").fetchone()) == (101, "completed", 1)
    conn.close()
