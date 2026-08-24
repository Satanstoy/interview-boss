"""Harness-owned QuestionBroker and SkillResolver contracts."""


def test_question_broker_returns_one_authoritative_card_deterministically():
    from app.agents.chat.question_broker import QuestionBroker

    result = QuestionBroker().select(
        candidates=[
            {
                "question_ref": "q-2",
                "canonical_text": "如何做容量评估？",
                "dimension": "system_design",
                "score": 0.7,
                "source": "question_bank",
            },
            {
                "question_ref": "q-1",
                "canonical_text": "缓存击穿如何处理？",
                "dimension": "distributed_system",
                "score": 0.7,
                "source": "question_bank",
            },
        ],
        required_dimension="distributed_system",
    )

    assert result.question_card.question_ref == "q-1"
    assert result.question_card.authority_check is True
    assert result.question_card.source == "question_bank"
    assert result.candidates_considered == 2


def test_question_broker_rejects_untrusted_question_text():
    import pytest
    from app.agents.chat.question_broker import QuestionBroker

    with pytest.raises(ValueError, match="authority"):
        QuestionBroker().select(
            candidates=[
                {
                    "question_ref": "q-1",
                    "canonical_text": "",
                    "source": "model",
                }
            ]
        )


def test_question_broker_normalizes_bank_tool_records_for_react_context():
    from app.agents.chat.question_broker import normalize_question_candidate

    candidate = normalize_question_candidate(
        {"id": 17, "question": "Redis 缓存击穿怎么处理？", "cat2": "缓存"},
        source="question_bank",
    )
    assert candidate["question_ref"] == "17"
    assert candidate["canonical_text"] == "Redis 缓存击穿怎么处理？"
    assert candidate["dimension"] == "缓存"
    assert candidate["source"] == "question_bank"


def test_harness_react_binds_selected_card_and_appends_context_suffix():
    from app.agents.chat.harness_contract import build_harness_context_pack
    from app.agents.chat.react_loop import _bind_question_card_to_react, _append_harness_call_suffix

    state = {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "user_message": "我做过 Redis 缓存优化",
        "interview_config": {"difficulty": "mid"},
        "interview_state": {"next_focus": "缓存"},
        "recent_messages": [],
        "resolved_skills": [],
        "budget_snapshot": {"available_tokens": 1000},
    }
    state["context_pack"] = build_harness_context_pack(
        state=state,
        call_mode="observe_propose",
        action_id="turn-1:observe",
        call_suffix={"phase": "observe_propose"},
    )
    messages = []
    _bind_question_card_to_react(
        state,
        messages,
        tool_name="search_questions",
        output='{"ok": true, "items": [{"id": 9, "question": "缓存击穿怎么处理？", "cat2": "缓存"}]}',
    )

    assert state["question_card"]["question_ref"] == "9"
    assert "QuestionCard" in messages[-1]["content"]
    stable_hash = state["context_pack"].stable_prefix_hash
    suffix = _append_harness_call_suffix(state, {"question_card": state["question_card"]})
    assert "question_card" in suffix
    assert state["context_pack"].stable_prefix_hash == stable_hash


def test_skill_resolver_adds_version_compatibility_and_content_hash():
    from app.agents.chat.skills.defaults import get_default_registry
    from app.agents.chat.skill_resolver import resolve_skills

    resolved = resolve_skills(
        get_default_registry(),
        {"user_message": "我想讨论 Redis 缓存", "interview_profile": None},
        harness_version="2.0",
    )

    assert resolved
    assert all(skill.skill_version for skill in resolved)
    assert all(skill.harness_compatibility == "2.0" for skill in resolved)
    assert all(len(skill.content_hash) == 64 for skill in resolved)
