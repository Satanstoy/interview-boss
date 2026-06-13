"""Chat Agent State — 面试对话状态机的状态定义"""

from typing import TypedDict, Annotated, Optional
from operator import add


class BudgetSnapshotType(TypedDict, total=False):
    """预算快照类型（与 budget.BudgetSnapshot dataclass 对应）"""

    system_chars: int
    compressed_chars: int
    memory_chars: int
    retrieved_chars: int
    recent_chars: int
    current_msg_chars: int
    total_chars: int
    available_chars: int
    utilization_pct: float
    compression_tier: str


class ChatState(TypedDict, total=False):
    """面试 Chatbot 的完整状态"""

    # === 输入 ===
    conversation_id: str  # 对话会话 ID
    user_id: int  # 用户 ID
    user_message: str  # 当前用户消息
    mode: str  # 'jd_resume' | 'free_practice'
    jd_id: Optional[int]  # 模式一关联的 JD ID
    jd_text: Optional[str]  # JD 文本内容
    resume_text: Optional[str]  # 简历文本
    model: Optional[str]  # 用户选择的模型（覆盖默认配置）
    bank_mode: Optional[str]  # 题库模式 public/personal/mixed

    # === 记忆 ===
    memories: list[dict]  # 用户长期记忆列表（按需加载完整内容）
    memory_summaries: list[dict]  # 记忆摘要列表（轻量级，用于 prompt 注入）
    resume_summary: Optional[str]  # 简历摘要（从记忆中提取）
    session_notes: str  # 会话级累积笔记（增量记忆）
    interview_context: str  # 面试上下文（岗位、分类、练习统计）
    job_position: Optional[str]  # 用户目标岗位名

    # === 上下文压缩 ===
    message_history: list[dict]  # 完整消息历史
    compressed_context: Optional[str]  # 压缩后的上下文摘要
    recent_messages: list[dict]  # 最近几轮完整消息
    budget_snapshot: Optional[BudgetSnapshotType]  # 上下文预算快照

    # === 意图分类 ===
    intent: str  # 'interview_question' | 'practice_request' | 'chat' | 'follow_up'
    answer_complete: bool  # 用户回答是否完整（面试官可以出下一题）

    # === RAG 检索 ===
    keywords: list[str]  # LLM 提取的检索关键词
    search_query: Optional[str]  # 基于对话上下文改写的检索查询
    retrieval_intent: Optional[
        str
    ]  # 检索意图: find_similar / expand_knowledge / review_weakness
    search_positive_terms: list[str]  # 结构化改写的正向检索词
    search_negative_terms: list[str]  # 结构化改写的负向排除词
    question_type: Optional[
        str
    ]  # 题目类型: project_followup / knowledge_probe / new_question
    retrieved_questions: list[dict]  # FTS5 检索到的相关题目

    # === 输出 ===
    response: str  # AI 面试官回复
    metadata: dict  # 回复元数据（检索到的题目等）

    # === 生成依据（basis） ===
    basis_type: str  # 'question' | 'resume' | 'conversation' | 'mixed' | 'none'
    basis_question_ids: list[int]  # 实际引用的题目 ID 列表
    basis_confidence: float  # 0.0-1.0，LLM 对依据的置信度
    should_show_references: bool  # 是否在前端显示参考信息

    # === Skills ===
    active_skills: list[str]  # 当前激活的 skill 名称列表（用于 prompt 注入）
    active_skill_instructions: list[dict]  # [{"skill_name": str, "instruction": str}] 当前 ReAct loop 待注入 system prompt；跨轮只持久化 skill_name

    # === 检索元数据 ===
    retrieved_questions: list[dict]  # RAG 检索到的相关题目
    rerank_metadata: dict  # Rerank 结构化结果
