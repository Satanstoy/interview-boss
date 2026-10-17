"""Budget detail reads only the requesting user's root ledger."""

import pytest
from app.core.auth import create_access_token


@pytest.mark.parametrize("uid", [9301, 9302, 9303])
def test_root_usage_is_owner_only_even_for_admin(client, test_db, uid):
    for user_id in [9301, 9302, 9303]:
        test_db.execute(
            "INSERT INTO users(id,username,password_hash,is_admin) VALUES(?,?,?,?)",
            (user_id, f"budget-{user_id}", "TEST_HASH", int(user_id == 9303)),
        )
    for root, owner in [("budget-own", 9301), ("budget-other", 9302)]:
        test_db.execute(
            "INSERT INTO upload_imports(id,requester_id,idempotency_key,request_hash,target_intent,source_type,pipeline_version) VALUES(?,?,?,?,'private','interview','upload-pipeline-v1')",
            (root, owner, root, root),
        )
    test_db.execute(
        "INSERT INTO upload_llm_calls(root_import_id,stage,call_key,credential_scope,payer_type,payer_user_id,status,input_tokens,output_tokens) VALUES('budget-own','extract','budget-call','user','user',9301,'succeeded',100,23)"
    )
    test_db.execute(
        "INSERT INTO upload_llm_calls(root_import_id,stage,call_key,credential_scope,payer_type,payer_user_id,status,input_tokens,output_tokens) VALUES('budget-other','extract','other-call','user','user',9302,'succeeded',999,999)"
    )
    test_db.commit()
    headers = {"Authorization": "Bearer " + create_access_token({"user_id": uid, "type": "access"})}
    response = client.get("/api/upload-imports/budget-own/budget", headers=headers)
    if uid == 9301:
        assert response.status_code == 200, response.text
        assert response.json() == {
            "import_id": "budget-own",
            "calls": 1,
            "input_tokens": 100,
            "output_tokens": 23,
            "total_tokens": 123,
            "unknown_calls": 0,
        }
    else:
        missing = client.get("/api/upload-imports/missing/budget", headers=headers)
        assert response.status_code == missing.status_code == 404
        assert response.json() == missing.json()
