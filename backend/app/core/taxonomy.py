"""Versioned interview-question taxonomies and legacy label migration rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


TAXONOMY_VERSION = "1.1"


AGENT_TAXONOMY: dict[str, Any] = {
    "version": TAXONOMY_VERSION,
    "job_family": "agent_llm",
    "categories": [
        {
            "cat1": "A.项目与系统设计",
            "children": [
                "A1.项目介绍与背景",
                "A2.系统架构设计",
                "A3.难点攻关与优化",
                "A4.可靠性与复盘",
            ],
        },
        {
            "cat1": "B.LLM基础与Prompt",
            "children": [
                "B1.模型基础与推理",
                "B2.Prompt与上下文工程",
                "B3.结构化输出与模型调用",
                "B4.模型选型与成本优化",
            ],
        },
        {
            "cat1": "C.Agent编排与工具",
            "children": [
                "C1.Agent架构与工作流",
                "C2.工具调用与MCP协议",
                "C3.记忆与状态管理",
                "C4.规划与多智能体协作",
                "C5.AI Coding与代码智能",
            ],
        },
        {
            "cat1": "D.RAG与知识工程",
            "children": [
                "D1.RAG检索增强",
                "D2.数据处理与切分",
                "D3.向量/混合检索与重排",
                "D4.知识图谱与Graph RAG",
            ],
        },
        {
            "cat1": "E.语言与基础工程",
            "children": [
                "E1.Python语言基础",
                "E2.Python异步与并发",
                "E3.Java语言基础与集合",
                "E4.Java并发与JVM",
                "E5.框架/数据库/消息基础",
                "E6.操作系统与网络",
            ],
        },
        {
            "cat1": "F.评测、安全与运行",
            "children": [
                "F1.Agent评测与回归",
                "F2.安全/权限/隐私",
                "F3.可观测性与可靠性",
                "F4.部署与云原生",
                "F5.成本/延迟/质量权衡",
            ],
        },
        {
            "cat1": "G.算法与数据结构",
            "children": ["G1.数据结构", "G2.算法手撕"],
        },
        {"cat1": "Z.其他", "children": ["Z1.待复核"]},
    ],
}


BACKEND_TAXONOMY: dict[str, Any] = {
    "version": TAXONOMY_VERSION,
    "job_family": "backend",
    "categories": [
        {
            "cat1": "A.项目与系统设计",
            "children": [
                "A1.项目介绍与背景",
                "A2.系统架构设计",
                "A3.难点攻关与优化",
                "A4.可靠性与复盘",
            ],
        },
        {
            "cat1": "B.Java/Python语言与运行时",
            "children": [
                "B1.Java语言基础与集合",
                "B2.Java并发",
                "B3.JVM与垃圾回收",
                "B4.Python语言基础",
                "B5.Python异步与并发",
                "B6.Python工程化/测试/类型",
            ],
        },
        {
            "cat1": "C.框架与中间件",
            "children": [
                "C1.Spring与Spring Boot",
                "C2.ORM/RPC与微服务",
                "C3.FastAPI/Django与异步框架",
                "C4.消息队列与任务调度",
            ],
        },
        {
            "cat1": "D.数据库与存储",
            "children": [
                "D1.MySQL/SQL/索引",
                "D2.Redis与缓存",
                "D3.NoSQL与搜索",
                "D4.数据建模与一致性",
            ],
        },
        {
            "cat1": "E.操作系统与网络",
            "children": [
                "E1.Linux与进程线程",
                "E2.TCP/HTTP/RPC",
                "E3.IO模型与性能排障",
            ],
        },
        {
            "cat1": "F.分布式与高并发",
            "children": [
                "F1.高并发与限流",
                "F2.分布式事务与一致性",
                "F3.微服务与服务治理",
                "F4.消息与事件驱动",
            ],
        },
        {
            "cat1": "G.工程质量与交付",
            "children": [
                "G1.API设计与安全",
                "G2.测试与可观测性",
                "G3.Docker/Kubernetes/CI/CD",
                "G4.性能优化与故障排查",
            ],
        },
        {
            "cat1": "H.算法与数据结构",
            "children": ["H1.数据结构", "H2.算法手撕"],
        },
        {"cat1": "Z.其他", "children": ["Z1.待复核"]},
    ],
}


GENERIC_TAXONOMY: dict[str, Any] = {
    "version": TAXONOMY_VERSION,
    "job_family": "generic",
    "categories": [
        {
            "cat1": "A.项目与系统设计",
            "children": [
                "A1.项目介绍与背景",
                "A2.系统架构设计",
                "A3.难点攻关与优化",
                "A4.可靠性与复盘",
            ],
        },
        {
            "cat1": "B.语言与工程化",
            "children": [
                "B1.语言基础与数据模型",
                "B2.并发与异步",
                "B3.测试/类型/打包",
            ],
        },
        {
            "cat1": "C.数据与服务",
            "children": [
                "C1.框架与中间件",
                "C2.数据库与缓存",
                "C3.API与服务集成",
            ],
        },
        {
            "cat1": "D.运行与交付",
            "children": [
                "D1.操作系统与网络",
                "D2.部署与云原生",
                "D3.安全与可观测性",
            ],
        },
        {"cat1": "E.算法与数据结构", "children": ["E1.数据结构", "E2.算法手撕"]},
        {"cat1": "Z.其他", "children": ["Z1.待复核"]},
    ],
}


DEFAULT_TAXONOMY: dict[str, Any] = {
    **deepcopy(AGENT_TAXONOMY),
    "job_position": "agent开发/大模型应用开发/大模型开发",
}


def taxonomy_for_position(position: str | None) -> dict[str, Any]:
    """Return a fresh v1.1 taxonomy for a concrete position name."""
    from app.core.interview_distribution_config import derive_job_family

    family = derive_job_family(position)
    if family == "agent_llm":
        template = AGENT_TAXONOMY
    elif family == "backend":
        template = BACKEND_TAXONOMY
    else:
        template = GENERIC_TAXONOMY
    result = deepcopy(template)
    result["job_position"] = str(position or "").strip()
    return result


def _contains(text: str, *terms: str) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def _language_target(question: str, family: str) -> tuple[str, str] | None:
    """Choose the language/runtime child without an LLM call."""
    is_java = _contains(question, "java", "jvm", "spring", "hashmap", "hash map")
    is_python = _contains(question, "python", "asyncio", "fastapi", "django", "gil")
    is_async = _contains(question, "并发", "线程", "锁", "协程", "异步", "async", "gil")
    if family == "backend":
        if is_java and _contains(question, "jvm", "gc", "垃圾回收", "内存", "并发", "线程", "锁"):
            return "B.Java/Python语言与运行时", "B2.Java并发" if not _contains(question, "jvm", "gc", "垃圾回收") else "B3.JVM与垃圾回收"
        if is_java:
            return "B.Java/Python语言与运行时", "B1.Java语言基础与集合"
        if is_python and is_async:
            return "B.Java/Python语言与运行时", "B5.Python异步与并发"
        if is_python:
            return "B.Java/Python语言与运行时", "B4.Python语言基础"
        return None
    if family == "agent_llm":
        if is_java and is_async:
            return "E.语言与基础工程", "E4.Java并发与JVM"
        if is_java:
            return "E.语言与基础工程", "E3.Java语言基础与集合"
        if is_python and is_async:
            return "E.语言与基础工程", "E2.Python异步与并发"
        if is_python:
            return "E.语言与基础工程", "E1.Python语言基础"
    return None


def map_legacy_category(
    cat1: str | None,
    cat2: str | None,
    question: str | None,
    job_position: str | None,
) -> tuple[str, str, str]:
    """Map legacy labels to v1.1 labels using explicit, repeatable rules.

    The third return value is an audit reason. Unknown labels deliberately go
    to ``Z.其他/Z1.待复核`` instead of being guessed by a migration-time LLM.
    """
    from app.core.interview_distribution_config import derive_job_family

    old_cat1 = str(cat1 or "").strip()
    old_cat2 = str(cat2 or "").strip()
    text = f"{old_cat1} {old_cat2} {question or ''}"
    family = derive_job_family(job_position)

    if not old_cat1 or not old_cat2 or _contains(text, "未分类"):
        return "Z.其他", "Z1.待复核", "empty_or_unclassified"

    language = _language_target(text, family)
    if old_cat2.startswith("C1.") and language:
        return (*language, "legacy_language_split")

    if family == "agent_llm":
        agent_map = {
            "B1.": ("C.Agent编排与工具", "C1.Agent架构与工作流"),
            "B2.": ("D.RAG与知识工程", "D1.RAG检索增强"),
            "B3.": ("C.Agent编排与工具", "C2.工具调用与MCP协议"),
            "B4.": ("C.Agent编排与工具", "C3.记忆与状态管理"),
            "B5.": ("B.LLM基础与Prompt", "B2.Prompt与上下文工程"),
            "B6.": ("F.评测、安全与运行", "F1.Agent评测与回归"),
            "B7.": ("C.Agent编排与工具", "C5.AI Coding与代码智能"),
            "B8.": ("B.LLM基础与Prompt", "B4.模型选型与成本优化"),
        }
        for prefix, target in agent_map.items():
            if old_cat2.startswith(prefix):
                return (*target, "legacy_agent_category")
        if old_cat1.startswith("C."):
            broad = {
                "C2.": ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
                "C3.": ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
                "C4.": ("E.语言与基础工程", "E6.操作系统与网络"),
            }
            for prefix, target in broad.items():
                if old_cat2.startswith(prefix):
                    return (*target, "legacy_agent_foundation")
        if old_cat1.startswith("D."):
            return "F.评测、安全与运行", "F5.成本/延迟/质量权衡", "legacy_agent_system"
        if old_cat1.startswith("E."):
            return "G.算法与数据结构", "G1.数据结构" if _contains(text, "数据结构", "链表", "树", "LRU") else "G2.算法手撕", "legacy_algorithm"

    if family == "backend":
        backend_map = {
            "C2.": ("C.框架与中间件", "C1.Spring与Spring Boot"),
            "C3.": ("D.数据库与存储", "D1.MySQL/SQL/索引"),
            "C4.": ("E.操作系统与网络", "E2.TCP/HTTP/RPC"),
            "D1.": ("D.数据库与存储", "D2.Redis与缓存"),
            "D2.": ("F.分布式与高并发", "F1.高并发与限流"),
            "D3.": ("F.分布式与高并发", "F2.分布式事务与一致性"),
            "E1.": ("H.算法与数据结构", "H1.数据结构"),
            "E2.": ("H.算法与数据结构", "H2.算法手撕"),
        }
        for prefix, target in backend_map.items():
            if old_cat2.startswith(prefix):
                return (*target, "legacy_backend_category")

    if old_cat1.startswith("A."):
        child = {
            "A1.": "A1.项目介绍与背景",
            "A2.": "A2.系统架构设计",
            "A3.": "A3.难点攻关与优化",
            "A4.": "A4.可靠性与复盘",
        }
        for prefix, target_child in child.items():
            if old_cat2.startswith(prefix):
                return "A.项目与系统设计", target_child, "legacy_project_category"

    return "Z.其他", "Z1.待复核", "unmapped_legacy_category"
