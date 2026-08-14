"""OAuth Gateway for InterviewBoss MCP — main FastAPI app."""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import auth
import db
from oauth import router as oauth_router
from proxy import proxy_mcp

app = FastAPI(title="InterviewBoss OAuth Gateway", version="0.1.0")

app.include_router(oauth_router)


@app.on_event("startup")
async def startup():
    auth.require_configured_secret()
    db.init_db()


@app.api_route("/mcp", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def mcp_endpoint(request: Request):
    return await proxy_mcp(request)


@app.api_route(
    "/mcp/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
)
async def mcp_catch_all(request: Request, path: str):
    return await proxy_mcp(request)


@app.get("/health")
async def health():
    return {"status": "ok"}
