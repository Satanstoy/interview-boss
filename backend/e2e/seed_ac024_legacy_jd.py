"""Seed old rootless JD retry plus legacy approved public JD/interview rows."""

from __future__ import annotations

import json

from app.core.auth import hash_password
from app.db.connection import get_db_connection


OWNER = "ac024_legacy_jd_owner"
OTHER = "ac024_legacy_jd_other"
TEST_PASSWORD = "Ac024-legacy-jd-real-stack-123!"
SOURCE_URL = "https://ac024.example/retried/private-source"
PUBLIC_SOURCE_URL = "https://ac024.example/reviewed/public-jd"
OLD_PUBLIC_JD_URL = "https://ac024.example/legacy/approved-jd"
OLD_PUBLIC_INTERVIEW_URL = "https://ac024.example/legacy/approved-interview"
SECRET_CONTACT = "AC024_PRIVATE_CONTACT_SENTINEL"


def main() -> None:
    with get_db_connection() as conn:
        admin = conn.execute(
            "SELECT id FROM users WHERE username = 'real_stack_admin' AND is_admin = 1"
        ).fetchone()
        if admin is None:
            raise RuntimeError("AC-024 disposable administrator is missing")
        if not conn.execute(
            "SELECT email FROM users WHERE id = ?", (int(admin["id"]),)
        ).fetchone()["email"]:
            conn.execute(
                "UPDATE users SET email = ? WHERE id = ?",
                ("real_stack_admin@example.test", int(admin["id"])),
            )

        users = {}
        for username in (OWNER, OTHER):
            if conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            ).fetchone():
                raise RuntimeError(f"AC-024 disposable user unexpectedly exists: {username}")
            users[username] = int(
                conn.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                    "VALUES (?, ?, ?, 0, 'private') RETURNING id",
                    (username, hash_password(TEST_PASSWORD), f"{username}@example.test"),
                ).fetchone()["id"]
            )

        # The ordinary interview path runs the real classification step. Point
        # this disposable user at a system taxonomy that exists in the blank
        # real-stack database, instead of creating an unconfigured position.
        position_name = "agent开发/大模型应用开发/大模型开发"
        taxonomy = conn.execute(
            "SELECT 1 FROM taxonomy WHERE position_name = ? AND source = 'system' "
            "AND owner_id IS NULL",
            (position_name,),
        ).fetchone()
        if taxonomy is None:
            raise RuntimeError(f"AC-024 ordinary interview taxonomy is missing: {position_name}")
        conn.execute(
            "INSERT OR IGNORE INTO job_positions (name, description) VALUES (?, ?)",
            (position_name, "disposable AC-024 JD compatibility fixture"),
        )
        position_id = int(
            conn.execute(
                "SELECT id FROM job_positions WHERE name = ? ORDER BY id LIMIT 1",
                (position_name,),
            ).fetchone()["id"]
        )
        conn.execute(
            "UPDATE users SET current_position_id = ? WHERE id IN (?, ?)",
            (position_id, users[OWNER], users[OTHER]),
        )

        owner_id = users[OWNER]
        conn.execute(
            "INSERT INTO user_llm_config (user_id, api_key, base_url, model, timeout) "
            "VALUES (?, ?, ?, ?, '10')",
            (owner_id, "real-stack-e2e-provider-key", "http://llm-stub:8080/v1", "real-stack-stub"),
        )

        payload = {
            "raw_text": (
                "AC024_LEGACY_JD_REAL_STACK: legacy JD retry must remain a JD. "
                f"Do not publish contact {SECRET_CONTACT}."
            ),
            "image_data": [],
            "url": SOURCE_URL,
            "season": "AC024 legacy season",
            "content_type_hint": "jd",
            "target": "personal",
            "target_intent": "share",
            "request_public_review": True,
            "user_id": owner_id,
            "is_admin": False,
            "job_position": position_name,
            "entry": "api",
        }
        old_job_id = int(
            conn.execute(
                "INSERT INTO jobs (job_type, status, progress_total, created_by, last_error) "
                "VALUES ('submit_import', 'failed', 6, ?, 'AC024 legacy JD failure') "
                "RETURNING id",
                (owner_id,),
            ).fetchone()["id"]
        )
        conn.execute(
            "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
            (old_job_id, json.dumps(payload, ensure_ascii=False)),
        )

        old_jd_id = int(
            conn.execute(
                "INSERT INTO jd (url, company, job_title, tech_stack, owner_id, status, job_position) "
                "VALUES (?, ?, ?, ?, NULL, 'approved', '') RETURNING id",
                (
                    OLD_PUBLIC_JD_URL,
                    "AC024_LEGACY_APPROVED_PUBLIC_JD",
                    "AC024 legacy approved JD title",
                    "AC024 legacy approved JD stack",
                ),
            ).fetchone()["id"]
        )
        old_interview_id = int(
            conn.execute(
                "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, "
                "owner_id, status, job_position) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, 'approved', '') RETURNING id",
                (
                    OLD_PUBLIC_INTERVIEW_URL,
                    "AC024_LEGACY_APPROVED_PUBLIC_INTERVIEW",
                    "AC024 legacy round",
                    "AC024 legacy compatibility",
                    "AC024_LEGACY_INTERVIEW_QUESTION_MARKER",
                    "中等",
                ),
            ).fetchone()["id"]
        )
        conn.commit()

    print(
        json.dumps(
            {
                "owner_id": owner_id,
                "owner_username": OWNER,
                "other_id": users[OTHER],
                "other_username": OTHER,
                "admin_id": int(admin["id"]),
                "old_job_id": old_job_id,
                "legacy_source_url": SOURCE_URL,
                "reviewed_public_url": PUBLIC_SOURCE_URL,
                "old_public_jd_id": old_jd_id,
                "old_public_jd_url": OLD_PUBLIC_JD_URL,
                "old_public_interview_id": old_interview_id,
                "old_public_interview_url": OLD_PUBLIC_INTERVIEW_URL,
                "secret_contact_marker": SECRET_CONTACT,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
