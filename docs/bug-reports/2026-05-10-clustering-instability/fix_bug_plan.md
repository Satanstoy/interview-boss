# 修复计划

**Bug ID:** BUG-001 ~ BUG-007
**日期:** 2026-05-10
**优先级:** P0/P1

## 总体策略
分两阶段修复：
1. **数据修复（无需重建）**：编写一次性脚本清理 sources、重算 frequency、补全 original_questions
2. **代码修复**：修复增量聚类链路中的 7 个 bug，防止数据再次被污染

---

## 步骤 1: 修复增量匹配上下文不足 (BUG-001)

**文件:** `backend/app/routers/submit.py`
**行号:** 648-651
**修改类型:** 修正

**修改前:**
```python
for r in existing_bank:
    cat2 = r.get('cat2') or ''
    if cat2 not in existing_by_cat2: existing_by_cat2[cat2] = []
    existing_by_cat2[cat2].append({"question_bank_id": r['id'], "question": r['question'], "all_questions": [r['question']]})
```

**修改后:**
```python
for r in existing_bank:
    cat2 = r.get('cat2') or ''
    if cat2 not in existing_by_cat2: existing_by_cat2[cat2] = []
    all_qs = [r['question']]
    try:
        orig = json.loads(r.get('original_questions') or '[]')
        all_qs.extend([q for q in orig if q and q != r['question']])
    except Exception:
        pass
    existing_by_cat2[cat2].append({
        "question_bank_id": r['id'],
        "question": r['question'],
        "all_questions": all_qs
    })
```

同时修改 `_load_existing_bank` 查询，增加 `original_questions` 字段：
```python
rows = conn.execute(f"SELECT id, question, cat2, sources, original_questions FROM question_bank WHERE {_where}", _params).fetchall()
```

---

## 步骤 2: 增量匹配后回写 original_questions (BUG-002)

**文件:** `backend/app/db/operations.py`
**行号:** 165-185
**修改类型:** 新增逻辑

在 matched 分支中，当 source 确实被新增时，同时将新题文本追加到 `original_questions` 和 `original_question_sources`：

```python
for m in matched:
    ...
    if url not in existing_urls:
        sources.append(new_source)
        # 回写 original_questions
        try:
            orig_qs = json.loads(existing_orig) if existing_orig else []
            orig_qs_src = json.loads(existing_orig_src) if existing_orig_src else []
        except:
            orig_qs, orig_qs_src = [], []
        new_q_text = row[3] if len(row) > 3 else ''
        if new_q_text and new_q_text not in orig_qs:
            orig_qs.append(new_q_text)
            orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
        cursor.execute(
            "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (len(sources), json.dumps(...), json.dumps(orig_qs), json.dumps(orig_qs_src), qb_id)
        )
```

需要在查询 existing 时同时 SELECT `original_questions` 和 `original_question_sources`。

---

## 步骤 3: 频率查询改为 mode-aware 动态计算 (BUG-004)

**文件:** `backend/app/routers/master_bank.py`
**行号:** 65-106
**修改类型:** 修正

在 `get_master_bank` 中：
1. 用 `get_dynamic_frequency_sql()` 替代直接 SELECT `qb.frequency`
2. 按动态频率排序
3. 在返回结果中用动态频率替换存储频率
4. sources 用 `filter_sources_by_mode()` 过滤后再返回

```python
@router.get("/api/master-bank")
async def get_master_bank(...):
    dyn_freq_sql = get_dynamic_frequency_sql(user.get('bank_mode', 'public'), user['id'])
    order_clause = f"ORDER BY ({dyn_freq_sql}) DESC" if sort != "recent" else "ORDER BY qb.id DESC"
    # SELECT 中加入动态频率
    rows = conn.execute(
        f"SELECT qb.id, qb.question, ..., ({dyn_freq_sql}) as dyn_frequency ...",
        ...
    )
    # 返回时用 dyn_frequency 替换 frequency，用 filter_sources_by_mode 过滤 sources
```

---

## 步骤 4: 删除面经时级联清理 sources (BUG-006)

**文件:** `backend/app/routers/data.py`
**行号:** 118-131
**修改类型:** 新增

在 `delete_data` 的软删除流程中，当删除 interview 时，调用清理逻辑移除 question_bank.sources 中对应 URL 的条目：

```python
if table_name == 'interview':
    if url:
        # 级联软删除关联的 questions_detail
        cursor.execute("UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP WHERE url = ? AND deleted_at IS NULL", (url,))
        # 清理 question_bank.sources 中该 URL 的条目
        _cleanup_sources_for_url(cursor, url)
```

同时在 `batch_delete_data` 中也加入相同逻辑。

新增通用函数 `_cleanup_sources_for_url(cursor, url)`：
```python
def _cleanup_sources_for_url(cursor, url):
    affected = cursor.execute("SELECT id, sources FROM question_bank WHERE sources LIKE ?", (f'%{url}%',)).fetchall()
    for r in affected:
        try:
            sources = json.loads(r['sources']) if r['sources'] else []
        except:
            sources = []
        new_sources = [s for s in sources if s.get('url') != url]
        if len(new_sources) != len(sources):
            cursor.execute(
                "UPDATE question_bank SET frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (len(new_sources), json.dumps(new_sources), r['id'])
            )
    cursor.execute("DELETE FROM question_bank WHERE frequency <= 0 AND owner_id IS NULL")
```

---

## 步骤 5: 将重建按钮移至设置面板 (BUG-007)

**文件:** `frontend/src/App.vue` + `frontend/src/components/SettingsPanel.vue`

1. 从 App.vue action bar 中移除重建按钮（保留进度指示器逻辑）
2. 在 SettingsPanel 中新增"危险操作"区域，放置重建按钮
3. SettingsPanel 需要新增 `build-master-bank` 和 `build-personal-bank` 事件

---

## 步骤 6: 一次性数据修复脚本（不重建）

编写 Python 脚本 `backend/scripts/fix_sources_frequency.py`，执行以下修复：

1. **清理 sources 中的重复 URL**：按 URL 去重，保留最具体的 company/round
2. **清理 sources 中指向已删除面经的条目**：join interview 表过滤 deleted_at
3. **重算 frequency**：`frequency = len(cleaned_sources)`
4. **补全 original_questions**：从 questions_detail 表反查，将属于同一聚类但不在 original_questions 中的题目文本补充进去

该脚本可在不触发全量重建的情况下修复现有数据。

---

## 验证方法

1. 运行数据修复脚本，检查 mismatched 数量归零
2. 上传测试面经，验证增量匹配后 original_questions 被正确更新
3. 删除面经后检查 QB.sources 是否被清理
4. 切换不同 bank_mode 查看频率是否正确变化
5. 在设置面板中测试重建按钮功能

## 回滚方案
修复前自动备份数据库：`cp interview-boss.db interview-boss.db.bak.fix-$(date +%s)`
