# 修复计划

**Bug ID:** BUG-001, BUG-002
**日期:** 2026-05-10
**优先级:** P1

## 修复步骤

### 步骤 1: 修复增量更新中 original_question_sources 的合并逻辑

**文件:** `backend/app/db/operations.py`
**行号:** 189-191
**修改类型:** 修正

**修改前:**
```python
if new_q_text and new_q_text not in orig_qs:
    orig_qs.append(new_q_text)
    orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
```

**修改后:**
```python
if new_q_text:
    if new_q_text not in orig_qs:
        orig_qs.append(new_q_text)
        orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
    else:
        # 问题文本已存在：合并新 URL 到该条目的 sources 中
        for _oqs_item in orig_qs_src:
            if _oqs_item.get("question") == new_q_text:
                _oqs_urls = {s.get("url") for s in _oqs_item.get("sources", [])}
                if url not in _oqs_urls:
                    _oqs_item.setdefault("sources", []).append(new_source)
                break
```

### 步骤 2: 修复前端展开来源数量与 badge 一致

**文件:** `frontend/src/components/QuestionCard.vue`
**修改类型:** 修正 — 展开视图改为按 `sources` 列表渲染，不再按 `original_question_sources` 条目数渲染

**修改前（行 141-167）：** 按 `original_questions` 遍历，从 `original_question_sources` 查找来源

**修改后：** 按去重后的 `sources` 列表渲染扁平来源列表，确保展开条数 = badge 数

## 验证方法

1. 增量更新后，展开来源详情中的 [原文] 链接指向正确的面经 URL
2. 收起 badge 数 = 展开可见来源卡片数
3. 重建题库后数字仍然一致

## 回滚方案

回退 `operations.py` 和 `QuestionCard.vue` 的修改。
