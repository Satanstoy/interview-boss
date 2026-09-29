"""System-owned position taxonomies and safe seed behavior."""

import json
import sys
import types

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch


EXPECTED_NON_AGENT_POSITIONS = {
    "后端开发",
    "测试开发",
    "全栈开发",
    "前端开发",
}


def test_system_taxonomies_cover_all_active_non_agent_positions():
    from app.core.system_taxonomies import SYSTEM_TAXONOMIES

    assert EXPECTED_NON_AGENT_POSITIONS <= SYSTEM_TAXONOMIES.keys()
    for position in EXPECTED_NON_AGENT_POSITIONS:
        config = SYSTEM_TAXONOMIES[position]
        assert config["job_position"] == position
        assert config["categories"]
        assert config["tags"]
        assert all(category["cat1"] and category["children"] for category in config["categories"])
        assert all(isinstance(child, str) and child for category in config["categories"] for child in category["children"])


def test_system_taxonomy_seed_is_idempotent_and_preserves_personal_history(test_db):
    from app.db.migrations.taxonomy_system import _migration_104_system_taxonomies
    from app.core.system_taxonomies import SYSTEM_TAXONOMIES

    position = "前端开发"
    personal_categories = [{"cat1": "个人历史分类", "children": ["个人历史子类"]}]
    test_db.execute(
        "INSERT OR IGNORE INTO job_positions (name) VALUES (?)",
        (position,),
    )
    test_db.execute(
        "DELETE FROM taxonomy WHERE position_name = ? AND (source = 'system' OR owner_id = 901)",
        (position,),
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (901, 'taxonomy-owner', 'hash')"
    )
    test_db.execute(
        "INSERT INTO taxonomy (position_name, categories_json, source, owner_id) VALUES (?, ?, 'user', 901)",
        (position, json.dumps(personal_categories, ensure_ascii=False)),
    )
    test_db.commit()

    _migration_104_system_taxonomies(test_db)
    _migration_104_system_taxonomies(test_db)

    system_row = test_db.execute(
        "SELECT categories_json, tags_json FROM taxonomy "
        "WHERE position_name = ? AND source = 'system' AND owner_id IS NULL",
        (position,),
    ).fetchone()
    personal_row = test_db.execute(
        "SELECT categories_json FROM taxonomy "
        "WHERE position_name = ? AND source = 'user' AND owner_id = 901",
        (position,),
    ).fetchone()

    assert json.loads(system_row["categories_json"]) == SYSTEM_TAXONOMIES[position]["categories"]
    assert json.loads(system_row["tags_json"]) == SYSTEM_TAXONOMIES[position]["tags"]
    assert json.loads(personal_row["categories_json"]) == personal_categories


def test_runtime_taxonomy_ignores_personal_override(test_db):
    from app.db.connection import get_taxonomy_for_position

    position = "系统分类隔离测试"
    test_db.execute(
        "DELETE FROM taxonomy WHERE position_name = ?",
        (position,),
    )
    test_db.execute(
        "INSERT INTO taxonomy (position_name, categories_json, tags_json, source, owner_id) "
        "VALUES (?, ?, ?, 'system', NULL)",
        (position, json.dumps([{"cat1": "系统分类", "children": ["系统子类"]}], ensure_ascii=False), json.dumps(["系统标签"], ensure_ascii=False)),
    )
    test_db.execute(
        "INSERT INTO taxonomy (position_name, categories_json, tags_json, source, owner_id) "
        "VALUES (?, ?, ?, 'user', 1)",
        (position, json.dumps([{"cat1": "个人分类", "children": ["个人子类"]}], ensure_ascii=False), json.dumps(["个人标签"], ensure_ascii=False)),
    )
    test_db.commit()

    result = get_taxonomy_for_position(position, user_id=1)

    assert result["categories"] == [{"cat1": "系统分类", "children": ["系统子类"]}]
    assert result["tags"] == ["系统标签"]


def test_unconfigured_position_does_not_fallback_to_agent_taxonomy(test_db):
    from app.db.connection import get_taxonomy_for_position

    result = get_taxonomy_for_position("尚未配置的系统岗位")

    assert result["job_position"] == "尚未配置的系统岗位"
    assert result["configured"] is False
    assert result["categories"] == []
    assert result["tags"] == []


