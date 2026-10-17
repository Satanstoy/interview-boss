"""AC-006 / UR-006：匹配三态 —— 失败不等于新题。

契约（contracts.md §2.3）：

- ``match_outcomes`` 返回每个输入的显式结果：matched(canonical_id) / no_match /
  failed(error_code, retryable)；
- 模型 401、超时、漏 new_id、返回其它 scope 的 canonical_id 都属于 failed，
  **不得**记 no_match、不得触发新建 canonical；
- 结构错误只有有限修复机会，失败保留可恢复步骤；
- 只有真正无候选才允许 no_match（随后可在同 scope 建新题）。
"""

from __future__ import annotations

import json

import pytest

from app.services.clustering.matcher import match_outcomes


def _rows():
    return [
        {"id": 1, "ordinal": 1, "cat2": "TCP", "question": "TCP 三次握手"},
        {"id": 2, "ordinal": 2, "cat2": "TCP", "question": "TCP 四次挥手"},
    ]


def _candidates():
    return {
        "TCP": [
            {"id": 100, "question_bank_id": 100, "question": "TCP 握手过程"},
            {"id": 101, "question_bank_id": 101, "question": "TCP 可靠传输"},
        ]
    }


def _patch_llm(monkeypatch, payload):
    import app.services.clustering.matcher as matcher

    async def fake(prompt, **kwargs):
        if isinstance(payload, Exception):
            raise payload
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(matcher, "_call_llm_with_retry", fake)


async def test_matched_returns_canonical_id(monkeypatch):
    _patch_llm(
        monkeypatch,
        {"matches": [{"new_id": 1, "cluster_id": 100}], "unmatched": [2]},
    )
    result = await match_outcomes(_rows(), _candidates(), user_id=101)
    outcomes = {r["new_id"]: r for r in result["results"]}
    assert outcomes[1]["outcome"] == "matched"
    assert outcomes[1]["canonical_id"] == 100
    assert outcomes[2]["outcome"] == "no_match"


async def test_no_candidates_is_no_match(monkeypatch):
    result = await match_outcomes(_rows(), {"TCP": []}, user_id=101)
    assert all(r["outcome"] == "no_match" for r in result["results"])


async def test_model_401_is_failed_not_no_match(monkeypatch):
    from fastapi import HTTPException

    _patch_llm(monkeypatch, HTTPException(status_code=401, detail="Invalid API Key"))
    result = await match_outcomes(_rows(), _candidates(), user_id=101)
    assert result["results"], "必须返回每个输入的结果"
    for row in result["results"]:
        assert row["outcome"] == "failed"
        assert row["error_code"] in ("MODEL_AUTH_INVALID", "MODEL_CONFIG_MISSING")
        assert row["retryable"] is False
        assert "canonical_id" not in row or row["canonical_id"] is None


async def test_timeout_is_failed_with_retryable(monkeypatch):
    _patch_llm(monkeypatch, TimeoutError("upstream timeout"))
    result = await match_outcomes(_rows(), _candidates(), user_id=101)
    for row in result["results"]:
        assert row["outcome"] == "failed"
        assert row["error_code"] in ("UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE")
        assert row["retryable"] is True


async def test_missing_new_id_is_structure_error_not_no_match(monkeypatch):
    """模型既没匹配也没显式声明 2 号题（漏题）：必须 failed，不是 no_match。"""

    _patch_llm(monkeypatch, {"matches": [{"new_id": 1, "cluster_id": 100}]})
    result = await match_outcomes(_rows(), _candidates(), user_id=101, strict=True)
    outcomes = {r["new_id"]: r for r in result["results"]}
    assert outcomes[1]["outcome"] == "matched"
    assert outcomes[2]["outcome"] == "failed"
    assert outcomes[2]["error_code"] == "MODEL_OUTPUT_INVALID"
    assert outcomes[2]["retryable"] is True


async def test_out_of_scope_canonical_id_is_rejected(monkeypatch):
    """返回其它 scope 的 cluster_id：整组判为结构错误，不写入任何关联。"""

    _patch_llm(
        monkeypatch,
        {"matches": [{"new_id": 1, "cluster_id": 999}], "unmatched": [2]},
    )
    result = await match_outcomes(_rows(), _candidates(), user_id=101, strict=True)
    assert all(r["outcome"] == "failed" for r in result["results"])
    assert all(r["error_code"] == "MODEL_OUTPUT_INVALID" for r in result["results"])


async def test_duplicate_new_id_is_structure_error(monkeypatch):
    _patch_llm(
        monkeypatch,
        {
            "matches": [
                {"new_id": 1, "cluster_id": 100},
                {"new_id": 1, "cluster_id": 101},
            ],
            "unmatched": [2],
        },
    )
    result = await match_outcomes(_rows(), _candidates(), user_id=101, strict=True)
    assert all(r["outcome"] == "failed" for r in result["results"])


async def test_non_strict_mode_still_reports_failed_for_model_errors(monkeypatch):
    """宽松模式下模型错误同样不得当作 no_match。"""

    _patch_llm(monkeypatch, RuntimeError("boom"))
    result = await match_outcomes(_rows(), _candidates(), user_id=101, strict=False)
    assert all(r["outcome"] == "failed" for r in result["results"])
