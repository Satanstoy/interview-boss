"""验证层覆盖（根因 #1）：高置信直通匹配可选二次验证"""


def test_partition_matches_by_risk_unchanged():
    """分区逻辑不变：高置信直通、中置信进验证"""
    from app.services.clustering.matcher import _partition_matches_by_risk

    matches = [
        {"new_id": "1", "cluster_id": "10", "confidence": 0.95},
        {"new_id": "2", "cluster_id": "11", "confidence": 0.85},  # >= 验证阈值 0.8 → 进验证
        {"new_id": "3", "cluster_id": "12", "confidence": 0.3},
        {"new_id": "4", "cluster_id": "13"},  # 无 confidence
    ]
    direct, needs = _partition_matches_by_risk(matches, "B1.Agent架构与范式")
    assert [m["new_id"] for m in direct] == ["1"]
    assert [m["new_id"] for m in needs] == ["2", "4"]  # 0.3 低于验证阈值被直接拒绝


def test_validate_direct_matches_disabled_by_default(monkeypatch):
    """默认关闭：高置信直通不验证（现状行为保持）"""
    from app.services.clustering.matcher import _validate_direct_matches_enabled

    monkeypatch.delenv("CLUSTER_VALIDATE_DIRECT", raising=False)
    assert _validate_direct_matches_enabled() is False


def test_validate_direct_matches_enabled_by_env(monkeypatch):
    """env=1 开启：高置信也进验证"""
    from app.services.clustering.matcher import _validate_direct_matches_enabled

    monkeypatch.setenv("CLUSTER_VALIDATE_DIRECT", "1")
    assert _validate_direct_matches_enabled() is True


async def test_direct_matches_routed_to_validation_when_enabled(monkeypatch):
    """开启后：高置信直通并入验证列表"""
    from app.services.clustering.matcher import _match_and_cluster_cat2

    calls = {"partition": None}

    async def fake_validate(matches, new_questions, existing_clusters, user_id):
        return ([m for m in matches if m["new_id"] == "1"], {})

    async def fake_llm(prompt, response_format, user_id):
        return {"matches": [
            {"new_id": "1", "cluster_id": "10", "confidence": 0.95},
            {"new_id": "2", "cluster_id": "11", "confidence": 0.6},
        ]}

    monkeypatch.setenv("CLUSTER_VALIDATE_DIRECT", "1")
    monkeypatch.setattr("app.services.llm._call_llm_with_retry", fake_llm)
    monkeypatch.setattr(
        "app.services.clustering.matcher._validate_merges", fake_validate
    )
    async def fake_cluster_unmatched(qs, user_id):
        return []

    monkeypatch.setattr(
        "app.services.clustering.matcher._cluster_unmatched",
        fake_cluster_unmatched,
    )
    monkeypatch.setattr(
        "app.services.clustering.matcher._apply_exact_candidate_matches",
        lambda cat2, nq, cands, unmatched: ([], set()),
    )
    async def fake_load_recent(cat2, days):
        return []

    monkeypatch.setattr(
        "app.services.clustering.matcher._load_recent_singletons",
        fake_load_recent,
    )

    result = await _match_and_cluster_cat2(
        cat2="B1.Agent架构与范式",
        new_questions=[
            {"id": "1", "question": "ReAct 是什么"},
            {"id": "2", "question": "Agent 死循环"},
        ],
        existing_clusters=[{"id": "10", "question": "ReAct 模式"}, {"id": "11", "question": "Agent 循环"}],
        user_id=1,
    )
    # 高置信 1 也走了验证（fake 验证放行 1，拒绝 2）
    assert len(result["matched"]) == 1
    assert result["matched"][0]["question"].startswith("ReAct")
