"""LangGraph State 定义 — Submit / BuildBank / BatchGenerate 三个流程的状态 TypedDict"""
from typing import TypedDict, Annotated, Optional
from operator import add


class SubmitState(TypedDict, total=False):
    """提交流程的完整状态"""
    # === 输入 ===
    raw_text: str                           # 用户输入的文本
    image_data: list[dict]                  # [{"content": bytes, "mime": str}] 图片列表
    url: str                                # 来源 URL
    season: str                             # 届次
    content_type_hint: str                  # "auto" | "jd" | "interview"
    target: str                             # "personal" | "public"
    user_id: int                            # 当前用户 ID
    is_admin: bool                          # 是否管理员
    job_position: str                       # 当前岗位

    # === 节点输出 ===
    doc_type: str                           # "JD" | "Interview" 由识别节点填入
    extracted_data: dict                    # LLM 提取的原始数据
    completion_attempted: bool              # 是否尝试了字段补全
    tagged_rows: list[list[str]]            # 分类结果 [url, company, round, q, cat1, cat2, tags, diff_tag]
    match_result: dict                      # 聚类匹配结果 {matched: [...], unmatched: [...]}
    saved_interview_id: int                 # 写入 DB 后的 interview ID
    answer_tasks: list[tuple[int, str]]     # 需要生成答案的 (question_id, question_text) 列表
    cluster_result: dict                    # 聚类结果

    # === 质量控制 ===
    extraction_quality: float               # 提取质量分数 (0-10)
    extraction_retries: int                 # 提取重试次数
    tagging_quality: float                  # 分类质量分数 (0-10)
    tagging_retries: int                    # 分类重试次数

    # === 可观测性 ===
    node_timings: dict                      # 每个节点的执行耗时
    error: str                              # 错误信息（如果有）
    llm_call_count: int                     # LLM 调用总次数
    total_tokens: int                       # Token 消耗估算
    taxonomy_config: dict                   # 分类体系配置

    # === 内部流转 ===
    saved_url: str                          # 最终使用的 URL（用户输入或自动生成）
    record_owner_id: int                    # 记录 owner_id
    record_status: str                      # 记录 status (approved/pending)


class BuildBankState(TypedDict, total=False):
    """题库重建流程状态"""
    # 输入
    user_id: int
    job_position: str
    # 流程状态
    backup_path: str
    total_questions: int
    processed_count: int
    current_batch: list[dict]
    cluster_results: list[dict]
    # 质量
    batch_quality_scores: list[float]
    # 可观测性
    events: Annotated[list[dict], add]
    progress_pct: float
    error: str


class BatchGenerateState(TypedDict, total=False):
    """批量生成答案流程状态"""
    # 输入
    question_ids: list[int]
    user_id: int
    skip_search: bool
    llm_scope: str
    search_scope: str
    # 流程状态
    current_index: int
    current_question: str
    current_answer: str
    answer_quality: float
    retry_count: int
    results: Annotated[list[dict], add]     # {id, quality, elapsed, success}
    events: Annotated[list[dict], add]
    success_count: int
    fail_count: int
    error: str
