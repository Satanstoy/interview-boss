# ADR-0015: Release Manifest 采用不可变 JSON 与关系型索引

**Status:** accepted

评测系统的每个 Target Release 和 Evaluation Release 以不可变 JSON Release Manifest 作为权威快照，同时在数据库中建立可查询的关系型索引。数据库索引负责列表、筛选、状态和两类版本之间的引用；Manifest 原文负责完整审计、导出和重放。Evaluation Release 内部可以按 Benchmark、Judge、Harness 等职责分组，但这些分组不产生独立的公开版本。

Manifest 至少包含以下通用信息：

- Manifest schema 版本；
- 版本类型、目标类型、版本标识、版本标签和 parent release；
- 创建者、创建时间、状态和内容摘要；
- 代码与依赖快照；
- 运行时环境快照；
- 模型、Prompt、Skill、工具和采样配置；
- Target 或 Evaluation 类型特有的配置与外部 Artifact 引用。

`content_digest` 根据规范化后的完整 Manifest 内容计算。Manifest 创建后不得通过更新数据库索引或覆盖存储内容来改变其含义；任何会影响评测结果的变化都必须创建新的 Target Release 或 Evaluation Release。数据库中的索引字段可以冗余摘要，但不能成为历史重放所依赖的唯一配置来源。
