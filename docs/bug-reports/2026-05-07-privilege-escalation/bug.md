# Bug 详细分析报告

**Bug ID:** BUG-006 ~ BUG-009
**发现日期:** 2026-05-07
**状态:** 已确认

## 问题概述
从普通用户视角遍历完整业务流程（上传→解析→题库→练习→查看记录），发现 4 个权限提升漏洞。

---

## BUG-006: generate-answer 端点无所有权校验

- **位置:** `backend/app/routers/master_bank.py:768`
- **症状:** 任何登录用户可调用 `POST /api/master-bank/generate-answer/{id}` 为任意题目生成/覆盖 AI 答案
- **根因:** 端点使用 `get_current_user`，查询时仅 `SELECT question, ai_answer FROM question_bank WHERE id = ?`，无 `owner_id` 或 `bank_mode` 可见性校验
- **影响:** 普通用户可覆盖公共题库或其他用户个人题库的 AI 答案
- **严重程度:** P0

## BUG-007: batch-generate-answers 端点无所有权校验

- **位置:** `backend/app/routers/master_bank.py:1018`
- **症状:** 任何登录用户可调用 `POST /api/master-bank/batch-generate-answers` 批量为任意题目 ID 生成答案
- **根因:** 与 BUG-006 相同，加载题目时无可见性过滤
- **影响:** 批量覆盖公共题库答案
- **严重程度:** P0

## BUG-008: evaluate-answer 端点无题目可见性校验

- **位置:** `backend/app/routers/master_bank.py:1318`
- **症状:** 任何登录用户可对不在其可见范围内的题目提交练习记录
- **根因:** `evaluate_answer` 接受任意 `question_id`，直接写入 `user_practice_history`，无可见性校验
- **影响:** 练习历史数据可被注入，影响个人统计和薄弱项分析
- **严重程度:** P1

## BUG-009: analytics 端点数据未按用户隔离

- **位置:** `backend/app/routers/analytics.py:46`
- **症状:** `GET /api/analytics` 返回全局数据，`jd` 和 `questions_detail` 查询无 `bank_mode` 过滤
- **根因:** `tech_counter` 和 `tag_counter` 直接查询全表，未应用 `_build_analytics_bank_filter`
- **影响:** 普通用户可看到所有用户的 JD 技术栈和面试题标签统计
- **严重程度:** P2

## 复现步骤

### BUG-006 复现
1. 以普通用户登录
2. 获取公共题目 ID（如 id=1）
3. 调用 `POST /api/master-bank/generate-answer/1`
4. 预期：403 拒绝
5. 实际：成功覆盖该题的 ai_answer

### BUG-007 复现
1. 以普通用户登录
2. 调用 `POST /api/master-bank/batch-generate-answers` body: `{"ids": [1,2,3]}`
3. 预期：403 拒绝或仅处理可见题目
4. 实际：成功为所有指定题目生成答案

### BUG-008 复现
1. 以普通用户 A 登录（bank_mode=public）
2. 获取用户 B 的个人题目 ID
3. 调用 `POST /api/evaluate-answer` body 含该 question_id
4. 预期：403 拒绝
5. 实际：成功写入 user_practice_history

### BUG-009 复现
1. 以普通用户登录（bank_mode=public）
2. 调用 `GET /api/analytics`
3. 预期：仅返回公共 approved 数据的统计
4. 实际：返回包含所有 JD 和 questions_detail 的全局统计

## 修复建议
- BUG-006/007: 在查询 question_bank 时加入 `_build_bank_where_clause` 可见性过滤
- BUG-008: 在记录练习前校验题目是否在用户可见范围内
- BUG-009: 对 jd 和 questions_detail 查询加入 bank_mode 过滤
