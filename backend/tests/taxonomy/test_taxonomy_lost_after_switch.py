"""Regression tests for the system-owned taxonomy contract."""

import json
from unittest.mock import MagicMock

import pytest


def _mock_taxonomy_connection(system_categories=None):
    connection = MagicMock()
    connection.__enter__ = MagicMock(return_value=connection)
    connection.__exit__ = MagicMock(return_value=False)

    def execute(sql, *args):
        result = MagicMock()
        if sql.startswith("PRAGMA"):
            result.fetchall.return_value = []
        elif "source = 'system'" in sql and system_categories is not None:
            result.fetchone.return_value = {
                "categories_json": json.dumps(system_categories, ensure_ascii=False)
            }
        else:
            result.fetchone.return_value = None
        return result

    connection.execute.side_effect = execute
    return connection


def test_get_taxonomy_for_position_ignores_historical_personal_override():
    """岗位切换后始终使用系统 taxonomy，不被历史个人记录覆盖。"""
    from app.db.connection import get_taxonomy_for_position

    connection = _mock_taxonomy_connection(
        [{"cat1": "A.系统分类", "children": ["A1.子类"]}]
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.db.connection.get_db_connection", lambda: connection)
        result = get_taxonomy_for_position("测试岗位", user_id=1)

    assert result["categories"][0]["cat1"] == "A.系统分类"
    assert result["source"] == "system"
    assert not any(
        "source = 'user'" in call.args[0]
        for call in connection.execute.call_args_list
    )


def test_unconfigured_position_does_not_fallback_to_agent_taxonomy():
    """切换到未配置岗位时返回未配置状态，不能静默套用旧分类。"""
    from app.db.connection import get_taxonomy_for_position

    connection = _mock_taxonomy_connection()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.db.connection.get_db_connection", lambda: connection)
        result = get_taxonomy_for_position("尚未配置岗位", user_id=1)

    assert result == {
        "job_position": "尚未配置岗位",
        "categories": [],
        "tags": [],
        "source": "system",
        "configured": False,
    }


@pytest.mark.asyncio
async def test_personal_taxonomy_endpoints_are_retired():
    """个人 taxonomy 写入和 profile 配置入口都返回明确的 410。"""
    from fastapi import HTTPException
    from app.models.schemas import ProfileUpdateRequest
    from app.routers.profile import update_profile
    from app.routers.profile_pkg.taxonomy import confirm_taxonomy, save_personal_taxonomy

    user = {"id": 1, "is_admin": True}
    request = {"categories": [{"cat1": "A.旧分类", "children": ["A1.子类"]}]}
    operations = (
        lambda: confirm_taxonomy(request, user=user),
        lambda: save_personal_taxonomy(request, user=user),
        lambda: update_profile(
            ProfileUpdateRequest(
                settings={
                    "taxonomy_config": json.dumps(
                        {"job_position": "测试岗位", "categories": request["categories"]}
                    )
                }
            ),
            admin=user,
        ),
    )

    for operation in operations:
        with pytest.raises(HTTPException) as exc_info:
            await operation()
        assert exc_info.value.status_code == 410
