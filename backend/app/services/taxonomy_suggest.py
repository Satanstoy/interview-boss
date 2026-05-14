"""
AI智能生成分类体系服务

调用LLM根据目标岗位特征，生成推荐的一级大类和二级子类分类体系。
"""
import json
import re
import logging
from typing import List, Dict

from app.services.llm import raw_llm_call
from app.db.connection import save_taxonomy_for_position

logger = logging.getLogger(__name__)

# 生成分类建议的提示词模板
GENERATE_TAXONOMY_PROMPT = """你是一个面试题分类专家。请根据以下目标岗位，生成一套合理的面试题分类体系。

目标岗位：{position}

要求：
1. 生成 4-6 个一级大类（cat1），每个大类下包含 3-8 个二级子类（children）
2. 一级大类使用"A.xxx"、"B.xxx"格式，以大写字母开头
3. 二级子类使用"A1.xxx"、"A2.xxx"格式，编号与一级大类对应
4. 分类应覆盖该岗位的核心技能领域
5. 分类名称简洁明确，适合面试题归类

请严格以JSON格式输出，不要包含任何其他文字：
```json
[
    {{"cat1": "A.一级大类名称", "children": ["A1.子类1", "A2.子类2"]}},
    {{"cat1": "B.一级大类名称", "children": ["B1.子类1", "B2.子类2"]}}
]
```"""


def _parse_taxonomy_response(response: str) -> List[Dict]:
    """解析LLM返回的分类JSON响应

    Args:
        response: LLM返回的原始文本

    Returns:
        解析后的分类列表

    Raises:
        ValueError: 当响应格式无效时
    """
    # 尝试提取JSON代码块中的内容
    json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # 尝试直接解析整个响应
        json_str = response.strip()

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM返回的分类格式无效: {e}") from e

    # 验证基本结构
    if not isinstance(result, list):
        raise ValueError("LLM返回的分类格式无效: 应为列表")

    for item in result:
        if not isinstance(item, dict):
            raise ValueError("LLM返回的分类格式无效: 每项应为字典")
        if "cat1" not in item or "children" not in item:
            raise ValueError("LLM返回的分类格式无效: 缺少cat1或children字段")
        if not isinstance(item["children"], list):
            raise ValueError("LLM返回的分类格式无效: children应为列表")

    return result


async def generate_taxonomy_suggestion(position: str, user_id: int = None) -> List[Dict]:
    """调用LLM生成分类体系建议

    Args:
        position: 目标岗位名称
        user_id: 用户ID（用于获取用户的LLM配置）

    Returns:
        推荐的分类体系列表

    Raises:
        ValueError: 当岗位名为空或LLM返回格式无效时
        TimeoutError: 当LLM调用超时时
    """
    if not position or not position.strip():
        raise ValueError("岗位名不能为空")

    prompt = GENERATE_TAXONOMY_PROMPT.format(position=position.strip())

    try:
        response = await raw_llm_call(
            user_id=user_id,
            model=None,  # 使用默认模型
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4000,  # 需要足够的token输出完整JSON
        )
    except TimeoutError:
        logger.error(f"LLM调用超时: position={position}")
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"LLM调用失败: position={position}, error={error_msg}")

        # 提供更详细的错误信息
        if "500" in error_msg:
            raise Exception(f"LLM服务内部错误: {error_msg}") from e
        elif "Connection" in error_msg:
            raise Exception(f"网络连接失败: {error_msg}") from e
        elif "401" in error_msg or "403" in error_msg:
            raise Exception(f"LLM服务认证失败: {error_msg}") from e
        else:
            raise

    return _parse_taxonomy_response(response)


def save_taxonomy_suggestion(position: str, categories: List[Dict]):
    """保存AI生成的分类体系到数据库

    Args:
        position: 岗位名称
        categories: 分类体系列表
    """
    save_taxonomy_for_position(position, categories)
