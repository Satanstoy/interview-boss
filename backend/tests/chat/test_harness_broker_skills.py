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
