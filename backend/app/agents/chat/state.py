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
    conversation_id: str                    # 对话会话 ID
    user_id: int                            # 用户 ID
    user_message: str                       # 当前用户消息
    mode: str                               # 'jd_resume' | 'free_practice'
    jd_id: Optional[int]                    # 模式一关联的 JD ID
    jd_text: Optional[str]                  # JD 文本内容
    resume_text: Optional[str]              # 简历文本

    # === 记忆 ===
    memories: list[dict]                    # 用户长期记忆列表（按需加载完整内容）
    memory_summaries: list[dict]            # 记忆摘要列表（轻量级，用于 prompt 注入）
    resume_summary: Optional[str]           # 简历摘要（从记忆中提取）
    session_notes: str                      # 会话级累积笔记（增量记忆）
    interview_context: str                  # 面试上下文（岗位、分类、练习统计）
    job_position: Optional[str]             # 用户目标岗位名

    # === 上下文压缩 ===
    message_history: list[dict]             # 完整消息历史
    compressed_context: Optional[str]       # 压缩后的上下文摘要
    recent_messages: list[dict]             # 最近几轮完整消息
    budget_snapshot: Optional[BudgetSnapshotType]  # 上下文预算快照

    # === 意图分类 ===
    intent: str                             # 'interview_question' | 'practice_request' | 'chat' | 'follow_up'

    # === RAG 检索 ===
    keywords: list[str]                     # LLM 提取的检索关键词
    retrieved_questions: list[dict]         # FTS5 检索到的相关题目

    # === 输出 ===
    response: str                           # AI 面试官回复
    metadata: dict                          # 回复元数据（检索到的题目等）
