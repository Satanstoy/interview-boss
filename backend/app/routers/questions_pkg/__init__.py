"""Questions 路由包 — 按职责拆分为 CRUD + 变异操作 + 批量操作"""
from fastapi import APIRouter

from app.routers.questions_pkg.mutations import router as mutations_router
from app.routers.questions_pkg.bulk import router as bulk_router

# 合并所有子路由为一个总路由
router = APIRouter()
for sub_router in [mutations_router, bulk_router]:
    router.include_router(sub_router)
