# Bug 预览报告

**日期:** 2026-05-07
**问题:** 后端代码存在阻塞事件 loop、全表扫描、LLM 响应解析不一致等多个 Bug
**严重程度:** High（2 个）/ Medium（2 个）

## 初步诊断

### 问题现象
1. 异步端点中直接使用同步数据库调用，阻塞 FastAPI 事件循环，导致并发性能下降
2. 删除操作触发 question_bank 全表扫描，在数据量大时性能严重退化
3. LLM 响应解析方式不一致，部分路径缺少容错处理，可能因 markdown 包裹导致 JSON 解析失败
4. 关键 LLM 调用缺少重试机制，网络波动时直接失败

### 根本原因
1. `profile.py` 的 `get_public_profile` 端点在 async 函数体和辅助函数中直接调用 `get_db_connection()`，未通过 `run_db()` 包装
2. `data.py` 的 `delete_data` 和 `batch_delete_data` 使用 `SELECT id, sources FROM question_bank` 全表查询来清理来源引用
3. `master_bank.py` 的 `_tag_batch` 直接用 `json.loads()` 解析 LLM 响应，未使用 `_extract_json()` 容错包装
4. `submit.py:310` 直接调用 `client.chat.completions.create()` 而非使用 `_call_llm_with_retry()` 带重试的封装

### 影响范围
- **功能:** 用户配置读取、数据删除、题库重建、内容提交
- **用户:** 所有用户（高并发场景下尤为明显）
- **数据:** 不影响数据完整性，但可能导致请求超时或解析失败

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 性能退化 | High | 事件循环被阻塞，并发能力下降；大表删除时全表扫描 |
| 功能中断 | Medium | LLM 响应被 markdown 包裹时 JSON 解析失败 |
| 可靠性 | Medium | LLM 调用无重试，网络抖动直接报错 |
| 数据完整性 | Low | 不影响数据正确性 |
