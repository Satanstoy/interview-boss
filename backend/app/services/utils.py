import re
import base64


def encode_image(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode('utf-8')


def normalize_category(text: str) -> str:
    """规范化分类名称，去除多余空格，统一格式（如 'A. 项目' → 'A.项目'）"""
    if not text:
        return text
    text = text.strip()
    text = re.sub(r'^([A-Fa-f]\d?)\.\s+', r'\1.', text)
    return text


def format_array_for_csv(data_array: list) -> str:
    if not isinstance(data_array, list) or not data_array:
        return str(data_array) if data_array else "未提供"
    return "\n".join([f"{i+1}. {item}" for i, item in enumerate(data_array)])


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
