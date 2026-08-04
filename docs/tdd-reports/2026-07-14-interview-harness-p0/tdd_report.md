# 模拟面试 Harness P0 TDD 报告

## RED 阶段

新增测试首先暴露了真实缺口：

- executor 不接受 policy 参数，也没有共享 `enforce_tool_call`；
- request fingerprint、`TurnIdempotencyConflict` 和 turn status endpoint 尚不存在；
- prompt trust helper 和动态资料安全说明不存在；
- evaluator 没有 request ID、turn status 查询或 terminal contract；
- revision 测试初始无法复用原 user message。

实现过程中还捕获并修复了一个兼容性回归：ReAct 纯校验入口原有测试依赖原始 JSON 参数格式，现在线上 policy 路径仍返回规范化参数，legacy pure path 保留原格式但继续执行严格校验。

## GREEN 阶段

- 针对性 P0 回归：53 passed。
- 全量 chat 回归：878 passed、3 skipped。
- review hardening 后全量 chat 回归：883 passed、3 skipped。
- 前端生产构建：`vite build` 通过。

## 已交付行为

- `execute_tool()` 和 `validate_tool_call()` 共享工具授权边界；executor 直调用也不能绕过 state-derived policy。
- turn migration 044 增加 fingerprint 与 revision linkage；status API 绑定 conversation/user owner，并返回可安全读取的 assistant 内容和 metadata。
- 普通发送和 revision 使用同一 SSE/fence/finalize 路径；revision 保留原 assistant、不新增 user message，并写入 revision number。
- 动态 prompt 数据统一包裹 `<untrusted_context>`，嵌套标签会转义。
- evaluator 每轮生成 request ID，记录 turn ID，核对 terminal event 与持久化状态；契约失败会强制整场评测失败。
- review hardening 补充匿名 MCP public-only 身份、普通生成路径的 compressed/retrieved trust wrapper、完成 turn SSE replay、legacy fingerprint 惰性回填校验和 regenerate 请求体 `extra=forbid`。

## 未在 P0 实现

- P1 durable side-effect jobs、memory provenance、metadata/session notes optimistic concurrency。
- P2 CandidateSet、EvidenceBundle、TurnContract v2 和 event/read model。
