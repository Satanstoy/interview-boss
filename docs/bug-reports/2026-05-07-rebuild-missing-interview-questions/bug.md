# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-07
**状态:** 已确认

## 问题概述
重建题库功能（`POST /api/master-bank/build`）在加载面经库题目时，从 `questions_detail` 表读取所有记录，无法按岗位过滤。这是因为 `questions_detail` 表缺少 `job_position` 列，而 `interview` 表同样缺少该列，导致面经数据与岗位之间没有关联关系。

## 根本原因分析

### BUG-001: `questions_detail` 表缺少 `job_position` 列
- **位置:** `backend/app/db/connection.py` (表定义) + `backend/app/routers/master_bank.py:167-172` (`_load()`)
- **症状:** 重建题库时，所有面经库的题目被无差别加载，不区分岗位
- **根因:** 数据库 schema 设计时未在 `questions_detail` 表中加入 `job_position` 列。面经提交时（`operations.py:60-67`），`_insert_details()` 写入 `questions_detail` 时不记录岗位信息。
- **影响:** 重建会将所有面经题目混入当前岗位题库，造成跨岗位数据污染
- **严重程度:** P0

### BUG-002: `interview` 表缺少 `job_position` 列
- **位置:** `backend/app/db/connection.py:42-52` (表定义)
- **症状:** 无法追溯某条面经属于哪个岗位
- **根因:** `interview` 表创建时未设计 `job_position` 字段
- **影响:** 即使想通过 `interview` 表关联 `questions_detail` 来过滤岗位，也无法实现
- **严重程度:** P0

### BUG-003: 答案恢复逻辑基于文本匹配，聚类后易失败
- **位置:** `backend/app/routers/master_bank.py:330-334`
- **症状:** 重建后部分已有 AI 答案丢失
- **根因:** `_save()` 中通过 `existing_answers_map.get(c['question'])` 恢复答案，但聚类后题目文本可能被 LLM 重写，导致文本匹配失败
- **影响:** 已生成的 AI 答案在重建后丢失，需要重新生成
- **严重程度:** P1

## 复现步骤
1. 提交一条面经，其中包含属于"后端开发"岗位的题目
2. 切换当前岗位到"前端开发"
3. 点击"重建题库"
4. **预期:** 重建只处理"前端开发"岗位的题目
5. **实际:** "后端开发"的面经题目也被加载并重建到"前端开发"题库中

## 修复建议
1. 给 `questions_detail` 表添加 `job_position` 列
2. 给 `interview` 表添加 `job_position` 列
3. 修改面经提交流程，写入正确的 `job_position`
4. 修改 `_load()` 函数，按 `job_position` 过滤
5. 优化答案恢复逻辑，使用 `original_questions` 匹配而非仅匹配统一后的问题文本
