"""Seed isolated, traceable interview rows for real-stack AC-001/002."""

from __future__ import annotations

import json

from app.core.auth import hash_password
from app.db.connection import get_db_connection


U1 = "ac001_ac002_u1"
U2 = "ac001_ac002_u2"
PASSWORD = "Ac001-ac002-real-stack-123!"
P1 = "AC001 后端 P1"
P2 = "AC001 数据 P2"
SEASONS = ("2025秋招", "2026春招")


def main() -> None:
    with get_db_connection() as conn:
        for position in (P1, P2):
            conn.execute(
                "INSERT OR IGNORE INTO job_positions (name, description) VALUES (?, ?)",
                (position, "disposable AC-001/002 fixture"),
            )
        position_ids = {
            row["name"]: int(row["id"])
            for row in conn.execute(
                "SELECT id, name FROM job_positions WHERE name IN (?, ?)",
                (P1, P2),
            ).fetchall()
        }
        if set(position_ids) != {P1, P2}:
            raise RuntimeError("AC-001/002 positions were not created")
        for position in (P1, P2):
            conn.execute(
                "INSERT OR IGNORE INTO taxonomy "
                "(position_name, categories_json, tags_json, source, owner_id, is_default, is_public) "
                "VALUES (?, '[\"Fixture\"]', '[\"Fixture\"]', 'system', NULL, 0, 0)",
                (position,),
            )

        user_ids = {}
        for username in (U1, U2):
            row = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin, "
                    "share_default, current_position_id) VALUES (?, ?, ?, 0, 'private', ?)",
                    (
                        username,
                        hash_password(PASSWORD),
                        f"{username}@example.test",
                        position_ids[P1],
                    ),
                )
                row = conn.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()
            user_ids[username] = int(row["id"])

        marker = "AC001_AC002_FIXTURE"
        existing = conn.execute(
            "SELECT COUNT(*) FROM interview WHERE company LIKE ?", (f"{marker}%",)
        ).fetchone()[0]
        if existing:
            raise RuntimeError(f"unexpected existing fixture rows: {existing}")

        rows = []
        # Equal timestamps force the deterministic id tie-breaker to be visible.
        for index in range(1, 122):
            rows.append(
                (
                    f"https://ac001.example/u1/{index}",
                    f"{marker}_U1_{index:03d}",
                    "一面",
                    f"{marker}_PRIVATE_U1_{index:03d}",
                    "中等",
                    SEASONS[(index - 1) % len(SEASONS)],
                    "2026-01-01 00:00:00",
                    user_ids[U1],
                    P1,
                    "approved",
                    "published",
                )
            )
        rows.extend(
            [
                (
                    "https://ac001.example/u1/p2-private-source",
                    f"{marker}_U1_P2_SOURCE",
                    "一面",
                    f"{marker}_PRIVATE_P2_SOURCE",
                    "中等",
                    SEASONS[1],
                    "2026-01-01 00:00:00",
                    user_ids[U1],
                    P2,
                    "approved",
                    "published",
                ),
                (
                    "https://ac001.example/u2/private",
                    f"{marker}_U2_PRIVATE",
                    "一面",
                    f"{marker}_PRIVATE_U2_SECRET",
                    "中等",
                    SEASONS[0],
                    "2026-01-01 00:00:00",
                    user_ids[U2],
                    P1,
                    "approved",
                    "published",
                ),
                (
                    "https://ac001.example/p2/public",
                    f"{marker}_P2_PUBLIC",
                    "一面",
                    f"{marker}_PUBLIC_P2_TARGET",
                    "中等",
                    SEASONS[1],
                    "2026-01-01 00:00:00",
                    None,
                    P2,
                    "approved",
                    "published",
                ),
            ]
        )
        conn.executemany(
            "INSERT INTO interview (url, company, round, questions_list, difficulty, "
            "season, created_at, owner_id, job_position, status, publish_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        private_p2_source_id = int(
            conn.execute(
                "SELECT id FROM interview WHERE company = ?",
                (f"{marker}_U1_P2_SOURCE",),
            ).fetchone()["id"]
        )
        public_p2_target_id = int(
            conn.execute(
                "SELECT id FROM interview WHERE company = ?",
                (f"{marker}_P2_PUBLIC",),
            ).fetchone()["id"]
        )
        contribution_cursor = conn.execute(
            "INSERT INTO public_contribution_requests "
            "(source_type, source_id, requester_id, status, snapshot_json, public_interview_id) "
            "VALUES ('interview', ?, ?, 'partially_published', '{}', ?)",
            (private_p2_source_id, user_ids[U1], public_p2_target_id),
        )
        import_id = "imp-ac001-ac002-public-result"
        conn.execute(
            "INSERT INTO upload_imports "
            "(id, requester_id, idempotency_key, request_hash, target_intent, source_type, "
            "resolved_type, position_id, position_name, pipeline_version, policy_json, payload_json, "
            "status, current_attempt_no, interview_id, contribution_request_id, revision, completed_at) "
            "VALUES (?, ?, 'ac001-ac002-result-key', 'ac001-ac002-result-hash', 'share', 'interview', "
            "'interview', ?, ?, 'upload-pipeline-v1', '{}', '{\"raw_text\":\"fixture snapshot\"}', "
            "'completed', 1, ?, ?, 4, CURRENT_TIMESTAMP)",
            (
                import_id,
                user_ids[U1],
                position_ids[P2],
                P2,
                private_p2_source_id,
                int(contribution_cursor.lastrowid),
            ),
        )
        conn.commit()
        print(
            json.dumps(
                {
                    "u1": U1,
                    "u2": U2,
                    "password": PASSWORD,
                    "u1_id": user_ids[U1],
                    "u2_id": user_ids[U2],
                    "p1": {"id": position_ids[P1], "name": P1},
                    "p2": {"id": position_ids[P2], "name": P2},
                    "u1_interviews": 121,
                    "result_import_id": import_id,
                    "result_private_interview_id": private_p2_source_id,
                    "result_public_interview_id": public_p2_target_id,
                    "fixture_marker": marker,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
