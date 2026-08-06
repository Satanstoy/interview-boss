"""LLM 结构化判断统一工具（实验结论 P4b）。

聚类验证层与检索 rerank 共用的"LLM JSON 判断 + 容错解析"：
- LLM 输出常带 markdown 代码块/前后解释文字，需容错提取
- 碎片恢复：整体 JSON 解析失败时逐个提取对象/数组元素

来源：聚类实验（experiments/ 的 norm_score_list / _extract_json_*）与
检索评估验证过的解析逻辑收敛。
"""

import json
import re


def parse_json_object(raw: str) -> dict | None:
    """从 LLM 输出提取 JSON 对象（容忍 markdown 代码块/前后文字/对象包裹）。

    Returns:
        dict | None: 解析出的对象；无法解析返回 None
    """
    text = _strip_fences(raw)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_json_list(raw: str) -> list | None:
    """从 LLM 输出提取 JSON 数组（容忍 markdown 代码块/前后文字）。

    Returns:
        list | None: 解析出的数组；无法解析返回 None
    """
    text = _strip_fences(raw)
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, list) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_score_items(raw: str) -> list[dict]:
    """从 LLM 打分输出提取评分条目（兼容数组/对象包裹/碎片恢复）。

    返回只含 ``{"score": ...}`` 的 dict 条目；无法解析返回 []。
    聚类验证层与检索评估的 norm_score_list 逻辑收敛于此。
    """
    data = parse_json_list(raw)
    if data is not None:
        return [x for x in data if isinstance(x, dict) and "score" in x]
    obj = parse_json_object(raw)
    if obj is not None:
        for k in ("scores", "results", "result", "items"):
            v = obj.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict) and "score" in x]
        if "score" in obj:
            return [obj]
    # 碎片恢复：逐个提取 {"id":..,"score":..} 对象
    out = []
    for m in re.finditer(r"\{[^{}]*\}", raw or ""):
        try:
            item = json.loads(m.group(0))
            if isinstance(item, dict) and "score" in item:
                out.append(item)
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def _strip_fences(raw: str) -> str:
    text = (raw or "").strip()
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
