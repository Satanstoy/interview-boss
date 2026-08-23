#!/usr/bin/env python3
"""Call the real batch-answer API for active Agent questions without answers.

The script only selects Agent questions locally. Answer generation and writes
are performed by the authenticated application API, not by a test double or
direct SQL answer fabrication.

Examples:
    uv run python backend/scripts/generate_agent_reference_answers.py \
      --base-url http://127.0.0.1:8000
    uv run python backend/scripts/generate_agent_reference_answers.py \
      --base-url https://interview.example.com --allow-no-search
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import httpx

from app.core.config import DB_PATH
from app.db.taxonomy_verification import select_agent_question_ids_without_answers


def _load_ids(db_path: str, owner_id: int | None = None) -> list[int]:
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return select_agent_question_ids_without_answers(conn, owner_id=owner_id)
    finally:
        conn.close()


def _stream_batch_generation(
    client: httpx.Client,
    base_url: str,
    token: str,
    question_ids: list[int],
    allow_no_search: bool,
) -> int:
    stream = client.stream(
        "POST",
        f"{base_url.rstrip('/')}/api/master-bank/batch-generate-answers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "ids": question_ids,
            "force": False,
            "refresh_stale": False,
            "allow_no_search": allow_no_search,
        },
    )
    with stream as response:
        response.raise_for_status()
        final = None
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            if payload.get("type") == "done":
                final = payload
        if final is None:
            raise RuntimeError("答案接口未返回 done 事件")
        return int(final.get("failed", 0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=DB_PATH)
    parser.add_argument("--base-url", default=os.getenv("INTERVIEW_BOSS_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--username", default=os.getenv("ADMIN_USERNAME"))
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD"))
    parser.add_argument("--allow-no-search", action="store_true")
    args = parser.parse_args()

    if not args.username or not args.password:
        parser.error("请通过 --username/--password 或 ADMIN_USERNAME/ADMIN_PASSWORD 提供管理员凭据")

    with httpx.Client(timeout=None, follow_redirects=False) as client:
        login = client.post(
            f"{args.base_url.rstrip('/')}/api/auth/login",
            json={"username": args.username, "password": args.password, "remember_me": True},
        )
        login.raise_for_status()
        login_payload = login.json()
        token = login_payload.get("token")
        if not token:
            raise RuntimeError("管理员登录未返回 access token，可能需要先绑定邮箱")
        user = login_payload.get("user") or {}
        owner_id = user.get("id")
        if owner_id is None:
            raise RuntimeError("管理员登录未返回用户 ID，无法按权限筛选私有题")

        all_question_ids = _load_ids(args.db_path)
        question_ids = _load_ids(args.db_path, owner_id=int(owner_id))
        skipped_ids = sorted(set(all_question_ids) - set(question_ids))
        print(
            json.dumps(
                {
                    "agent_question_ids": question_ids,
                    "skipped_inaccessible_ids": skipped_ids,
                    "total": len(question_ids),
                },
                ensure_ascii=False,
            )
        )
        if not question_ids:
            return 0
        failed = _stream_batch_generation(
            client,
            args.base_url,
            token,
            question_ids,
            args.allow_no_search,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
