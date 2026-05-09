# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-007
**发现日期:** 2026-05-10
**状态:** 已确认

## 问题概述
增量聚类系统存在多个相互关联的缺陷，导致聚类质量持续退化、频率数据不准确。这些问题使得系统越来越依赖全量重建来修复数据，但全量重建消耗大量 LLM Token。

---

## 根本原因分析

### BUG-001: 增量匹配上下文不足——只传顶层 question，不传 original_questions
- **位置:** `backend/app/routers/submit.py:651`
- **症状:** 增量匹配时 LLM 只看到聚类的顶层统一问题，看不到该聚类包含的所有原始题目变体。例如一个聚类包含"RAG 的召回策略"和"双路召回是为了解决幻觉问题对吗"，但匹配时 LLM 只看到"请详细解释 RAG 中的召回策略及其如何缓解幻觉问题"
- **根因:** `existing_by_cat2` 构建时 `all_questions` 只设为 `[r['question']]`，没有包含 `original_questions`
- **影响:** LLM 可用的匹配语义信息不足，导致本应匹配的新题被当成新题插入，产生重复聚类
- **严重程度:** P1

### BUG-002: 增量匹配后不回写 original_questions
- **位置:** `backend/app/db/operations.py:165-185`
- **症状:** 新题匹配到已有聚类后，只更新 frequency 和 sources，不将新题文本追加到 `original_questions` 和 `original_question_sources`
- **根因:** `_apply_incremental_txn` 中 matched 分支只做了增频和追加 source，完全没有操作 original_questions
- **影响:** 聚类的"记忆"只在全量重建时才更新，增量路径下聚类的原始题目列表永远不增长。配合 BUG-001，后续匹配可用的上下文越来越少
- **严重程度:** P1

### BUG-003: sources 包含已删除面经的 URL（32 条记录）
- **位置:** `backend/app/db/operations.py`（缺少清理逻辑）
- **症状:** 32 条 QB 记录的 sources JSON 中包含 `deleted_at IS NOT NULL` 的面经 URL
- **根因:** 面经被软删除时，未级联清理 question_bank.sources 中对应的条目。`_cleanup_old_sources_txn` 只在"重新分析面经"时调用，普通删除流程不调用
- **影响:** 频率虚增（sources 长度包含已删除的面经）
- **严重程度:** P1

### BUG-004: 频率查询不按 bank_mode 动态计算
- **位置:** `backend/app/routers/master_bank.py:80`
- **症状:** `get_master_bank` API 直接返回 `qb.frequency`（存储值），而非使用 `get_dynamic_frequency_sql()` 按当前用户的 bank_mode 动态计算
- **根因:** `get_dynamic_frequency_sql()` 已在 `connection.py:719` 实现但未被调用
- **影响:** 公共模式用户看到的频率包含了个人来源的数量；个人模式用户看到的频率包含了公共来源。排序和展示都不准确
- **严重程度:** P1

### BUG-005: sources 中仍有重复 URL（11 条记录）
- **位置:** 历史遗留（已在之前的修复中部分处理）
- **症状:** 11 条 QB 记录的 sources 中同一 URL 出现多次（不同 company/round 值）
- **根因:** 之前 sources 去重 key 为 `(url, company, round)`，历史数据中同一面经因不同轮次被记录为不同来源
- **影响:** 频率 = `len(sources)` > 唯一 URL 数
- **严重程度:** P2

### BUG-006: 删除面经时不级联清理 question_bank.sources
- **位置:** `backend/app/routers/data.py:118-131`
- **症状:** 删除面经只级联软删除 questions_detail，不清理 question_bank.sources 中的对应条目
- **根因:** 删除流程缺少对 sources JSON 的维护
- **影响:** sources 中残留已删除面经的 URL，频率虚增
- **严重程度:** P1

### BUG-007: "重建题库"按钮位置不合理
- **位置:** `frontend/src/App.vue:158-159`
- **症状:** 重建题库按钮直接暴露在题库页面的操作栏中，紧邻日常操作按钮，容易误触发
- **根因:** 该操作消耗大量 Token（全量 LLM 标注 + 聚类），不应是高频操作
- **影响:** 用户可能误触发导致不必要的 Token 消耗
- **严重程度:** P2

---

## 复现步骤

### BUG-001 + BUG-002 联合复现
1. 上传面经 A，包含题目"Redis 和 Memcached 的区别"，被新建为 QB 记录 X
2. 上传面经 B，包含题目"Redis 跟 Memcached 有什么不同"，LLM 匹配到 X → 增频
3. 此时 X 的 `original_questions` 仍为空（BUG-002）
4. 上传面经 C，包含题目"Memcached 和 Redis 区别是什么"，LLM 匹配时只看到 X 的顶层问题（BUG-001），可能匹配失败 → 创建重复聚类

### BUG-003 + BUG-006 联合复现
1. 上传面经 URL-1，聚类后 QB.frequency=1, sources=[{url: "URL-1"}]
2. 删除面经 URL-1 → questions_detail 被软删除，但 QB.sources 未清理
3. 重新上传面经 URL-2，包含相同题目，匹配到 QB → frequency=2, sources=[{url: "URL-1"}, {url: "URL-2"}]
4. 但 URL-1 已被删除，实际可见来源只有 1 个，频率显示为 2

## 修复建议
详见 `fix_bug_plan.md`
