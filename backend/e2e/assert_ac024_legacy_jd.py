"""Cross-check AC-024 browser/provider evidence against durable SQLite rows."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


COUNT_TABLES = (
    "upload_imports",
    "upload_attempts",
    "public_contribution_requests",
    "jd",
    "interview",
    "question_bank",
    "questions_detail",
    "question_resolutions",
    "analysis_queue",
)


def _counts(conn) -> dict:
    return {
        "submit_import_jobs": int(
            conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'submit_import'").fetchone()[0]
        ),
        "generate_answer_jobs": int(
            conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'generate_answer'").fetchone()[0]
        ),
        **{
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in COUNT_TABLES
        },
    }


def main() -> None:
    seed_path, browser_path, baseline_path, provider_path = sys.argv[1:5]
    with open(seed_path, encoding="utf-8") as stream:
        seed = json.load(stream)
    with open(browser_path, encoding="utf-8") as stream:
        browser = json.load(stream)
    with open(baseline_path, encoding="utf-8") as stream:
        baseline = json.load(stream)
    with open(provider_path, encoding="utf-8") as stream:
        provider = json.load(stream)

    old_job_id = int(seed["old_job_id"])
    retry_job_id = int(browser["retry_job_id"])
    request_id = int(browser["contribution_request_id"])
    private_jd_id = int(browser["private_jd_id"])
    public_jd_id = int(browser["approval"]["body"]["public_jd_id"])
    ordinary_result = browser["ordinary_interview"]["result"]
    ordinary_import_id = str(browser["ordinary_interview"]["import_id"])
    ordinary_interview_id = int(ordinary_result["interview_id"])

    with get_db_connection() as conn:
        old_job = conn.execute(
            "SELECT id, job_type, status, created_by, parent_job_id, root_import_id "
            "FROM jobs WHERE id = ?",
            (old_job_id,),
        ).fetchone()
        retry_job = conn.execute(
            "SELECT id, job_type, status, created_by, parent_job_id, root_import_id, result "
            "FROM jobs WHERE id = ?",
            (retry_job_id,),
        ).fetchone()
        retry_payload = conn.execute(
            "SELECT payload FROM job_payloads WHERE job_id = ?", (retry_job_id,)
        ).fetchone()
        contribution = conn.execute(
            "SELECT id, source_type, source_id, requester_id, status, public_jd_id, snapshot_json, "
            "review_projection_json FROM public_contribution_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        private_jd = conn.execute("SELECT * FROM jd WHERE id = ?", (private_jd_id,)).fetchone()
        public_jd = conn.execute("SELECT * FROM jd WHERE id = ?", (public_jd_id,)).fetchone()
        old_public_jd = conn.execute(
            "SELECT id, owner_id, status, url FROM jd WHERE id = ?", (seed["old_public_jd_id"],)
        ).fetchone()
        old_interview = conn.execute(
            "SELECT id, owner_id, status, publish_status, url FROM interview WHERE id = ?",
            (seed["old_public_interview_id"],),
        ).fetchone()
        ordinary_import = conn.execute(
            "SELECT id, requester_id, source_type, target_intent, status "
            "FROM upload_imports WHERE id = ?",
            (ordinary_import_id,),
        ).fetchone()
        ordinary_jobs = conn.execute(
            "SELECT id, job_type, status, created_by, root_import_id "
            "FROM jobs WHERE root_import_id = ? ORDER BY id",
            (ordinary_import_id,),
        ).fetchall()
        ordinary_interview = conn.execute(
            "SELECT id, url, company, owner_id, status, publish_status, questions_list "
            "FROM interview WHERE id = ?",
            (ordinary_interview_id,),
        ).fetchone()
        ordinary_details = conn.execute(
            "SELECT id, question, owner_id, interview_id FROM questions_detail "
            "WHERE interview_id = ? ORDER BY id",
            (ordinary_interview_id,),
        ).fetchall()
        ordinary_contributions = conn.execute(
            "SELECT id FROM public_contribution_requests "
            "WHERE source_type = 'interview' AND source_id = ?",
            (ordinary_interview_id,),
        ).fetchall()
        answer_children = conn.execute(
            "SELECT id, job_type, status FROM jobs WHERE parent_job_id = ? "
            "AND job_type != 'submit_import'",
            (retry_job_id,),
        ).fetchall()
        descendants = conn.execute(
            "SELECT id, job_type, parent_job_id FROM jobs "
            "WHERE parent_job_id IN (?, ?) ORDER BY id",
            (old_job_id, retry_job_id),
        ).fetchall()
        import_rows = conn.execute(
            "SELECT id FROM upload_imports WHERE requester_id = ? AND source_type = 'jd'",
            (seed["owner_id"],),
        ).fetchall()
        jd_columns = {row[1] for row in conn.execute("PRAGMA table_info('jd')").fetchall()}
        interview_rows_with_jd_marker = conn.execute(
            "SELECT id FROM interview WHERE COALESCE(company, '') LIKE '%AC024_LEGACY_JD_REAL_STACK%' "
            "OR COALESCE(round, '') LIKE '%AC024_LEGACY_JD_REAL_STACK%' "
            "OR COALESCE(focus, '') LIKE '%AC024_LEGACY_JD_REAL_STACK%' "
            "OR COALESCE(questions_list, '') LIKE '%AC024_LEGACY_JD_REAL_STACK%'"
        ).fetchall()
        question_markers = {
            "question_bank": conn.execute(
                "SELECT id FROM question_bank WHERE question LIKE '%AC024_LEGACY_JD_REAL_STACK%'"
            ).fetchall(),
            "questions_detail": conn.execute(
                "SELECT id FROM questions_detail WHERE question LIKE '%AC024_LEGACY_JD_REAL_STACK%'"
            ).fetchall(),
        }
        final_counts = _counts(conn)

    assert old_job is not None and old_job["status"] == "failed"
    assert old_job["job_type"] == "submit_import" and old_job["created_by"] == seed["owner_id"]
    assert old_job["root_import_id"] is None and old_job["parent_job_id"] is None
    assert retry_job is not None and retry_job["status"] == "completed"
    assert retry_job["job_type"] == "submit_import" and retry_job["created_by"] == seed["owner_id"]
    assert retry_job["parent_job_id"] == old_job_id and retry_job["root_import_id"] is None
    payload = json.loads(retry_payload["payload"])
    assert payload["content_type_hint"] == "jd" and payload["user_id"] == seed["owner_id"]
    result = json.loads(retry_job["result"] or "{}")
    assert result["doc_type"] == "JD", result
    assert result["interview_id"] is None and result["question_count"] == 0
    assert result["answer_job_count"] == 0
    assert contribution is not None
    assert contribution["source_type"] == "jd" and contribution["source_id"] == private_jd_id
    assert contribution["requester_id"] == seed["owner_id"]
    assert contribution["status"] == "published" and contribution["public_jd_id"] == public_jd_id
    assert private_jd is not None and private_jd["owner_id"] == seed["owner_id"]
    assert private_jd["status"] == "approved" and private_jd["url"] == seed["legacy_source_url"]
    assert public_jd is not None and public_jd["owner_id"] is None and public_jd["status"] == "approved"
    assert public_jd["url"] == seed["reviewed_public_url"]
    assert public_jd["company"] == "AC024_PUBLIC_REVIEW_COMPANY"
    assert public_jd["job_title"] == "AC024 public platform engineer"
    assert public_jd["bonus"] == "AC024_PUBLIC_BONUS_SQL"
    assert "publish_status" not in jd_columns
    assert old_public_jd is not None and old_public_jd["owner_id"] is None
    assert old_public_jd["status"] == "approved" and old_public_jd["url"] == seed["old_public_jd_url"]
    assert old_interview is not None and old_interview["owner_id"] is None
    assert old_interview["status"] == "approved" and old_interview["publish_status"] == "published"
    assert old_interview["url"] == seed["old_public_interview_url"]
    assert ordinary_import is not None
    assert ordinary_import["requester_id"] == seed["owner_id"]
    assert ordinary_import["source_type"] == "interview"
    assert ordinary_import["target_intent"] == "private"
    assert ordinary_import["status"] == "completed"
    assert ordinary_jobs and all(row["root_import_id"] == ordinary_import_id for row in ordinary_jobs)
    assert any(
        row["job_type"] == "submit_import"
        and row["status"] == "completed"
        and row["created_by"] == seed["owner_id"]
        for row in ordinary_jobs
    )
    assert ordinary_interview is not None and ordinary_interview["owner_id"] == seed["owner_id"]
    assert ordinary_interview["company"] == "AC024_ORDINARY_INTERVIEW_COMPANY"
    assert any(
        "AC024_ORDINARY_INTERVIEW_QUESTION_MARKER" in row["question"]
        and row["interview_id"] == ordinary_interview_id
        for row in ordinary_details
    )
    assert not ordinary_contributions
    assert ordinary_result["interview_id"] == ordinary_interview_id
    assert isinstance(ordinary_result["question_ids"], list)
    assert browser["ordinary_interview"]["private_visible_for_owner"] is True
    assert browser["ordinary_interview"]["public_absent_for_other"] is True
    assert not import_rows, f"legacy retry unexpectedly created v2 upload roots: {import_rows}"
    assert not answer_children, f"JD retry created answer jobs: {[dict(row) for row in answer_children]}"
    assert [dict(row) for row in descendants] == [
        {"id": retry_job_id, "job_type": "submit_import", "parent_job_id": old_job_id}
    ]
    assert not interview_rows_with_jd_marker
    assert not question_markers["question_bank"] and not question_markers["questions_detail"]
    assert browser["other_retry_status"] == 404 and browser["other_job_read_status"] == 404
    assert browser["private_request_read_status"] == 403
    assert browser["disallowed_projection_status"] == 422
    assert browser["old_rows_visible"] == {"jd": True, "interview": True}
    assert browser["private_source_absent_for_other"] is True
    assert browser["approval"]["body"]["status"] == "published"
    assert browser["public_jd"]["owner_id"] is None
    assert "AC024_PRIVATE_CONTACT_SENTINEL" not in json.dumps(dict(public_jd), ensure_ascii=False)
    assert "AC024_PRIVATE_COMPANY_SENTINEL" not in json.dumps(dict(public_jd), ensure_ascii=False)
    assert final_counts == baseline, {"before_list_reads": baseline, "after_list_reads": final_counts}

    marker_statuses = provider.get("marker_statuses", {}).get("AC024_LEGACY_JD_REAL_STACK", {})
    assert sum(marker_statuses.values()) >= 1 and int(marker_statuses.get("200", 0)) >= 1
    ordinary_marker_statuses = provider.get("marker_statuses", {}).get(
        "AC024_ORDINARY_INTERVIEW_REAL_STACK", {}
    )
    assert sum(ordinary_marker_statuses.values()) >= 1
    assert int(ordinary_marker_statuses.get("200", 0)) >= 1

    trace = {
        "old_job": dict(old_job),
        "retry_job": {
            "id": retry_job_id,
            "job_type": retry_job["job_type"],
            "status": retry_job["status"],
            "created_by": retry_job["created_by"],
            "parent_job_id": retry_job["parent_job_id"],
            "root_import_id": retry_job["root_import_id"],
            "result": result,
        },
        "legacy_retry_payload": {
            "content_type_hint": payload["content_type_hint"],
            "user_id": payload["user_id"],
            "request_public_review": payload.get("request_public_review"),
            "target_intent": payload.get("target_intent"),
        },
        "contribution": {
            "id": contribution["id"],
            "source_type": contribution["source_type"],
            "source_id": contribution["source_id"],
            "requester_id": contribution["requester_id"],
            "status": contribution["status"],
            "public_jd_id": contribution["public_jd_id"],
            "snapshot": json.loads(contribution["snapshot_json"]),
            "review_projection": json.loads(contribution["review_projection_json"]),
        },
        "private_jd": {key: private_jd[key] for key in ("id", "url", "company", "job_title", "owner_id", "status")},
        "public_jd": {key: public_jd[key] for key in ("id", "url", "company", "job_title", "tech_stack", "bonus", "owner_id", "status")},
        "old_public_jd": dict(old_public_jd),
        "old_public_interview": dict(old_interview),
        "ordinary_interview": {
            "import": dict(ordinary_import),
            "jobs": [dict(row) for row in ordinary_jobs],
            "interview": dict(ordinary_interview),
            "details": [dict(row) for row in ordinary_details],
            "contribution_requests": [dict(row) for row in ordinary_contributions],
            "result": ordinary_result,
        },
        "jd_schema_has_publish_status": "publish_status" in jd_columns,
        "question_and_interview_markers_absent": True,
        "descendant_jobs": [dict(row) for row in descendants],
        "counts_unchanged_across_list_reads": {"before": baseline, "after": final_counts},
        "provider_marker_statuses": marker_statuses,
        "ordinary_interview_provider_marker_statuses": ordinary_marker_statuses,
    }
    print(json.dumps(trace, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
