import re
import base64


# LLM 生成的 cat2 变体 → 标准 taxonomy 值的映射
_TAXONOMY_ALIASES = {
    "E1.算法手撕与数据结构": "E1.数据结构",
    "E1.算法手撕": "E2.算法手撕",
}


def encode_image(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode('utf-8')


def normalize_category(text: str) -> str:
    """规范化分类名称，去除多余空格，统一格式，处理逗号分隔的多分类（取第一个）"""
    if not text:
        return text
    text = text.strip()
    # 处理逗号分隔的多分类：取第一个
    if ',' in text:
        text = text.split(',')[0].strip()
    text = re.sub(r'^([A-Za-z]+\d*)\.\s+', r'\1.', text)
    # taxonomy 别名映射: 将 LLM 变体映射到标准值
    if text in _TAXONOMY_ALIASES:
        text = _TAXONOMY_ALIASES[text]
    return text


def _extract_url_signature(url: str) -> str:
    """从 URL 中提取帖子唯一标识，用于增强去重"""
    if not url:
        return ""
    # 小红书：提取 /explore/ 后面的帖子 ID
    m = re.search(r'/explore/([a-f0-9]+)', url)
    if m:
        return f"xhs:{m.group(1)}"
    # 牛客：提取 discuss/ 后面的数字 ID
    m = re.search(r'/discuss/(\d+)', url)
    if m:
        return f"nc:{m.group(1)}"
    # Boss直聘：提取 job/ 后面的 ID
    m = re.search(r'/job_detail/([^?]+)', url)
    if m:
        return f"boss:{m.group(1)}"
    # 通用：去掉查询参数后的 URL 路径
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"generic:{parsed.netloc}{parsed.path}"
