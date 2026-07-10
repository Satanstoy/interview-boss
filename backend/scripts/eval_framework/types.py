"""Data classes and shared constants for the eval framework."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


# ── Constants ──────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_OUTPUT_DIR = Path("backend/data/evaluations")

SUMMARY_SIGNALS = (
    "面试总结",
    "整体表现",
    "模拟面试就到这里",
    "面试到这里结束",
    "面试就到这里",
    "就到这里",
    "有什么想问",
)

CORRECTION_OUTPUT_SIGNALS = (
    "不是生成式",
    "判别式",
    "encoder",
    "不支持事务",
    "不支持ACID",
    "向量索引库",
    "Least Recently Used",
    "最近最少使用",
)


# ── Data Classes ───────────────────────────────────────


@dataclass(frozen=True)
class CandidateLLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: int


@dataclass(frozen=True)
class JudgeLLMConfig:
    """Configuration for the LLM judge used in scoring and report generation."""

    api_key: str
    base_url: str
    model: str
    timeout: int


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    mode: str
    difficulty: str
    max_turns: int
    persona: dict[str, str]
    active_skills: list[str]
    scoring: dict[str, dict[str, Any]]
    extra_args: dict[str, Any] | None = None
    early_exit_check: Callable[[list[dict[str, Any]]], bool] | None = None
    # Turn-level candidate behavior injection: {turn_number: extra_instruction}
    candidate_prompt_overrides: dict[int, str] | None = None


# ── Personas ───────────────────────────────────────────

MID_LEVEL_PERSONA = {
    "model": "mimo-v2.5",
    "resume_text": (
        "211 硕士，2 年 RAG + Agent 开发经验。做过双路召回 + rerank 的 RAG 系统，"
        "用 LangChain/LangGraph 搭建过 Agent，Faiss 做向量检索，Redis 做缓存。"
    ),
    "ability_profile": """
- RAG 系统：熟练，做过双路召回 + rerank，了解 embedding 模型选型
- Agent 框架：熟悉 LangChain/LangGraph，了解 MCP 协议
- 向量数据库：用过 Faiss，了解 HNSW 原理，知道 IVF
- 数据库：MySQL 基础扎实（B+树、索引），Redis 常用（缓存、分布式锁）
- 算法：中等水平，常见题型（LRU、排序、二叉树）能做
- 系统设计：能做中等复杂度的设计
""",
    "opening": (
        "大家好，我叫张明，211硕士毕业，2年RAG和Agent开发经验。最近一份工作做了一个"
        "企业级RAG系统，用双路召回加rerank提升检索质量，用LangGraph搭建了多Agent协作框架。"
    ),
}

SENIOR_PERSONA = {
    "model": "mimo-v2.5",
    "resume_text": (
        "985 硕士，4 年后端 + 2 年 Agent 开发经验。从零搭建过 MCP 工具平台，"
        "对分布式系统（限流、熔断、幂等）有深入理解，发表过 CCF-B 论文。"
    ),
    "ability_profile": """
- Agent 平台：深入，从零搭建过 MCP Server + 工具市场
- 分布式系统：深入，限流（令牌桶/滑动窗口）、熔断、幂等重试
- 向量检索：深入，HNSW 构建原理、pgvector vs Faiss trade-off
- 数据库：深入，B+树叶分裂、聚簇索引、主键设计
- 算法：较强，能写 LRU Cache、滑动窗口、图搜索
- 系统设计：能做高并发场景设计（SSE 架构、Agent 编排）
""",
    "opening": (
        "大家好，我叫李强，985硕士，4年后端加2年Agent开发。最近在做MCP工具平台，"
        "从协议设计到Server实现到工具市场，全链路都参与过。之前还做过分布式限流和熔断的基础设施。"
    ),
}


# ── Helper Functions ───────────────────────────────────


def _check_ratio(numerator: int, denominator: int, threshold: float) -> bool:
    return denominator > 0 and numerator / denominator >= threshold


def _check_error_corrected(metrics: dict[str, Any], error_type: str) -> bool:
    correction_keywords = {
        "bert": ("encoder", "判别式", "不是生成式"),
        "faiss": ("不支持事务", "不支持ACID", "向量索引库"),
        "lru": ("Least Recently Used", "最近最少使用"),
    }
    keywords = correction_keywords.get(error_type, ())
    recent_assistant_texts = [
        str(turn.get("assistant") or "") for turn in metrics.get("recent_turns", [])
    ]
    return any(keyword in text for text in recent_assistant_texts for keyword in keywords)


def _candidate_asks_to_end(turns: list[dict[str, Any]]) -> bool:
    """Check if candidate asked to end the interview in the last turn."""
    if not turns:
        return False
    last_user = str(turns[-1].get("user") or "")
    return any(signal in last_user for signal in ("结束", "收尾", "就到这里", "先到这里"))


def _interviewer_forces_close(turns: list[dict[str, Any]]) -> bool:
    """Check if interviewer initiated closing (not candidate)."""
    for turn in turns[-2:]:
        assistant_text = str(turn.get("assistant") or "")
        if any(signal in assistant_text for signal in SUMMARY_SIGNALS):
            return True
    return False
