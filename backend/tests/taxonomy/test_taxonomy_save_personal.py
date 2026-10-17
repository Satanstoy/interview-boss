"""Regression tests for the retired personal taxonomy endpoint."""

import pytest


@pytest.mark.asyncio
async def test_save_personal_taxonomy_is_retired():
    from fastapi import HTTPException
    from app.routers.profile_pkg.taxonomy import save_personal_taxonomy

    with pytest.raises(HTTPException) as exc_info:
        await save_personal_taxonomy(
            {"categories": [{"cat1": "A.个人分类", "children": ["A1.子类"]}]},
            user={"id": 1, "is_admin": True},
        )

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_save_personal_taxonomy_rejects_empty_categories_with_retirement_contract():
    from fastapi import HTTPException
    from app.routers.profile_pkg.taxonomy import save_personal_taxonomy

    with pytest.raises(HTTPException) as exc_info:
        await save_personal_taxonomy(
            {"categories": []},
            user={"id": 1, "is_admin": True},
        )

    assert exc_info.value.status_code == 410
