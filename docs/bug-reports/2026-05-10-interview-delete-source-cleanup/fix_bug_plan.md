# 修复计划

**Bug ID:** BUG-003
**日期:** 2026-05-10
**优先级:** P2

## 修复步骤

### 步骤 1: 确认代码已有事务一致性保护
**文件:** `backend/app/routers/data.py`
**行号:** 177-182, 228-231

代码已在面经删除端点中调用 `_cleanup_sources_for_url()`：
- 单条删除：line 182
- 批量删除：line 231
- JD 删除：line 166-172（级联清理关联面经）

### 步骤 2: 确认 GET 端点过滤已删除面经的 oqs
**文件:** `backend/app/db/connection.py`
**行号:** 797-828

`filter_original_question_sources_by_mode` 查询 `interview.deleted_at IS NULL`，自动过滤指向已删除面经的 oqs 条目。

### 步骤 3: 重启服务加载最新代码
服务启动时间（01:48）早于代码修改时间（01:58），需重启以加载最新代码。

### 步骤 4: 验证测试
运行 `test_interview_delete_cleanup.py` 中的 17 个测试用例。

## 验证方法
1. 所有 17 个测试用例通过
2. 删除面经后检查 question_bank.sources 不再包含已删除 URL
3. 删除面经后前端题库来源正确更新

## 回滚方案
代码无实质性变更（已有修复），无需回滚。如需回滚测试文件，直接删除 `test_interview_delete_cleanup.py`。
