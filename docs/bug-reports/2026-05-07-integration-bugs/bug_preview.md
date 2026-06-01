# Bug 预览报告

**日期:** 2026-05-07
**问题:** 前后端 API 接口存在不匹配，导致功能异常
**严重程度:** High（1 个）/ Medium（2 个）

## 初步诊断

### 问题现象
1. 非管理员用户打开页面后，招聘季筛选器始终为空（`activeSeason` 为空字符串）
2. 管理员点击"重建题库"后，提示"重建完成，共 undefined 道题目"
3. 前端缺少 `fetchPublicProfile` API 函数，非管理员无法获取公开配置

### 根本原因
1. `loadActiveSeason()` 调用 `api.fetchProfile()`（`GET /api/profile`，仅管理员），非管理员收到 403 后被静默捕获，`activeSeason` 保持空值。后端已有 `GET /api/profile/public` 端点供所有用户使用，但前端未调用。
2. `triggerBuildMasterBank()` 调用 `api.buildMasterBank()`（使用 `post()` 发送普通 HTTP 请求），但后端 `POST /api/master-bank/build` 返回 `StreamingResponse`（SSE 格式）。`post()` 将 SSE 流作为纯文本返回，导致 `data.total_unique` 为 `undefined`。前端已有 `buildMasterBankSSE()` 函数（使用 `postSSE()`）但未被使用。
3. 后端 `GET /api/profile/public` 端点已实现，但前端 `api/index.js` 中未定义对应的 API 函数。

### 影响范围
- **功能:** 招聘季筛选、题库重建进度显示
- **用户:** 非管理员用户（BUG-001）、管理员用户（BUG-002）
- **数据:** 不影响数据完整性

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | High | 非管理员无法看到招聘季筛选；管理员重建题库无正确反馈 |
| 数据完整性 | Low | 不影响数据 |
| 安全风险 | Low | 不涉及安全问题 |
