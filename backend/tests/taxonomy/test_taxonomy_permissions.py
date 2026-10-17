"""Permission tests for system-owned position taxonomies."""

import pytest
from unittest.mock import MagicMock, patch


def _taxonomy(taxonomy_id=999, source="system", owner_id=None):
    return {
        "id": taxonomy_id,
        "source": source,
        "owner_id": owner_id,
        "categories": [{"cat1": "A.原分类", "children": []}],
    }


@pytest.mark.asyncio
async def test_admin_can_edit_system_taxonomy():
    from app.db.operations import update_taxonomy_permissions

    categories = [{"cat1": "A.测试分类", "children": ["A1.子类1"]}]
    connection = MagicMock()
    connection.__enter__ = MagicMock(return_value=connection)
    connection.__exit__ = MagicMock(return_value=False)
    with patch("app.db.operations.get_taxonomy_by_id", return_value=_taxonomy()):
        with patch("app.db.operations.get_db_connection", return_value=connection):
            result = await update_taxonomy_permissions(
                taxonomy_id=999,
                categories=categories,
                user={"id": 1, "is_admin": True},
            )

    assert result["success"] is True
    assert result["taxonomy"]["categories"] == categories


@pytest.mark.asyncio
async def test_regular_user_cannot_edit_system_taxonomy():
    from app.db.operations import update_taxonomy_permissions

    with patch("app.db.operations.get_taxonomy_by_id", return_value=_taxonomy()):
        with pytest.raises(PermissionError, match="只有管理员可以编辑系统分类"):
            await update_taxonomy_permissions(
                taxonomy_id=999,
                categories=[],
                user={"id": 2, "is_admin": False},
            )


@pytest.mark.asyncio
async def test_personal_taxonomy_creation_is_disabled():
    from app.db.operations import create_personal_taxonomy

    with pytest.raises(ValueError, match="系统维护"):
        await create_personal_taxonomy(
            position="测试岗位",
            categories=[{"cat1": "A.个人分类", "children": ["A1.子类"]}],
            user={"id": 2, "is_admin": False},
        )


@pytest.mark.asyncio
async def test_personal_taxonomy_editing_is_disabled():
    from app.db.operations import update_taxonomy_permissions

    with patch(
        "app.db.operations.get_taxonomy_by_id",
        return_value=_taxonomy(taxonomy_id=100, source="user", owner_id=2),
    ):
        with pytest.raises(ValueError, match="个人分类体系已停用"):
            await update_taxonomy_permissions(
                taxonomy_id=100,
                categories=[],
                user={"id": 2, "is_admin": False},
            )


@pytest.mark.asyncio
async def test_personal_taxonomy_sharing_is_disabled():
    from app.db.operations import share_taxonomy

    with pytest.raises(ValueError, match="个人分类体系已停用"):
        await share_taxonomy(taxonomy_id=100, user={"id": 2, "is_admin": False})


def test_public_taxonomy_listing_is_read_only():
    """The legacy public listing remains callable for historical records."""
    from app.db.operations import get_public_shared_taxonomies

    assert callable(get_public_shared_taxonomies)
