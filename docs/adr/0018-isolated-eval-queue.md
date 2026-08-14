# ADR-0018: 评测任务使用独立 Eval Queue 与 Worker Pool

**Status:** accepted

评测属于管理员异步计算域，不能与用户服务共享默认任务队列、并发额度或故障域。系统为评测建立独立的 `Eval Queue` 和 Worker Pool，承载 Eval Run 编排、Case/Replication 执行、Judge 和聚合任务。

隔离至少覆盖：

- ARQ queue namespace 和 Worker 进程；
- Worker 并发数、LLM provider 限流和成本预算；
- 任务超时、重试和积压策略；
- 监控、告警和故障恢复；
- 评测使用的凭证、工具夹具、测试数据和副作用边界。

评测队列不替代数据库任务生命周期。`eval_runs` 和其子任务记录负责业务状态、幂等、租约、重试和恢复；ARQ 只负责传递和执行任务。用户队列发生拥塞时不应拖慢评测，评测突发运行也不应影响普通用户请求。

1.0 阶段可以复用现有 ARQ 基础设施和数据库任务生命周期实现，但必须使用独立的 Eval Queue 配置和 Worker Pool；不得仅通过在默认 Worker 中新增 `eval_*` 函数来宣称资源隔离。
