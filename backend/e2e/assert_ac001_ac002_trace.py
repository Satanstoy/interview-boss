"""Validate the real AC-001 share-to-public task-target relationship."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


PRIVATE_COMPANY = "AC001_TASK_LOCATOR_REAL_STACK 公司"
EXPECTED_QUESTION = "AC001_TASK_LOCATOR_REAL_STACK：系统怎样验证异步任务的幂等恢复？"
EXPECTED_POSITION = "AC001 数据 P2"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main(trace_path: str) -> None:
    if trace_path == "-":
        trace = json.load(sys.stdin)
    else:
        with open(trace_path, encoding="utf-8") as stream:
            trace = json.load(stream)

    import_id = str(trace["import_id"])
    request_id = int(trace["contribution_request_id"])
    private_id = int(trace["private_interview_id"])
    public_id = int(trace["public_interview_id"])
    owner_id = int(trace["user_id"])
    require(trace["shared_question"] == EXPECTED_QUESTION, "browser question differs from fixture")
    require(int(trace["p2_position_id"]) > 0, "browser trace has no P2 position")
    require(public_id != private_id, "task target aliases the private source")

    with get_db_connection() as conn:
        root = conn.execute(
            "SELECT id, requester_id, target_intent, source_type, position_name, status, "
            "interview_id, contribution_request_id FROM upload_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        require(root is not None, "upload root is missing")
        require(int(root["requester_id"]) == owner_id, "upload root owner differs from browser user")
        require(root["target_intent"] == "share", "upload root lost share intent")
        require(root["source_type"] == "interview", "upload root source type is not interview")
        require(root["position_name"] == EXPECTED_POSITION, "upload root position differs from P2")
        require(int(root["interview_id"] or 0) == private_id, "root does not reference private interview")
        require(int(root["contribution_request_id"] or 0) == request_id,
                "root does not reference the reviewed contribution")

        private = conn.execute(
            "SELECT id, owner_id, company, job_position FROM interview "
            "WHERE id = ? AND deleted_at IS NULL",
            (private_id,),
        ).fetchone()
        require(private is not None, "private source interview is missing")
        require(int(private["owner_id"]) == owner_id, "private source owner differs")
        require(private["company"] == PRIVATE_COMPANY, "private source company differs")
        require(private["job_position"] == EXPECTED_POSITION, "private source position differs")

        private_detail = conn.execute(
            "SELECT id, question, source_ordinal FROM questions_detail "
            "WHERE interview_id = ? AND import_id = ? AND deleted_at IS NULL",
            (private_id, import_id),
        ).fetchall()
        require(len(private_detail) == 1, "private source must retain exactly one extracted question")
        source_detail = private_detail[0]
        require(source_detail["question"] == EXPECTED_QUESTION, "private question differs from extraction")
        require(int(source_detail["source_ordinal"] or 0) == 1, "private question ordinal changed")

        contribution = conn.execute(
            "SELECT id, requester_id, source_type, source_id, status, public_interview_id "
            "FROM public_contribution_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        require(contribution is not None, "public contribution request is missing")
        require(int(contribution["requester_id"]) == owner_id, "contribution requester differs")
        require(contribution["source_type"] == "interview", "contribution source type differs")
        require(int(contribution["source_id"]) == private_id, "contribution source is not private interview")
        require(contribution["status"] == "published", "contribution is not published")
        require(int(contribution["public_interview_id"] or 0) == public_id,
                "contribution does not reference browser's public interview")

        item = conn.execute(
            "SELECT i.status, i.source_item_id, i.public_detail_id, d.interview_id, "
            "d.owner_id, d.question FROM public_contribution_items i "
            "LEFT JOIN questions_detail d ON d.id = i.public_detail_id "
            "WHERE i.request_id = ? ORDER BY i.ordinal LIMIT 1",
            (request_id,),
        ).fetchone()
        require(item is not None, "contribution item is missing")
        require(item["status"] == "published", "contribution question was not published")
        require(int(item["source_item_id"]) == int(source_detail["id"]),
                "contribution item is disconnected from the private question")
        require(item["public_detail_id"] is not None, "published item has no public detail")
        require(int(item["interview_id"]) == public_id, "public detail is attached to another interview")
        require(item["owner_id"] is None, "public detail is not public-owned")
        require(item["question"] == EXPECTED_QUESTION, "public question differs from reviewed source")

        public = conn.execute(
            "SELECT id, owner_id, company, job_position, status, publish_status "
            "FROM interview WHERE id = ? AND deleted_at IS NULL",
            (public_id,),
        ).fetchone()
        require(public is not None, "public interview is missing")
        require(public["owner_id"] is None, "published target has an owner")
        require(public["company"] == "", "unapproved private company leaked into public interview")
        require(public["job_position"] == EXPECTED_POSITION, "public interview position differs")
        require(public["status"] == "approved", "public interview is not approved")
        require(public["publish_status"] == "published", "public interview is not published")

        result = {
            "upload_import": {
                "id": root["id"],
                "requester_id": int(root["requester_id"]),
                "target_intent": root["target_intent"],
                "status": root["status"],
                "private_interview_id": private_id,
                "contribution_request_id": request_id,
            },
            "private_interview": {
                "id": private_id,
                "owner_id": owner_id,
                "job_position": private["job_position"],
                "question_detail_id": int(source_detail["id"]),
            },
            "contribution": {
                "id": request_id,
                "status": contribution["status"],
                "source_interview_id": private_id,
                "public_interview_id": public_id,
            },
            "public_interview": {
                "id": public_id,
                "owner_id": None,
                "job_position": public["job_position"],
                "public_detail_id": int(item["public_detail_id"]),
                "status": public["status"],
                "publish_status": public["publish_status"],
            },
            "task_target_matches_public_interview": int(trace["task_result_target"]["entity_id"]) == public_id,
        }
        require(result["task_target_matches_public_interview"], "task card target does not match public interview")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: assert_ac001_ac002_trace.py BROWSER_TRACE.json")
    main(sys.argv[1])
