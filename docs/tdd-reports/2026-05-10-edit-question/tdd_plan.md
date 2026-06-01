# TDD 开发计划

**功能名称:** 编辑聚类题目内容
**日期:** 2026-05-10
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述
支持用户直接编辑题库中聚类题目的内容（question 文本、cat1、cat2、tags、difficulty），无需通过 LLM re-tag 或 split/merge 间接修改。

## 验收标准
- [ ] 用户可以修改题目的 question 文本
- [ ] 用户可以修改题目的 cat1、cat2、tags、difficulty 分类字段
- [ ] 公共题目仅管理员可编辑，个人题目仅本人可编辑
- [ ] 修改 question 文本时同步更新 questions_detail 表
- [ ] 空字符串字段不会覆盖已有值
- [ ] 不存在的题目 ID 返回 404

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | 管理员编辑公共题目所有字段 | valid fields + admin | 200 + updated fields | ⏳ 待写 |
| T-002 | 普通用户编辑自己的个人题目 | valid fields + owner | 200 + updated fields | ⏳ 待写 |
| T-003 | 普通用户无权编辑公共题目 | valid fields + non-admin | 403 | ⏳ 待写 |
| T-004 | 非 owner 无权编辑他人个人题目 | valid fields + non-owner | 403 | ⏳ 待写 |
| T-005 | 编辑不存在的题目 | invalid id | 404 | ⏳ 待写 |
| T-006 | 部分字段更新（只改 tags） | partial fields | 200 + only tags changed | ⏳ 待写 |
| T-007 | 更新 question 时同步 questions_detail | new question text | questions_detail.question updated | ⏳ 待写 |

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 — 管理员编辑公共题目
- [ ] 循环 2: T-003 — 权限校验（非管理员不能编辑公共题）
- [ ] 循环 3: T-005 — 404 处理
- [ ] 循环 4: T-006 — 部分字段更新
- [ ] 循环 5: T-002 — 个人题目 owner 编辑
- [ ] 循环 6: T-004 — 非 owner 权限校验
- [ ] 循环 7: T-007 — questions_detail 同步
