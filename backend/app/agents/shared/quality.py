"""质量评估函数 — 纯规则检查，无 LLM 调用"""
import logging
from typing import List

logger = logging.getLogger("interview-boss")


def evaluate_extraction_quality(data: dict, content_type_hint: str = "") -> float:
    """评估提取质量 (0-10)

    检查项:
    - 0个题目 → 0.0 (致命)
    - 公司缺失 → -2.0
    - 面试轮次缺失 → -1.0
    - 题目数 < 2 → -3.0 (可疑)
    - 有极短题目(长度<4) → -1.0 (噪声)
    """
    score = 10.0
    questions = data.get("具体题目清单", [])

    if not questions:
        return 0.0
    if not data.get("公司") or data["公司"] == "未提供":
        score -= 2.0
    if not data.get("面试轮次") or data["面试轮次"] == "未提供":
        score -= 1.0
    if len(questions) < 2:
        score -= 3.0
    if any(len(q.strip()) < 4 for q in questions if isinstance(q, str)):
        score -= 1.0

    return max(0.0, score)


def evaluate_tagging_quality(rows: list[list[str]], valid_cat1: set = None, valid_cat2_by_cat1: dict = None) -> float:
    """评估分类质量 (0-10)

    检查项（按错误率归一化）:
    - 无效的 cat1
    - 无效的 cat2
    - 无效的难度标签(非 L1/L2/L3)

    最终分数 = 10 * (1 - 错误率)，归一化到 0-10。
    """
    if not rows:
        return 0.0

    valid_diffs = {"L1-基础", "L2-中等", "L2-中级", "L3-高级", "L3-困难"}
    error_count = 0

    for row in rows:
        if len(row) < 8:
            error_count += 1
            continue
        cat1 = row[4] if len(row) > 4 else ""
        cat2 = row[5] if len(row) > 5 else ""
        diff_tag = row[7] if len(row) > 7 else ""

        has_error = False
        if valid_cat1 and cat1 and cat1 not in valid_cat1 and "未分类" not in cat1:
            has_error = True
        if valid_cat2_by_cat1 and cat1 and cat2:
            expected = valid_cat2_by_cat1.get(cat1, set())
            if expected and cat2 not in expected and "未分类" not in cat2:
                has_error = True
        if diff_tag and diff_tag not in valid_diffs and diff_tag != "未知":
            has_error = True
        if has_error:
            error_count += 1

    error_rate = error_count / len(rows)
    score = 10.0 * (1.0 - error_rate)
    return max(0.0, min(10.0, round(score, 1)))


def evaluate_answer_quality(answer: str, question: str = "") -> float:
    """评估答案质量 (0-10)

    检查项:
    - 长度 < 50 → 1.0 (太短，几乎无效)
    - 开头包含"抱歉"/"无法" → 2.0 (LLM拒绝回答)
    - 非算法题包含代码块 → -1.0
    """
    if not answer:
        return 0.0

    score = 10.0
    if len(answer) < 50:
        return 1.0
    if any(answer.strip().startswith(p) for p in ("抱歉", "无法", "对不起")):
        return 2.0
    # 非算法题包含过多代码块
    code_blocks = answer.count("```")
    if code_blocks > 0 and question:
        algo_keywords = ("算法", "代码", "实现", "编程", "手撕", "写一个", "数据结构")
        if not any(kw in question for kw in algo_keywords):
            score -= 1.0 * min(code_blocks, 2)

    return max(0.0, score)


def should_retry(quality_score: float, retry_count: int, threshold: float = 3.0, max_retries: int = 2) -> bool:
    """判断是否应该重试"""
    if quality_score >= threshold:
        return False
    if retry_count >= max_retries:
        return False
    return True
