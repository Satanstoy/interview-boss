"""JD reads must apply ownership, publication, and soft-delete visibility."""

from app.agents.chat import memory_extract
from app.services import load_visible_jd


def _seed_jds(test_db):
    rows = [
        (1, None, "approved", None, "Public JD"),
        (2, 10, "draft", None, "Owner JD"),
        (3, 11, "draft", None, "Private JD"),
        (4, 10, "approved", "2026-08-17", "Deleted JD"),
    ]
    test_db.executemany(
        "INSERT INTO jd (id, owner_id, status, deleted_at, job_title) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    test_db.commit()


def test_visible_jd_loader_enforces_owner_publication_and_soft_delete(test_db):
    _seed_jds(test_db)

    assert load_visible_jd(test_db, 1, user_id=10)["job_title"] == "Public JD"
    assert load_visible_jd(test_db, 2, user_id=10)["job_title"] == "Owner JD"
    assert load_visible_jd(test_db, 3, user_id=10) is None
    assert load_visible_jd(test_db, 4, user_id=10) is None


def test_memory_jd_title_uses_the_same_visibility_policy(test_db, monkeypatch):
    _seed_jds(test_db)
    monkeypatch.setattr(
        "app.db.connection.get_db_connection", lambda: test_db
    )

    assert memory_extract._get_jd_title(2, user_id=10) == "Owner JD"
    assert memory_extract._get_jd_title(3, user_id=10) == ""
    assert memory_extract._get_jd_title(4, user_id=10) == ""
