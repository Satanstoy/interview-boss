# ADR 0049：岗位分类体系由系统统一维护

## 决策

岗位的标准分类体系由系统/管理员维护，用户不能创建、修改或分享个人 canonical taxonomy。个人题库和公共题库在同一岗位下使用相同的 `cat1`、`cat2` 和 `tags`，以保证聚类、统计、搜索和公共提交的一致性。

用户仍可选择目标岗位，并通过个人标签、收藏夹和练习分组进行个性化整理。

## 当前岗位

除已有的 Agent 岗位外，系统为以下 active 岗位记录了完整分类：

- `后端开发`
- `前端开发`
- `全栈开发`
- `测试开发`

分类定义的代码来源是 `backend/app/core/system_taxonomies.py`，数据库由 migration 104 幂等写入。Agent 的历史 `categories_json` 保留，只补充系统 tags；其他内置岗位的 `categories_json` 和 `tags_json` 都按 canonical 定义写入。migration 105 为岗位增加可恢复的 `is_deleted` 下线标记。个人 taxonomy 数据保留用于历史兼容，但运行时不再读取。

## 运行规则

- 新上传、重新标注、聚类、公共提交和聊天上下文只读取 `source='system'` 的 taxonomy。
- 普通用户只能选择 `job_positions` 中 active 的岗位。
- 管理员通过系统 taxonomy 接口维护分类和标签。
- 用户 taxonomy 的旧 API 返回 `410 Gone`，防止旧客户端继续制造个人分类数据。
- 岗位只能下线，不能物理删除；下线不会删除题目、面经、JD、聚类、队列或 taxonomy 历史数据，也不能下线最后一个 active 岗位。
