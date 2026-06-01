# 前后端联动优化

**日期：** 2026-05-17
**类型：** TDD / 性能优化
**状态：** 完成

## 问题描述

1. 列表接口返回过多数据（ai_answer 全文、user_answer、original_question_sources 嵌套结构）
2. 零客户端缓存，fetchAnalytics 等接口被重复调用 10+ 次
3. postSSE 不抛 error 事件（与 uploadSSE 不一致）
4. popularTags 客户端遍历整个数组计算

## 解决方案

### 后端
- `get_master_bank` 新增 `compact` 参数：`ai_answer=null`、`user_answer=''`、`original_question_sources` 替换为 `source_labels` 扁平 map
- 新增 `GET /api/master-bank/{id}/detail` 懒加载端点
- `popular_tags` 服务端计算返回（Top 20）
- 移除前端未使用的 `status` 字段

### 前端
- `http.js` 添加 GET 请求 TTL 缓存（30s，100 条上限），导出 `invalidateCache`
- `postSSE` 添加 `data.type === 'error'` 抛出
- `fetchMasterBank` 默认 `compact=true`
- `QuestionCard` ai_answer/user_answer 懒加载（展开时调 detail 端点）
- `dedupedSources` 延迟计算（showSources 为 false 时跳过）
- `App.vue` 使用服务端 `popular_tags`（fallback 到客户端计算）

## 涉及文件
- `backend/app/routers/master_bank.py` — compact 模式 + detail 端点 + popular_tags
- `frontend/src/utils/http.js` — TTL 缓存 + postSSE 错误处理
- `frontend/src/api/index.js` — compact 参数 + invalidateCache 导出
- `frontend/src/components/QuestionCard.vue` — 懒加载 + 延迟计算
- `frontend/src/components/MasterBankList.vue` — update-answer 事件转发
- `frontend/src/App.vue` — popular_tags + onUpdateAnswer 处理

## 预期效果
- 列表接口响应体减少 40-60%（去掉 ai_answer 全文 + 嵌套 OQS）
- fetchAnalytics 等接口 30s 内复用缓存
- postSSE 错误事件正确传播
