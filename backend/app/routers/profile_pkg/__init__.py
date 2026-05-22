"""Profile 路由包 — 按领域拆分为多个子模块"""
from fastapi import APIRouter

from app.routers.profile_pkg.llm import router as llm_router
from app.routers.profile_pkg.taxonomy import router as taxonomy_router
from app.routers.profile_pkg.position import router as position_router
from app.routers.profile_pkg.email import router as email_router
from app.routers.profile_pkg.resume import router as resume_router

# 合并所有子路由为一个总路由
router = APIRouter()
for sub_router in [llm_router, taxonomy_router, position_router, email_router, resume_router]:
    router.include_router(sub_router)
