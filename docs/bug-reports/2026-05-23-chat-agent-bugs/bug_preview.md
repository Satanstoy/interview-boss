# Bug 预览报告

**日期:** 2026-05-23
**问题:** 模拟面试 Chat Agent 存在 4 个 bug
**严重程度:** 2 High + 2 Medium

## 初步诊断

### BUG-001: `_llm_compress` 不传递 user_id（High）
- **位置:** `budget.py:204`
- **症状:** LLM 结构化压缩时无法使用用户特定的 API 配置
- **根因:** `compress()` 收到了 `user_id` 但 `_llm_compress` 调用时硬编码 `state_user_id=None`
- **影响:** 多用户环境下压缩可能使用错误的 API key 或 model

### BUG-002: SYSTEM_BUDGET 常量不一致（High）
- **位置:** `nodes.py:26` vs `budget.py:61`
- **症状:** 预算管理器认为系统 prompt 占 2000 字符，实际可占 3000 字符
- **根因:** 两处定义不同值，无统一来源
- **影响:** 上下文可能溢出 1000 字符，导致 API 报错或截断

### BUG-003: `generate_response` 错误内容作为正常 chunk 输出（Medium）
- **位置:** `nodes.py:323-334`
- **症状:** LLM 失败时，错误消息以 `chunk` 类型返回，前端无法区分
- **根因:** 错误 chunk 和正常 chunk 使用相同的 `type: "chunk"`
- **影响:** 错误消息被当作面试官回复保存到数据库

### BUG-004: `session_notes` 截断可能切断标签（Medium）
- **位置:** `nodes.py:395-396`
- **症状:** `updated_notes[-2000:]` 可能在 `[weakness]` 标签中间截断
- **根因:** 简单切片不感知行/标签边界
- **影响:** 下游解析器无法识别被截断的标签，丢失记忆数据

## 风险评估

| Bug ID | 风险类型 | 等级 | 说明 |
|--------|---------|------|------|
| BUG-001 | 功能异常 | High | 多用户压缩可能路由到错误 LLM |
| BUG-002 | 上下文溢出 | High | 预算计算偏差 1000 字符 |
| BUG-003 | 数据污染 | Medium | 错误消息被持久化为正常回复 |
| BUG-004 | 数据丢失 | Medium | session notes 中的记忆可能丢失 |
