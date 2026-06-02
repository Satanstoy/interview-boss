# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-005
**发现日期:** 2026-06-02
**状态:** 已确认

## 问题概述
通过数据库聚类效果全面分析，发现聚类系统存在 5 个相互关联的质量问题。

## 根本原因分析

### BUG-001: 聚类缺少显式 cluster_id
- **位置:** `backend/app/db/migrations.py`, `backend/app/services/pipeline/batch.py`
- **症状:** 聚类信息靠 `frequency`（合并数）+ `original_questions`（JSON 数组）隐式表达
- **根因:** 数据模型设计时没有引入显式的聚类标识字段
- **影响:** API 和查询需要解析 JSON 才能获取聚类大小；无法通过简单字段标识聚类关系
- **严重程度:** P1

### BUG-002: merge_history 置信度大面积为 0
- **位置:** `backend/app/services/pipeline/batch.py:401,685`
- **症状:** 129 条 merge_history 中 123 条 confidence=0（95%）
- **根因:** 旧版 compaction 代码在 `_validate_merges` 抛异常时返回空 confidence_map，导致默认值 0.0 被记录
- **影响:** 无法追溯合并质量，无法区分高质量和低质量合并
- **严重程度:** P0

### BUG-003: 孤岛题目未被聚类
- **位置:** `backend/app/services/clustering.py`, `backend/app/services/pipeline/batch.py`
- **症状:** 通过 embedding 相似度扫描，发现 16 对 sim>0.90 的题目未被合并（包括完全相同的题目）
- **根因:** compact 只处理 frequency=1 的单例；full_recluster 成本高未被频繁执行；跨 cat2 的题目不参与同组聚类
- **影响:** 用户看到重复题目，练习体验差
- **严重程度:** P0

### BUG-004: E 分类体系不完整
- **位置:** `backend/app/core/prompts.py:100`, `backend/app/services/utils.py:9`
- **症状:** 数据库中存在 "E1.算法手撕" 和 "E1.算法手撕与数据结构" 两种 cat2 值
- **根因:** LLM 生成 cat2 时偶尔缩写，`normalize_category` 缺少 taxonomy 标准值校验
- **影响:** E 分类下的题目被分到不同 cat2，影响聚类分组
- **严重程度:** P1

### BUG-005: 未利用 merge-question API 修复孤岛
- **位置:** 无专门的批量修复端点
- **症状:** 有完整的 merge-question API 但没有用于批量修复孤岛
- **根因:** 缺少自动化脚本或管理端点将 embedding 相似度分析结果接入 merge 流程
- **影响:** 孤岛问题只能手动逐个修复，效率低
- **严重程度:** P1

## 复现步骤

### BUG-002 复现
```sql
SELECT COUNT(*) FROM merge_history WHERE confidence=0 AND is_rolled_back=0;
-- 结果: 123（应为 0）
```

### BUG-003 复现
```python
# 运行 embedding 全量比对
SELECT id, question FROM question_bank WHERE id IN (6309, 6331);
-- "Redis和Memcached的区别？" 出现在两个不同 cat2，sim=0.959
```

### BUG-004 复现
```sql
SELECT DISTINCT cat2 FROM question_bank WHERE cat2 LIKE 'E%';
-- 结果: E1.算法手撕, E1.算法手撕与数据结构（应统一）
```

## 修复建议
详见 fix_bug_plan.md
