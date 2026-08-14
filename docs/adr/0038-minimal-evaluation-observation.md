# ADR-0038: Evaluation Observation 采用最小公共外壳

**Status:** accepted

不同评测目标不强制输出同一种完整内部数据结构。Target Adapter 输出一个最小公共 Observation Envelope，目标类型特有的数据放入版本化 `payload`；通用评测链路只依赖公共外壳、声明的能力和相关 Artifact 引用。

1.0 的公共外壳为：

```json
{
  "status": "completed",
  "started_at": "...",
  "finished_at": "...",
  "duration_ms": 0,
  "contract_violations": [],
  "artifact_refs": [],
  "payload": {}
}
```

模拟面试可以在 `payload` 中保存 transcript、tool trace 和 state summary；面经提取可以保存 extracted questions 和分类结果；简历分析可以保存 sections、evidence 和 recommendations。Token/cost、详细状态转移等只在目标或 Harness 能可靠提供时记录，不作为所有目标的必填字段。

Observation Envelope 和 `payload_schema_version` 纳入 Eval Artifact/Release 的版本追踪；新增目标字段不破坏其他目标的通用评测流程。
