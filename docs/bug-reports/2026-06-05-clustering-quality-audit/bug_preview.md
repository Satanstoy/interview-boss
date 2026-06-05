# Bug 预览报告

**日期:** 2026-06-05
**问题:** 聚类系统存在 10 个质量缺陷，导致 56% 题目未被合并、管理端 API 运行时崩溃、embedding 预筛选完全失效
**严重程度:** Critical

## 初步诊断

### 问题现象
1. **56.3% 题目是孤岛**（frequency=1），即 183/325 活跃题目没有被合并到任何聚类
2. **Embedding 覆盖率为 0%** — 所有 325 条题目的 embedding 列都是 NULL，导致 FAISS 预筛选降级为全量扫描
3. **管理员回滚/反馈 API 必然崩溃** — merge_history 表缺少 `is_rolled_back` 等列，merge_feedback 表不存在
4. **6 个聚类测试失败** — prompt 负面案例被移除、migration 函数重命名后测试未更新
5. **"其他"分类 75% 孤岛率** — 30/40 题未合并（被策略性跳过）
6. **batch_v2.py 合并无历史记录** — 导致无法回滚

### 根本原因
聚类系统经历了多次迭代（V1→V2→三阶段），但遗留了以下技术债：
- migration 032 只添加了 embedding 列，但从未触发 backfill 写入实际数据
- admin_review.py 引用了尚未迁移的 schema 字段
- batch_v2.py 是独立实现，未复用 batch.py 的 `_do_merge_to_existing` 和 `_record_merge_history`
- prompt 迭代时移除了测试断言检查的负面案例
- 全量重聚 (`full_recluster_hybrid`) 只设置 `duplicate_of` 和 `frequency++`，不合并 sources/original_questions

### 影响范围
- **功能:** 管理员回滚、反馈、统计 API 全部不可用（SQL 报错）
- **数据:** 56% 题目未被聚类，用户体验差；embedding 未计算导致预筛选降级
- **用户:** 管理员（回滚/反馈）、所有用户（搜索质量差）

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | **Critical** | 管理员回滚/反馈/统计 API 运行时 SQL 报错 |
| 数据完整性 | **High** | 56% 孤岛率 + batch_v2 合并无历史记录 |
| 性能 | **Medium** | embedding 预筛选失效，每次全量扫描 |
| 测试覆盖 | **Medium** | 6 个测试失败，测试与实际代码不一致 |
