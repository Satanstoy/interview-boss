"""URL 校验工具：面经/题目来源链接必须为 http(s) URL。

回归防护：用户提交或 admin 编辑面经链接时粘贴 App 内部分享链接
（internal://<base64>）或任意文本，此前无校验直接入库，导致
question_sources 出现大量无效来源（历史 33 行 internal:// 脏数据）。
"""

import re

from fastapi import HTTPException

_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def validate_source_url(url: str) -> str:
    """校验面经来源链接：非空时必须为 http(s) URL，返回 strip 后的值。

    Raises:
        HTTPException(400): 非空且非 http(s) 协议时拒绝。
    """
    url = (url or "").strip()
    if url and not _HTTP_URL_RE.match(url):
        raise HTTPException(
            status_code=400,
            detail="来源链接必须是有效的 http(s) 链接，请检查后重试（没有链接可以留空）",
        )
    return url
