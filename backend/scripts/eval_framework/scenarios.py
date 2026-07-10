"""Scenario definitions for eval runs."""

from __future__ import annotations

from .types import Scenario, MID_LEVEL_PERSONA, SENIOR_PERSONA, _candidate_asks_to_end
from .rubrics import (
    LONG_SESSION_SCORING,
    ERROR_CORRECTION_SCORING,
    EARLY_CLOSE_SCORING,
    PROPER_END_SCORING,
    INSUFFICIENT_EVIDENCE_SCORING,
    COUNTER_QUESTION_SCORING,
    GREETING_SCORING,
    TOOL_TIMING_SCORING,
    NATURAL_CLOSING_SCORING,
    COUNTER_QUESTION_FLOW_SCORING,
)

SCENARIOS: dict[str, Scenario] = {
    "long_session_mid": Scenario(
        scenario_id="long_session_mid",
        mode="free_practice",
        difficulty="mid",
        max_turns=16,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=LONG_SESSION_SCORING,
        candidate_prompt_overrides={
            16: "这是最后一轮回答。回答完后，自然地表示'时间差不多了，今天先到这里'，给面试官一个收尾的机会。",
        },
    ),
    "long_session_senior": Scenario(
        scenario_id="long_session_senior",
        mode="free_practice",
        difficulty="senior",
        max_turns=20,
        persona=SENIOR_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=LONG_SESSION_SCORING,
        candidate_prompt_overrides={
            20: "这是最后一轮回答。回答完后，自然地表示'今天聊得很充实，差不多可以收了'，给面试官一个收尾的机会。",
        },
    ),
    "long_session_jd": Scenario(
        scenario_id="long_session_jd",
        mode="jd_resume",
        difficulty="mid",
        max_turns=16,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=LONG_SESSION_SCORING,
        extra_args={"jd_id": None},
        candidate_prompt_overrides={
            16: "这是最后一轮回答。回答完后，自然地表示'今天先到这里吧'，给面试官一个收尾的机会。",
        },
    ),
    "error_correction": Scenario(
        scenario_id="error_correction",
        mode="free_practice",
        difficulty="mid",
        max_turns=8,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
        ],
        scoring=ERROR_CORRECTION_SCORING,
        candidate_prompt_overrides={
            3: "[重要行为指令] 在你的回答中故意植入一个关于 BERT 的技术错误：说'BERT 是一个生成式模型，它通过自回归方式生成文本'。这是错误的（BERT 实际上是 encoder-only 的判别式模型），你要表现得像是真的相信这个错误观点。",
            5: "[重要行为指令] 在你的回答中故意植入一个关于 Faiss 的技术错误：说'Faiss 的 IVFFlat 索引支持 ACID 事务，可以保证数据一致性'。这是错误的（Faiss 不支持事务），你要表现得像是真的相信这个错误观点。",
        },
    ),
    "early_close_guard": Scenario(
        scenario_id="early_close_guard",
        mode="free_practice",
        difficulty="mid",
        max_turns=5,
        persona=MID_LEVEL_PERSONA,
        active_skills=["candidate-rhythm", "project-storytelling", "knowledge-answer"],
        scoring=EARLY_CLOSE_SCORING,
        early_exit_check=_candidate_asks_to_end,
        candidate_prompt_overrides={
            3: "[重要行为指令] 在回答完面试官的问题后，追加一句：'不好意思，时间有点紧，我们是不是可以先收尾？'。这是为了测试面试官是否会拒绝过早结束。",
        },
    ),
    "proper_end": Scenario(
        scenario_id="proper_end",
        mode="free_practice",
        difficulty="senior",
        max_turns=10,
        persona=SENIOR_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=PROPER_END_SCORING,
        candidate_prompt_overrides={
            10: "这是最后一轮回答。回答完后，自然地表示'今天聊得很深入，时间差不多了'，给面试官一个收尾总结的机会。",
        },
    ),
    "insufficient_evidence": Scenario(
        scenario_id="insufficient_evidence",
        mode="free_practice",
        difficulty="mid",
        max_turns=5,
        persona=MID_LEVEL_PERSONA,
        active_skills=["candidate-rhythm"],
        scoring=INSUFFICIENT_EVIDENCE_SCORING,
        candidate_prompt_overrides={
            3: "[重要行为指令] 对面试官的问题给出非常简短、模糊的回答，只说结论不给细节。比如只说'用过'、'做过'、'了解'，不展开解释。这是为了测试面试官是否会追问细节。",
            4: "[重要行为指令] 继续给出简短模糊的回答。如果面试官追问细节，你可以稍微展开一点，但仍然不够充分。",
        },
    ),
    "counter_question": Scenario(
        scenario_id="counter_question",
        mode="free_practice",
        difficulty="senior",
        max_turns=6,
        persona=SENIOR_PERSONA,
        active_skills=["candidate-rhythm", "project-storytelling", "knowledge-answer"],
        scoring=COUNTER_QUESTION_SCORING,
        candidate_prompt_overrides={
            4: "[重要行为指令] 在回答完面试官的问题后，主动向面试官提一个技术相关的问题，比如：'我想了解一下，贵团队在 XX 方面是怎么做的？'或'这个岗位日常工作中，XX 技术栈的使用频率高吗？'。这是为了测试面试官是否会回答候选人的反问。",
        },
    ),
    # ── New: prompt quality validation scenarios ──
    "greeting_role_adherence": Scenario(
        scenario_id="greeting_role_adherence",
        mode="free_practice",
        difficulty="mid",
        max_turns=6,
        persona={**MID_LEVEL_PERSONA, "opening": "面试官你好，我来参加今天的模拟面试。"},
        active_skills=["candidate-rhythm", "project-storytelling", "knowledge-answer"],
        scoring=GREETING_SCORING,
    ),
    "tool_timing": Scenario(
        scenario_id="tool_timing",
        mode="free_practice",
        difficulty="mid",
        max_turns=6,
        persona={**MID_LEVEL_PERSONA, "opening": "你好，我是今天的候选人。"},
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=TOOL_TIMING_SCORING,
    ),
    "natural_closing": Scenario(
        scenario_id="natural_closing",
        mode="free_practice",
        difficulty="mid",
        max_turns=14,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=NATURAL_CLOSING_SCORING,
    ),
    "counter_question_flow": Scenario(
        scenario_id="counter_question_flow",
        mode="free_practice",
        difficulty="mid",
        max_turns=8,
        persona=MID_LEVEL_PERSONA,
        active_skills=["candidate-rhythm", "project-storytelling", "knowledge-answer"],
        scoring=COUNTER_QUESTION_FLOW_SCORING,
        candidate_prompt_overrides={
            3: "[重要行为指令] 回答完面试官的问题后，追加一个反问：'您觉得这个方案在实际业务里好落地吗？有什么需要改进的地方？'",
        },
    ),
}
