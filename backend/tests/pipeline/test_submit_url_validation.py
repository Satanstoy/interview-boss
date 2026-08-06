"""URL 协议校验：面经提交必须使用 http(s) 链接。

回归场景：用户粘贴 App 内部分享链接（internal://<base64>）作为面经 URL，
此前无校验直接入库，导致 question_sources 出现 33 行无效来源
（2026-06-04 批量导入 17 条 internal:// 面经）。
"""

from unittest.mock import AsyncMock, patch

import pytest


def _override_user():
    from app.asgi import app
    from app.core.auth import get_current_user

    USER = {"id": 1, "is_admin": 0, "username": "testuser"}
    app.dependency_overrides[get_current_user] = lambda: USER
    return app, get_current_user


@pytest.fixture
def _mock_background():
    """拦截 submit-jobs 的后台执行，避免测试里真的入队/跑任务。"""
    with patch(
        "app.worker.enqueue_submit_import_job", new=AsyncMock()
    ) as enq, patch(
        "app.worker.submit_import_task", new=AsyncMock()
    ) as task:
        yield enq, task


def test_submit_stream_v2_rejects_internal_url(client, mock_llm, mock_redis):
    """submit-stream-v2：internal:// 无效协议 → 400，不进入流水线"""
    app, dependency = _override_user()
    try:
        resp = client.post(
            "/api/submit-stream-v2",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={
                "url": "internal://5ildmcA5aKMt3W5UeGHkzQ",
                "text": "字节跳动一面：解释B树的原理、TCP三次握手",
                "target": "private",
            },
        )
        assert resp.status_code == 400
        assert "链接" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_submit_jobs_rejects_internal_url(client, mock_llm, mock_redis, _mock_background):
    """submit-jobs：internal:// 无效协议 → 400，不创建 job"""
    app, dependency = _override_user()
    try:
        resp = client.post(
            "/api/submit-jobs",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={
                "url": "internal://5ildmcA5aKMt3W5UeGHkzQ",
                "text": "美团一面：MySQL索引结构",
                "target": "private",
            },
        )
        assert resp.status_code == 400
        assert "链接" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_submit_jobs_rejects_random_text_url(client, mock_llm, mock_redis, _mock_background):
    """submit-jobs：纯文本/无协议字符串 URL → 400"""
    app, dependency = _override_user()
    try:
        resp = client.post(
            "/api/submit-jobs",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={
                "url": "not-a-url-at-all",
                "text": "腾讯二面：项目难点",
                "target": "private",
            },
        )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_submit_jobs_accepts_https_url(client, mock_llm, mock_redis, _mock_background):
    """submit-jobs：合法 https URL → 通过校验并创建 job（非 400）"""
    app, dependency = _override_user()
    try:
        resp = client.post(
            "/api/submit-jobs",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={
                "url": "https://www.xiaohongshu.com/explore/69ebf7ec000000001f0075ba",
                "text": "蚂蚁一面：Redis数据结构",
                "target": "private",
            },
        )
        assert resp.status_code != 400
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_submit_jobs_accepts_empty_url(client, mock_llm, mock_redis, _mock_background):
    """submit-jobs：留空 URL 仍允许（用户只提供文本）"""
    app, dependency = _override_user()
    try:
        resp = client.post(
            "/api/submit-jobs",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={"url": "", "text": "字节三面：自我介绍", "target": "private"},
        )
        assert resp.status_code != 400
    finally:
        app.dependency_overrides.pop(dependency, None)
