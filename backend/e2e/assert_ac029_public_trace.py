"""Validate and print the disposable AC-029 item-to-canonical data trace."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


SOURCE_QUESTIONS = {
    10: "Agent 与普通工作流的核心区别是什么？",
    20: "多智能体系统如何设计任务协作？",
    30: "RAG 检索结果不相关时如何定位问题？",
    40: "Agent 执行链路出现死循环如何自动恢复？ AC029_FAIL_PUBLIC_ORDINAL_40",
    50: "MCP 与 Function Calling 有哪些区别？",
}
EDITED_QUESTION = "AC029 管理员修订后的题面"
EXCLUDED_SOURCE_ORDINAL = 50
FAILED_SOURCE_ORDINAL = 40
PRESEEDED_CANONICAL = SOURCE_QUESTIONS[20]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main(import_id: str, request_id: int, baseline: list | None = None) -> None:
    with get_db_connection() as conn:
        root = conn.execute(
            "SELECT id, requester_id, target_intent, source_type, interview_id, "
            "contribution_request_id, policy_json FROM upload_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        require(root is not None, "upload root is missing")
        require(root["target_intent"] == "share", "root did not preserve share intent")
        require(root["source_type"] == "interview", "root source type is not interview")
        require(root["interview_id"] is not None, "private source interview is missing")
        require(root["contribution_request_id"] == request_id, "root/request link differs")
        policy = json.loads(root["policy_json"] or "{}")
        require(policy.get("target_intent") in (None, "share"), "policy target is not share")

        attempts = conn.execute(
            "SELECT id, attempt_no FROM upload_attempts WHERE import_id = ? ORDER BY attempt_no",
            (import_id,),
        ).fetchall()
        require(len(attempts) == 1 and int(attempts[0]["attempt_no"]) == 1,
                "same upload created more than one attempt")

        private_interview = conn.execute(
            "SELECT id, owner_id FROM interview WHERE id = ? AND deleted_at IS NULL",
            (root["interview_id"],),
        ).fetchone()
        require(private_interview is not None, "private interview is missing or deleted")
        require(int(private_interview["owner_id"]) == int(root["requester_id"]),
                "private interview owner differs from uploader")
        private_details = conn.execute(
            "SELECT id, question, cat1, cat2, tags, source_ordinal FROM questions_detail "
            "WHERE interview_id = ? AND import_id = ? AND deleted_at IS NULL "
            "ORDER BY source_ordinal",
            (root["interview_id"], import_id),
        ).fetchall()
        require([int(row["source_ordinal"]) for row in private_details] == [10, 20, 30, 40, 50],
                "private question ordinals changed")
        require([row["question"] for row in private_details] == list(SOURCE_QUESTIONS.values()),
                "private question text differs from deterministic extract")
        require(all(row["cat1"] == "B.Agent与LLM应用" for row in private_details),
                "private category 1 differs from the system taxonomy")
        require(all(row["cat2"] == "B1.Agent架构与范式" for row in private_details),
                "private category 2 differs from the system taxonomy")

        require(all(row["tags"] == "Agent架构设计" for row in private_details),
                "private tags differ from deterministic classification")

        private_canonical = conn.execute(
            "SELECT canonical_id, canonical_scope, status FROM question_resolutions "
            "WHERE detail_id = ? AND occurrence_scope = 'private' "
            "AND occurrence_owner_id = ? AND invalidated_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (int(private_details[1]["id"]), int(root["requester_id"])),
        ).fetchone()
        preseed = conn.execute(
            "SELECT id, question, frequency, sources FROM question_bank "
            "WHERE question = ? AND owner_id IS NULL AND status = 'approved' "
            "AND deleted_at IS NULL ORDER BY id LIMIT 1",
            (PRESEEDED_CANONICAL,),
        ).fetchone()
        require(preseed is not None, "preseeded public canonical is missing")
        require(private_canonical is not None, "private matching resolution is missing")
        require(int(private_canonical["canonical_id"]) == int(preseed["id"]),
                "private resolution did not reuse the preexisting public canonical")
        require(private_canonical["canonical_scope"] == "public", "private resolution scope is not public")

        contribution = conn.execute(
            "SELECT id, status, public_interview_id, snapshot_json, review_projection_json "
            "FROM public_contribution_requests WHERE id = ? AND requester_id = ?",
            (request_id, int(root["requester_id"])),
        ).fetchone()
        require(contribution is not None, "contribution request is missing")
        snapshot = json.loads(contribution["snapshot_json"] or "{}")
        projection = json.loads(contribution["review_projection_json"] or "{}")
        source = projection.get("source") or {}
        require(source.get("company") is None, "company was not redacted in the review projection")
        require(source.get("round") is None, "round was not redacted in the review projection")
        require(source.get("source_url") is None, "source URL was not redacted")
        source_snapshot = snapshot.get("source") or {}
        require(source_snapshot.get("company") == "AC029 隔离公司",
                "admin review did not preserve access to the submitted source snapshot")
        require(int(contribution["public_interview_id"] or 0) > 0,
                "public projection interview is missing")

        item_rows = conn.execute(
            "SELECT i.id, i.ordinal, i.status, i.source_item_id, i.public_detail_id, "
            "i.error_message, i.review_json, i.snapshot_json, d.question, d.source_ordinal, d.cat1, d.cat2, d.tags "
            "FROM public_contribution_items i LEFT JOIN questions_detail d "
            "ON d.id = i.public_detail_id WHERE i.request_id = ? ORDER BY i.ordinal",
            (request_id,),
        ).fetchall()
        require(len(item_rows) == 5, "contribution does not retain all five source items")

        trace_items = []
        seen_public_details = set()
        published_by_source_ordinal = {}
        for item in item_rows:
            private_detail = conn.execute(
                "SELECT source_ordinal FROM questions_detail WHERE id = ?",
                (item["source_item_id"],),
            ).fetchone()
            require(private_detail is not None, "contribution lost its private item link")
            source_ordinal = int(private_detail["source_ordinal"])
            if source_ordinal == EXCLUDED_SOURCE_ORDINAL:
                require(item["status"] == "rejected", "excluded item was not rejected")
                require(item["public_detail_id"] is None, "excluded item created public detail")
                continue
            require(item["public_detail_id"] is not None, "retained item lacks public detail")
            public_detail_id = int(item["public_detail_id"])
            require(public_detail_id not in seen_public_details, "duplicate public detail id")
            seen_public_details.add(public_detail_id)
            expected_question = EDITED_QUESTION if source_ordinal == 10 else SOURCE_QUESTIONS[source_ordinal]
            require(item["question"] == expected_question,
                    f"public detail text does not match reviewed projection for ordinal {source_ordinal}")
            require(item["cat1"] == "B.Agent与LLM应用" and item["cat2"] == "B1.Agent架构与范式",
                    f"public classification changed for ordinal {source_ordinal}")
            require(item["tags"] == "Agent架构设计",
                    f"public tags changed for ordinal {source_ordinal}")
            resolution = conn.execute(
                "SELECT r.id AS resolution_id, r.canonical_id, r.canonical_scope, r.status, qb.owner_id, qb.question, qb.cat1 AS canonical_cat1, qb.cat2 AS canonical_cat2, qb.tags AS canonical_tags "
                "FROM question_resolutions r JOIN question_bank qb ON qb.id = r.canonical_id "
                "WHERE r.detail_id = ? AND r.occurrence_scope = 'public' "
                "AND r.occurrence_owner_id IS NULL AND r.invalidated_at IS NULL "
                "ORDER BY r.id DESC LIMIT 1",
                (public_detail_id,),
            ).fetchone()
            if source_ordinal == FAILED_SOURCE_ORDINAL:
                require(item["status"] == "published", "failed ordinal did not recover to published")
            require(item["status"] == "published", f"ordinal {source_ordinal} is not published")
            require(resolution is not None, f"ordinal {source_ordinal} has no current public resolution")
            require(resolution["status"] in ("matched", "created"),
                    f"ordinal {source_ordinal} resolution is not successful")
            require(resolution["canonical_scope"] == "public" and resolution["owner_id"] is None,
                    f"ordinal {source_ordinal} resolved outside public scope")
            require(resolution["canonical_cat1"] == "B.Agent与LLM应用" and resolution["canonical_cat2"] == "B1.Agent架构与范式",
                    f"public canonical classification changed for ordinal {source_ordinal}")
            require(resolution["canonical_tags"] == "Agent架构设计",
                    f"public canonical tags changed for ordinal {source_ordinal}")
            if source_ordinal == 20:
                require(int(resolution["canonical_id"]) == int(preseed["id"]),
                        "published matched item changed canonical")
                require(resolution["question"] == PRESEEDED_CANONICAL,
                        "preexisting canonical text changed")
            published_by_source_ordinal[source_ordinal] = public_detail_id
            trace_items.append({
                "source_ordinal": source_ordinal,
                "private_detail_id": int(item["source_item_id"]),
                "contribution_item_id": int(item["id"]),
                "public_detail_id": public_detail_id,
                "question": item["question"],
                "canonical_id": int(resolution["canonical_id"]),
                "resolution_status": resolution["status"],
                "resolution_id": int(resolution["resolution_id"]),
                "cat1": item["cat1"], "cat2": item["cat2"], "tags": item["tags"],
                "canonical_cat1": resolution["canonical_cat1"],
                "canonical_cat2": resolution["canonical_cat2"],
                "canonical_tags": resolution["canonical_tags"],
            })

        if baseline is not None:
            require(len(baseline) == 3, "first pass must contain three successful resolutions")
            for previous in baseline:
                current = next((row for row in trace_items if row["contribution_item_id"] == previous["contribution_item_id"]), None)
                require(current is not None, "successful item disappeared during retry")
                require(all(current[key] == previous[key] for key in ("public_detail_id", "resolution_id", "canonical_id")),
                        "retry replaced an already successful detail or resolution")

        require(set(published_by_source_ordinal) == {10, 20, 30, 40},
                "final published source ordinals are not exactly the four retained questions")
        public_interview = conn.execute(
            "SELECT owner_id, publish_status, company, round, questions_list FROM interview "
            "WHERE id = ? AND deleted_at IS NULL",
            (int(contribution["public_interview_id"]),),
        ).fetchone()
        require(public_interview is not None and public_interview["owner_id"] is None,
                "public interview projection is missing or has a private owner")
        require(public_interview["publish_status"] == "published",
                "public interview has not passed the publication gate")
        lines = [line for line in (public_interview["questions_list"] or "").splitlines() if line.strip()]
        require(len(lines) == 4, "public interview list does not contain exactly four questions")
        require(EDITED_QUESTION in public_interview["questions_list"], "public list omitted admin edit")
        require(SOURCE_QUESTIONS[50] not in public_interview["questions_list"], "excluded item leaked into public list")
        require(SOURCE_QUESTIONS[40] in public_interview["questions_list"], "recovered item is missing from public list")
        require(public_interview["company"] != "AC029 隔离公司", "sensitive company name leaked publicly")
        require(public_interview["round"] != "AC029 一面", "sensitive round leaked publicly")

        sources = conn.execute(
            "SELECT url, company, round FROM question_sources WHERE question_bank_id = ? "
            "AND deleted_at IS NULL ORDER BY id",
            (int(preseed["id"]),),
        ).fetchall()
        require(any(row["url"] == "https://ac029.example/preexisting-public-source" for row in sources),
                "preexisting canonical source was lost")
        require(all(row["company"] != "AC029 隔离公司" and row["round"] != "AC029 一面" for row in sources),
                "redacted interview source metadata reached canonical sources")
        canonical_count = conn.execute(
            "SELECT COUNT(*) FROM question_bank WHERE owner_id IS NULL AND status = 'approved' "
            "AND deleted_at IS NULL AND question = ?",
            (PRESEEDED_CANONICAL,),
        ).fetchone()[0]
        require(int(canonical_count) == 1, "public canonical was duplicated")

        trace = {
            "import_id": import_id,
            "contribution_request_id": int(request_id),
            "private_interview_id": int(root["interview_id"]),
            "public_interview_id": int(contribution["public_interview_id"]),
            "attempt_count": len(attempts),
            "private_question_count": len(private_details),
            "preexisting_public_canonical_id": int(preseed["id"]),
            "preexisting_canonical_source_count": len(sources),
            "items": sorted(trace_items, key=lambda row: row["source_ordinal"]),
            "excluded_source_ordinal": EXCLUDED_SOURCE_ORDINAL,
            "request_status": contribution["status"],
            "public_list_count": len(lines),
        }
        print(json.dumps(trace, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: assert_ac029_public_trace.py <import_id> <request_id> [--baseline-stdin]")
    baseline = json.load(sys.stdin) if len(sys.argv) == 4 and sys.argv[3] == "--baseline-stdin" else None
    main(sys.argv[1], int(sys.argv[2]), baseline)
