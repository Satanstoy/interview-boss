# 修复计划

**Bug ID:** BUG-001, BUG-002
**日期:** 2026-05-10
**优先级:** P1

## 修复步骤

### 步骤 1: 添加 original_question_sources 模式过滤函数

**文件:** `backend/app/db/connection.py`
**行号:** 770 之后
**修改类型:** 新增

在 `filter_sources_by_mode()` 函数之后新增一个针对 `original_question_sources` 的过滤函数。

**新增代码:**
```python
def filter_original_question_sources_by_mode(oqs_list: list, bank_mode: str, user_id: int) -> list:
    """根据 bank_mode 过滤 original_question_sources 中每条记录的 sources 子列表。"""
    if not oqs_list:
        return []
    # 收集所有 URL
    all_urls = set()
    for item in oqs_list:
        for s in item.get('sources', []):
            if s.get('url'):
                all_urls.add(s['url'])
    if not all_urls:
        return oqs_list
    with get_db_connection() as conn:
        placeholders = ','.join(['?'] * len(all_urls))
        rows = conn.execute(
            f"SELECT url, owner_id FROM interview WHERE url IN ({placeholders}) AND deleted_at IS NULL",
            list(all_urls)
        ).fetchall()
    url_owner = {r['url']: r['owner_id'] for r in rows}
    result = []
    for item in oqs_list:
        filtered_sources = []
        for s in item.get('sources', []):
            owner = url_owner.get(s.get('url'))
            if bank_mode == 'personal' and owner == user_id:
                filtered_sources.append(s)
            elif bank_mode == 'public' and owner is None:
                filtered_sources.append(s)
            elif bank_mode == 'mixed' and (owner is None or owner == user_id):
                filtered_sources.append(s)
        if filtered_sources:
            result.append({**item, 'sources': filtered_sources})
    return result
```

### 步骤 2: 在 GET 端点中调用过滤函数

**文件:** `backend/app/routers/master_bank.py`
**行号:** 103-106
**修改类型:** 修正

**修改前:**
```python
        try:
            d['original_question_sources'] = json.loads(d['original_question_sources']) if d['original_question_sources'] else []
        except Exception:
            d['original_question_sources'] = []
```

**修改后:**
```python
        try:
            raw_oqs = json.loads(d['original_question_sources']) if d['original_question_sources'] else []
        except Exception:
            raw_oqs = []
        d['original_question_sources'] = filter_original_question_sources_by_mode(raw_oqs, bank_mode, user['id'])
```

### 步骤 3: 修复前端 sourceCount 计算

**文件:** `frontend/src/components/QuestionCard.vue`
**行号:** 254-258
**修改类型:** 修正

**修改前:**
```javascript
const sourceCount = computed(() => {
  const q = props.question
  if (q.original_questions && q.original_questions.length > 0) return q.original_questions.length
  if (q.sources && q.sources.length > 0) return q.sources.length
  return 0
})
```

**修改后:**
```javascript
const sourceCount = computed(() => {
  const q = props.question
  if (q.sources && q.sources.length > 0) return q.sources.length
  return 0
})
```

## 验证方法

1. 重建题库后，确认每张题卡的"频率"数字 = "来源详情 N条"中的 N
2. 在 personal/mixed 模式下，确认来源详情只显示属于当前模式的来源
3. 增量分析新面经后，确认数字仍然一致

## 回滚方案

如果修复引入新问题，可回退三个文件的修改到 git 上一个 commit。
