# Bug 详细分析报告

**Bug ID:** BUG-006
**发现日期:** 2026-05-22
**状态:** 已确认

## 问题概述

面经库和 JD 库不按用户岗位过滤。用户切换岗位后，面经数据不变化。根因是 `data.py` 的 `get_data` 端点使用全局岗位函数 `get_current_job_position()` 而非用户级函数 `get_user_job_position(user_id)`。

## 根本原因分析

### BUG-006: 面经/JD 库不按用户岗位过滤

- **位置:** `backend/app/routers/data.py:183-184`
- **症状:** 切换岗位后面经库和 JD 库数据不变
- **根因:** `get_data` 端点使用 `get_current_job_position()`（读 `user_profile` 表的全局值），而非 `get_user_job_position(user['id'])`（读用户个人 `personal_position` 或 `current_position_id`）
- **对比:** 题库 API (`questions.py`) 已经正确使用 `get_user_job_position(uid)`
- **影响:** 所有用户的面经/JD 岗位过滤失效
- **严重程度:** P1

## 复现步骤

1. 用户 A 设置岗位为 "agent开发"
2. 打开面经库，看到数据
3. 切换岗位到 "后端开发"
4. 再次打开面经库
5. **预期:** 数据应按 "后端开发" 过滤
6. **实际:** 数据不变，仍显示所有岗位的数据

## 修复建议

将 `data.py` 中的 `get_current_job_position()` 替换为 `get_user_job_position(user['id'])`。
