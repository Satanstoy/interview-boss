# 修复计划

**Bug ID:** BUG-001 ~ BUG-004
**日期:** 2026-05-07
**优先级:** P1 (BUG-001, BUG-004) / P2 (BUG-002, BUG-003)

## 修复步骤

### 步骤 1: 修复 BUG-001 — 异步端点中同步阻塞调用

**文件:** `backend/app/routers/profile.py`
**行号:** 56-78
**修改类型:** 重构

**修改前:**
```python
async def get_public_profile(user: dict = Depends(get_current_user)):
    """公开配置（普通用户可访问）：岗位列表、分类配置、招聘季"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
            settings_map = {r['key']: r['value'] for r in rows}
            seasons = conn.execute(
                "SELECT DISTINCT season FROM interview WHERE season IS NOT NULL AND season != '' ORDER BY season"
            ).fetchall()
            season_list = [r['season'] for r in seasons]
            active = settings_map.get('active_season', '')
            if active and active not in season_list:
                season_list.append(active)
                season_list.sort()
        return settings_map, season_list

    settings, used_seasons = await run_db(_query)
    available_positions = _get_available_positions()
    with get_db_connection() as conn:
        user_row = conn.execute(
            "SELECT jp.name FROM users u LEFT JOIN job_positions jp ON u.current_position_id = jp.id WHERE u.id = ?",
            (user['id'],)
        ).fetchone()
    current_pos = (user_row['name'] if user_row and user_row['name'] else None) or settings.get('current_job_position') or DEFAULT_TAXONOMY['job_position']
    taxonomy_data = await run_db(lambda: get_taxonomy_for_position(current_pos))
```

**修改后:**
```python
async def get_public_profile(user: dict = Depends(get_current_user)):
    """公开配置（普通用户可访问）：岗位列表、分类配置、招聘季"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
            settings_map = {r['key']: r['value'] for r in rows}
            seasons = conn.execute(
                "SELECT DISTINCT season FROM interview WHERE season IS NOT NULL AND season != '' ORDER BY season"
            ).fetchall()
            season_list = [r['season'] for r in seasons]
            active = settings_map.get('active_season', '')
            if active and active not in season_list:
                season_list.append(active)
                season_list.sort()
            # 合并 _get_available_positions 的查询
            tax_rows = conn.execute("SELECT position_name FROM taxonomy ORDER BY position_name").fetchall()
            pos_rows = conn.execute("SELECT name FROM job_positions ORDER BY name").fetchall()
            seen = set()
            positions = []
            for r in tax_rows:
                if r['position_name'] not in seen:
                    seen.add(r['position_name'])
                    positions.append(r['position_name'])
            for r in pos_rows:
                if r['name'] not in seen:
                    seen.add(r['name'])
                    positions.append(r['name'])
            if not positions:
                positions = [DEFAULT_TAXONOMY["job_position"]]
            # 用户当前岗位
            user_row = conn.execute(
                "SELECT jp.name FROM users u LEFT JOIN job_positions jp ON u.current_position_id = jp.id WHERE u.id = ?",
                (user['id'],)
            ).fetchone()
        return settings_map, season_list, positions, user_row

    settings, used_seasons, available_positions, user_row = await run_db(_query)
    current_pos = (user_row['name'] if user_row and user_row['name'] else None) or settings.get('current_job_position') or DEFAULT_TAXONOMY['job_position']
    taxonomy_data = await run_db(lambda: get_taxonomy_for_position(current_pos))
```

**验证方法:** 并发发送 `/api/profile/public` 请求，确认无阻塞

---

### 步骤 2: 修复 BUG-002 — 删除操作全表扫描

**文件:** `backend/app/routers/data.py`
**行号:** 103, 122, 190
**修改类型:** 优化

**修改前 (line 103):**
```python
affected_rows = cursor.execute("SELECT id, sources FROM question_bank").fetchall()
```

**修改后 (line 103):**
```python
# 使用 JSON 函数预筛选包含目标 URL 的记录
affected_rows = cursor.execute(
    "SELECT id, sources FROM question_bank WHERE sources LIKE ?",
    (f'%{url}%',)
).fetchall()
```

同样修改 line 122 和 line 190。

**验证方法:** 确认删除功能正常，且不再全表扫描

---

### 步骤 3: 修复 BUG-003 — _tag_batch JSON 解析不一致

**文件:** `backend/app/routers/master_bank.py`
**行号:** 204
**修改类型:** 替换

**修改前:**
```python
result = json.loads(response.choices[0].message.content.strip())
```

**修改后:**
```python
from app.services.llm import _extract_json
result = _extract_json(response.choices[0].message.content)
```

**验证方法:** 触发题库重建，确认 markdown 包裹的 JSON 也能正确解析

---

### 步骤 4: 修复 BUG-004 — submit LLM 调用缺少重试

**文件:** `backend/app/routers/submit.py`
**行号:** 303-311
**修改类型:** 替换

**修改前:**
```python
llm_kwargs = dict(
    model=LLM_MODEL,
    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
    temperature=0.1,
)
if _should_use_response_format():
    llm_kwargs["response_format"] = {"type": "json_object"}
response = await client.chat.completions.create(**llm_kwargs)
parsed_data = _extract_json(response.choices[0].message.content)
```

**修改后:**
```python
from app.services.llm import _call_llm_with_retry
# 构建 prompt 供 _call_llm_with_retry 使用
user_text = ""
for item in user_content:
    if isinstance(item, dict) and item.get("type") == "text":
        user_text += item["text"]
    elif isinstance(item, str):
        user_text += item
response_text = await _call_llm_with_retry(
    prompt=user_text,
    system_msg=system_prompt,
    response_format={"type": "json_object"} if _should_use_response_format() else None
)
parsed_data = _extract_json(response_text)
```

**注意:** 此处需要处理图片内容的情况。`_call_llm_with_retry` 目前只支持文本 prompt。如果提交包含图片，需要保留原始调用方式但添加重试装饰器。简化方案：为 submit 路径添加一个支持 messages 参数的重试包装。

**简化方案:**
```python
from app.services.llm import _extract_json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import APIConnectionError, RateLimitError, APITimeoutError

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APITimeoutError, asyncio.TimeoutError)),
)
async def _call_llm_with_retry_messages(messages, **kwargs):
    response = await client.chat.completions.create(messages=messages, **kwargs)
    return response.choices[0].message.content.strip()

# 在 submit_data 中：
response_text = await _call_llm_with_retry_messages(
    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
    model=LLM_MODEL,
    temperature=0.1,
    **({"response_format": {"type": "json_object"}} if _should_use_response_format() else {})
)
parsed_data = _extract_json(response_text)
```

**验证方法:** 模拟 API 超时，确认自动重试 3 次

## 验证方法

1. 运行 pytest 测试套件
2. 手动测试各受影响端点
3. 检查日志确认重试行为

## 回滚方案

每个 Bug 修复独立提交，如需回滚可单独 revert 对应 commit。
