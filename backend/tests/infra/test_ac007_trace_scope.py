"""Shared real-stack scenarios must not count another owner's attempts."""

from e2e.assert_ac007_owner_retry_trace import count_owner_attempts


def test_owner_retry_trace_ignores_other_scenarios_and_detects_extra_attempt(test_db):
    for owner in (9601, 9602):
        test_db.execute(
            "INSERT INTO users(id,username,password_hash) VALUES(?,?, 'TEST_HASH')",
            (owner, f"trace-{owner}"),
        )
        root = f"trace-{owner}"
        test_db.execute(
            "INSERT INTO upload_imports(id,requester_id,idempotency_key,request_hash,target_intent,source_type,pipeline_version) VALUES(?,?,?,?,'private','interview','upload-pipeline-v1')",
            (root, owner, root, root),
        )
        for number in (1, 2):
            test_db.execute(
                "INSERT INTO upload_attempts(import_id,attempt_no,status,requested_by) VALUES(?,?,'completed',?)",
                (root, number, owner),
            )
    test_db.commit()
    assert count_owner_attempts(test_db, 9601) == 2
    test_db.execute(
        "INSERT INTO upload_attempts(import_id,attempt_no,status,requested_by) VALUES('trace-9601',3,'completed',9601)"
    )
    test_db.commit()
    assert count_owner_attempts(test_db, 9601) == 3
