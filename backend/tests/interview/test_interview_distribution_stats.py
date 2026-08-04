"""Statistical defaults must be derived only from valid public interview facts."""

import pytest


_TYPES = (
    "project_followup",
    "knowledge_probe",
    "algorithm_coding",
    "system_design",
    "behavioral",
)


def _insert_interview(test_db, *, position, owner_id=None, status="approved"):
    cursor = test_db.execute(
        """
        INSERT INTO interview (url, company, round, focus, questions_list, difficulty, owner_id, status, job_position)
        VALUES (?, '测试公司', '一面', '', '', '', ?, ?, ?)
        """,
        (f"https://example.test/{position}/{owner_id}/{status}/{test_db.total_changes}", owner_id, status, position),
    )
    return cursor.lastrowid


def _insert_details(test_db, interview_id, types):
    url = test_db.execute("SELECT url FROM interview WHERE id = ?", (interview_id,)).fetchone()["url"]
    for index, question_type in enumerate(types):
        test_db.execute(
            """
            INSERT INTO questions_detail (
                interview_id, url, question, cat1, cat2, tags, question_type, dimension, job_position
            ) VALUES (?, ?, ?, '', '', '', ?, ?, ?)
            """,
            (
                interview_id,
                url,
                f"题目 {index}",
                question_type,
                "unclassified" if question_type == "unclassified" else "knowledge_probe",
                test_db.execute("SELECT job_position FROM interview WHERE id = ?", (interview_id,)).fetchone()["job_position"],
            ),
        )


def test_refresh_uses_only_public_approved_linked_details(test_db):
    from app.services.interview_distribution import refresh_distribution_scope

    public_id = _insert_interview(test_db, position="Agent开发")
    _insert_details(test_db, public_id, ["algorithm_coding"] * 5)
    private_id = _insert_interview(test_db, position="Agent开发", owner_id=1)
    _insert_details(test_db, private_id, ["knowledge_probe"] * 5)
    pending_id = _insert_interview(test_db, position="Agent开发", status="pending")
    _insert_details(test_db, pending_id, ["behavioral"] * 5)

    result = refresh_distribution_scope(test_db, "public_job_position", "Agent开发")

    assert result["sample_interview_count"] == 1
    assert result["raw_counts"] == {
        "project_followup": 0,
        "knowledge_probe": 0,
        "algorithm_coding": 5,
        "system_design": 0,
        "behavioral": 0,
    }


def test_refresh_excludes_interview_with_more_than_twenty_percent_unclassified(test_db):
    from app.services.interview_distribution import refresh_distribution_scope

    valid_id = _insert_interview(test_db, position="Agent开发")
    _insert_details(test_db, valid_id, ["knowledge_probe"] * 5)
    excluded_id = _insert_interview(test_db, position="Agent开发")
    _insert_details(test_db, excluded_id, ["knowledge_probe"] * 5 + ["unclassified"] * 2)

    result = refresh_distribution_scope(test_db, "public_job_position", "Agent开发")

    assert result["sample_interview_count"] == 1
    reason = test_db.execute(
        "SELECT exclusion_reason FROM interview_distribution_stat_exclusions "
        "WHERE scope = 'public_job_position' AND job_position = ? AND interview_id = ?",
        ("Agent开发", excluded_id),
    ).fetchone()["exclusion_reason"]
    assert reason == "unclassified_ratio_exceeded"


def test_recommended_total_is_median_and_ratio_sum_is_one(test_db):
    from app.services.interview_distribution import refresh_distribution_scope

    for types in (["knowledge_probe"] * 5, ["algorithm_coding"] * 10, ["behavioral"] * 15):
        interview_id = _insert_interview(test_db, position="Agent开发")
        _insert_details(test_db, interview_id, types)

    result = refresh_distribution_scope(test_db, "public_job_position", "Agent开发")

    assert result["recommended_total_count"] == 10
    assert sum(result["posterior_mean_ratio"].values()) == pytest.approx(1.0)


def test_related_positions_share_a_family_but_unknown_positions_do_not_merge():
    from app.core.interview_distribution_config import derive_job_family

    assert derive_job_family("Agent开发") == derive_job_family("大模型开发") == "agent_llm"
    assert derive_job_family("冷门岗位") == "position:冷门岗位"


def test_refresh_uses_job_family_parent_for_sparse_position(test_db):
    from app.services.interview_distribution import refresh_distribution_scope

    for position in ("Agent开发", "大模型开发"):
        interview_id = _insert_interview(test_db, position=position)
        _insert_details(test_db, interview_id, ["knowledge_probe"] * 5)
    sparse_id = _insert_interview(test_db, position="大模型应用开发")
    _insert_details(test_db, sparse_id, ["algorithm_coding"] * 5)

    result = refresh_distribution_scope(test_db, "public_job_position", "大模型应用开发")

    assert result["parent_scope"] == "job_family"
    assert result["parent_job_position"] == "agent_llm"
    assert result["sample_interview_count"] == 1


def test_mark_refresh_coalesces_one_scope_job(test_db):
    from app.services.interview_distribution import mark_distribution_refresh

    mark_distribution_refresh(test_db.cursor(), "Agent开发")
    mark_distribution_refresh(test_db.cursor(), "Agent开发")

    assert test_db.execute(
        "SELECT COUNT(*) FROM interview_distribution_refresh_jobs "
        "WHERE scope = 'public_job_position' AND job_position = 'Agent开发'"
    ).fetchone()[0] == 1
