# 2026-06-22 Chat Tools Gateway 与题目计划绑定实施计划

## 本次变更

- 新增实施计划：`docs/superpowers/plans/2026-06-22-chat-tools-gateway-question-plan.md`
- 计划基于已确认设计文档：`docs/superpowers/specs/2026-06-22-chat-tools-gateway-question-plan-design.md`
- 更新 `docs/CLAUDE.md`，记录 `docs/superpowers/plans/` 目录职责。

## 计划范围

- Tool Gateway Pydantic 契约与 envelope。
- `search_questions` / `draw_questions` 结构化输出。
- ReAct loop envelope 兼容。
- `selected_question` plan 选择、注入、adherence、repair。
- metadata 优先使用计划题。
- 文档与最终测试门控。

## 未改动内容

- 未修改业务实现代码。
- 未修改测试代码。
- 未运行后端测试；本次只产出 implementation plan。
