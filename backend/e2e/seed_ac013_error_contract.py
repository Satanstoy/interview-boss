"""Create the disposable account/config fixture for AC-013 real-stack traces."""

from __future__ import annotations

import json

from app.core.auth import hash_password
from app.core.prompts import DEFAULT_TAXONOMY
from app.db.connection import get_db_connection


USERNAME = "ac013_error_contract"
PASSWORD = "Ac013-error-contract-real-stack-123!"


def main() -> None:
    with get_db_connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = ?", (USERNAME,)).fetchone()
        if user is None:
            user_id = int(
                conn.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                    "VALUES (?, ?, ?, 0, 'private') RETURNING id",
                    (USERNAME, hash_password(PASSWORD), f"{USERNAME}@example.test"),
                ).fetchone()["id"]
            )
        else:
            user_id = int(user["id"])

        conn.execute(
            "INSERT INTO user_llm_config "
            "(user_id, api_key, base_url, model, timeout, api_format) "
            "VALUES (?, 'real-stack-e2e-provider-key', 'http://llm-stub:8080/v1', "
            "'real-stack-stub', '10', 'chat') "
            "ON CONFLICT(user_id) DO UPDATE SET api_key = excluded.api_key, "
            "base_url = excluded.base_url, model = excluded.model, "
            "timeout = excluded.timeout, api_format = excluded.api_format",
            (user_id,),
        )

        position_name = DEFAULT_TAXONOMY["job_position"]
        position = conn.execute(
            "SELECT id FROM job_positions WHERE name = ? "
            "AND (is_deleted = 0 OR is_deleted IS NULL) ORDER BY id LIMIT 1",
            (position_name,),
        ).fetchone()
        if position is None:
            position_id = int(
                conn.execute(
                    "INSERT INTO job_positions (name, description) "
                    "VALUES (?, 'AC-013 real-stack fixture') RETURNING id",
                    (position_name,),
                ).fetchone()["id"]
            )
        else:
            position_id = int(position["id"])
        conn.execute("UPDATE users SET current_position_id = ? WHERE id = ?", (position_id, user_id))
        conn.commit()

    print(json.dumps({"username": USERNAME, "password": PASSWORD}, ensure_ascii=False))


if __name__ == "__main__":
    main()
