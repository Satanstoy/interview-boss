# Bug 预览报告

**日期:** 2026-06-02
**问题:** 聚类系统存在 5 个系统性质量问题：缺少显式 cluster_id、置信度大面积为 0、孤岛题目未合并、E 分类需要拆分、未充分利用 merge API
**严重程度:** High

## 初步诊断

### 问题现象
1. 数据库中 232 道存活题目，522 道原始题目，去重率 55.6%，但通过 embedding 分析发现至少 16 对高相似度（>0.90）题目未被合并
2. merge_history 中 95% 的记录置信度为 0，无法追溯合并质量
3. E 分类存在命名混乱（E1.算法手撕 vs E1.算法手撕与数据结构）
4. 聚类模型缺少显式的 cluster_id 标识

### 根本原因
1. **无 cluster_id**: 聚类信息靠 frequency + original_questions JSON 隐式表达，没有显式标识
2. **置信度丢失**: compaction 操作执行时 `_validate_merges` 可能抛异常返回空 confidence_map，或旧版代码未记录置信度
3. **孤岛遗漏**: compact 操作只处理 frequency=1 的单例，高 frequency 题目间的遗漏无法覆盖
4. **E 分类**: LLM 生成 cat2 时偶尔缩写，`normalize_category` 缺少 taxonomy 校验
5. **API 利用不足**: 有完整的 merge-question 接口但未用于批量修复孤岛

### 影响范围
- **功能:** 聚类去重效果下降，用户看到重复题目
- **用户:** 所有使用题库练习的用户
- **数据:** merge_history 置信度缺失，聚类可追溯性差

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Medium | 重复题目影响练习体验 |
| 数据完整性 | High | merge_history 置信度大面积丢失 |
| 安全风险 | Low | 无安全风险 |
