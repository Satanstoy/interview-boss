# 2026-06-22 Chat Tools Gateway 与题目计划绑定设计文档

## 本次变更

- 新增设计文档：`docs/superpowers/specs/2026-06-22-chat-tools-gateway-question-plan-design.md`
- 设计范围结合：
  - Tool Gateway 契约硬化
  - `selected_question` 计划绑定
  - adherence 校验与 repair
  - 错误/空结果/metrics/metadata 统一

## 未改动内容

- 未修改业务代码。
- 未修改测试代码。
- 未修改 API、数据库、前端或部署配置。

## 后续建议

1. 进入 implementation plan 前先 review spec。
2. 第一阶段优先实现 Tool Gateway 契约。
3. 第二阶段再接入 question plan enforce/observe。
