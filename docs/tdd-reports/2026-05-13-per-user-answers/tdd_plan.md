# TDD 开发计划

**功能名称:** 用户级答案管理 + 参考答案复用
**日期:** 2026-05-13
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

公共题库答案以用户为单位独立维护：管理员的参考答案存储在 `question_bank.ai_answer`（全局），普通用户拥有独立的个人答案。当管理员已有参考答案时，普通用户可选择「使用参考答案」一键复制到个人答案，或「AI 生成」独立生成自己的答案。

## 验收标准

- [ ] 新建 `user_question_answers` 表，存储每用户每题的答案
- [ ] 新增 `POST /api/master-bank/use-reference-answer/{question_id}` 端点
- [ ] 修改 `POST /api/master-bank/generate-answer/{question_id}` 端点，答案存入用户表
- [ ] 修改 `GET /api/master-bank` 返回字段增加 `has_reference_answer` 和 `user_answer`
- [ ] 前端 QuestionCard 增加「使用参考答案」按钮（第三个按钮）
- [ ] 普通用户点击「使用参考答案」后，将管理员的 ai_answer 复制为个人答案
- [ ] 普通用户点击「AI 生成答案」后，答案存入个人表而非全局表
- [ ] 管理员行为不变：管理员的答案仍然写入 `question_bank.ai_answer`

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | DB 迁移：user_question_answers 表创建 | 启动 init_db | 表存在且有正确列 | ⏳ 待写 |
| T-002 | 使用参考答案：正常复制 | user_id, question_id with ai_answer | 返回复制的答案，user_question_answers 有记录 | ⏳ 待写 |
| T-003 | 使用参考答案：无参考答案 | user_id, question_id without ai_answer | 404 错误 | ⏳ 待写 |
| T-004 | 使用参考答案：已有人工答案时覆盖 | user_id, question_id with existing user_answer | 覆盖为参考答案 | ⏳ 待写 |
| T-005 | 生成答案（普通用户）：存入个人表 | user_id, question_id | user_question_answers 有新记录，question_bank.ai_answer 不变 | ⏳ 待写 |
| T-006 | 生成答案（管理员）：存入全局表 | admin_user_id, question_id | question_bank.ai_answer 更新 | ⏳ 待写 |
| T-007 | GET master-bank 返回 user_answer 和 has_reference_answer | user with answer, question with ai_answer | user_answer 字段有值，has_reference_answer 为 true | ⏳ 待写 |
| T-008 | GET master-bank：无参考答案时 has_reference_answer 为 false | question without ai_answer | has_reference_answer 为 false | ⏳ 待写 |

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 — DB 迁移
- [ ] 循环 2: T-002~T-004 — 使用参考答案端点
- [ ] 循环 3: T-005~T-006 — 生成答案端点改造
- [ ] 循环 4: T-007~T-008 — GET 端点改造
- [ ] 循环 5: 前端改造（QuestionCard + api/index.js）
