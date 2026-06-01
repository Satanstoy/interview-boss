# Bug 预览报告

**日期:** 2026-05-22
**问题:** 面经库和 JD 库不根据用户岗位过滤，切换岗位后面经数据不变
**严重程度:** High

## 初步诊断

### 问题现象
用户切换岗位后，面经库和 JD 库的数据不随之变化。无论用户选择什么岗位，看到的都是同一份数据。

### 根本原因
`backend/app/routers/data.py` 的 `get_data` 端点使用 `get_current_job_position()`（全局岗位）而非 `get_user_job_position(user['id'])`（用户个人岗位）。

对比：
- **题库 API (questions.py)**: 使用 `get_user_job_position(uid)` → 按用户岗位过滤 ✅
- **面经/JD API (data.py)**: 使用 `get_current_job_position()` → 按全局岗位过滤 ❌

### 影响范围
- **功能:** 面经库、JD 库的岗位过滤失效
- **用户:** 所有用户（管理员和普通用户）
- **数据:** 面经表有 2 条脏数据 (`job_position='backend'`)

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | High | 岗位切换后面经/JD 数据不变化 |
| 数据完整性 | Low | 2 条脏数据需清理 |
| 安全风险 | Low | 无安全风险 |
