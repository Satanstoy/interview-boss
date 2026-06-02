# Bug 详细分析报告

**Bug ID:** BUG-002
**发现日期:** 2026-06-02
**状态:** 已修复

## 问题概述
聚类详情页中，当两道**文本完全相同**的题目来自不同公司时，后加入的公司来源不显示原题。

## 根本原因分析

### BUG-002: apply_matched 未更新已有原题的来源映射
- **位置:** `backend/app/services/pipeline/writer.py:83-90`
- **症状:** 聚类 #6080 "介绍项目" 有 3 个 sources（阿里国际、蚂蚁国际、中兴），但 `original_question_sources` 只映射了阿里国际和蚂蚁国际，中兴的来源丢失
- **根因:** `apply_matched` 中，当 `q_is_new=False`（原题文本已存在）且 `url_is_new=True`（来源 URL 是新的）时，只更新了 `sources` 列表，没有将新 URL 追加到 `original_question_sources` 中对应原题的 sources 数组
- **影响:** 前端按 `original_question_sources` 渲染原题-来源映射，导致后加入的同名题目来源不显示
- **严重程度:** P2（数据完整性问题，不影响核心功能）

## 复现步骤
1. 提交中兴面经，其中包含"介绍项目"
2. 该题匹配到已有聚类 #6080（之前来自阿里国际和蚂蚁国际）
3. 查看聚类详情 → 中兴的"介绍项目"没有原题显示

## 修复方案
在 `apply_matched` 中，当 `q_is_new=False` 且 `url_is_new=True` 时，找到 `oqs_src` 中对应的原题条目，将新来源追加到其 sources 数组。

## 修复前 vs 修复后
```python
# 修复前: q_is_new=False 时跳过 oqs_src 更新
if q_is_new:
    oqs.append(q)
    oqs_src.append({...})

# 修复后: 同名原题的新来源追加到已有映射
if q_is_new:
    oqs.append(q)
    oqs_src.append({...})
elif q and url_is_new:
    for oqs_entry in oqs_src:
        if oqs_entry.get('question') == q:
            oqs_entry.setdefault('sources', []).append({...})
            break
```