def test_tagging_prompt_uses_position_tags():
    from app.core.prompts import build_tagging_prompt

    prompt = build_tagging_prompt(
        {
            "job_position": "测试开发",
            "categories": [{"cat1": "A.测试", "children": ["A1.功能测试"]}],
            "tags": ["接口测试", "自动化测试"],
        }
    )

    assert "接口测试, 自动化测试" in prompt


@pytest.mark.asyncio
async def test_personal_taxonomy_mutations_are_disabled():
    from app.routers.profile_pkg.taxonomy import (
        confirm_taxonomy,
        generate_taxonomy,
        save_personal_taxonomy,
        share_taxonomy_endpoint,
    )

    user = {"id": 1, "is_admin": False}
    request = {"categories": [{"cat1": "个人分类", "children": ["个人子类"]}]}

    for operation in (
        lambda: generate_taxonomy(user=user),
        lambda: confirm_taxonomy(request, user=user),
        lambda: save_personal_taxonomy(request, user=user),
        lambda: share_taxonomy_endpoint(1, user=user),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await operation()
        assert exc_info.value.status_code == 410


def test_user_source_cannot_be_written_through_legacy_db_helper(test_db):
    from app.db.connection import save_taxonomy_for_position

    with pytest.raises(ValueError, match="系统维护"):
        save_taxonomy_for_position(
            "后端开发",
            [{"cat1": "个人分类", "children": ["个人子类"]}],
            source="user",
            owner_id=1,
        )


@pytest.mark.asyncio
async def test_admin_can_update_system_taxonomy_for_existing_position(test_db):
    from app.routers.profile_pkg.taxonomy import update_system_taxonomy

    position = "测试开发"
    test_db.execute("INSERT OR IGNORE INTO job_positions (name) VALUES (?)", (position,))
    test_db.commit()

    result = await update_system_taxonomy(
        {
            "position": position,
            "categories": [{"cat1": "A.质量", "children": ["A1.自动化"]}],
            "tags": ["接口测试"],
        },
        admin={"id": 1, "is_admin": True},
    )

    assert result["position"] == position
    row = test_db.execute(
        "SELECT categories_json, tags_json, source, owner_id FROM taxonomy "
        "WHERE position_name = ? AND source = 'system' AND owner_id IS NULL",
        (position,),
    ).fetchone()
    assert json.loads(row["categories_json"]) == [{"cat1": "A.质量", "children": ["A1.自动化"]}]
    assert json.loads(row["tags_json"]) == ["接口测试"]


@pytest.mark.asyncio
async def test_user_cannot_select_an_unregistered_position(test_db):
    from app.routers.profile_pkg.position import switch_my_position

    with pytest.raises(HTTPException) as exc_info:
        await switch_my_position({"position": "用户自定义岗位"}, user={"id": 1})

        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_switch_to_soft_deleted_position(test_db):
    from app.routers.profile_pkg.position import switch_position

    position = "后端开发"
    test_db.execute("UPDATE job_positions SET is_deleted = 1 WHERE name = ?", (position,))
    test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await switch_position({"position": position}, admin={"id": 1, "is_admin": True})

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_upload_classification_ignores_injected_personal_taxonomy():
    from app.agents.submit.classify import classify_node

    system_taxonomy = {
        "job_position": "前端开发",
        "categories": [{"cat1": "系统分类", "children": ["系统子类"]}],
        "tags": ["系统标签"],
    }
    state = {
        "user_id": 1,
        "job_position": "前端开发",
        "saved_url": "https://example.com/interview",
        "extracted_data": {
            "公司": "示例公司",
            "面试轮次": "一面",
            "具体题目清单": ["题目"],
        },
        "taxonomy_config": {
            "job_position": "前端开发",
            "categories": [{"cat1": "个人分类", "children": ["个人子类"]}],
            "tags": ["个人标签"],
        },
    }

    mock_tag = AsyncMock(return_value=[])
    fake_submit_service = types.SimpleNamespace(tag_questions_batch=mock_tag)
    with patch.dict(sys.modules, {"app.services.submit_service": fake_submit_service}):
        with patch("app.db.connection.run_db", new=AsyncMock(return_value=system_taxonomy)) as mock_run_db:
            await classify_node(state)

    mock_run_db.assert_awaited_once()
    assert mock_tag.await_args.kwargs["taxonomy_config"] == system_taxonomy
