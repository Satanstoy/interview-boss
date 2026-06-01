# TDD 开发计划

**功能名称:** 两阶段流水线（Tag → Queue → Cluster）
**日期:** 2026-05-10
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

将面经分析流程从"每条面经独立做增量聚类"改为"打标签并发 → 队列缓冲 → 批量聚类串行"的两阶段流水线，消除孤儿数据和增量聚类质量问题。

## 架构设计

```
阶段1（并发）: 面经A → tag → questions_detail + enqueue
              面经B → tag → questions_detail + enqueue
              面经C → tag → questions_detail + enqueue

阶段2（串行）: queue达到batch_size 或 全部完成
              → 加载所有pending的questions_detail
              → 加载已有question_bank聚类
              → LLM聚类（新题+已有聚类一起处理）
              → 原子写入question_bank
```

## 验收标准

- [ ] 阶段1：面经打标签后只写 questions_detail，不碰 question_bank
- [ ] 阶段2：批量聚类时同时看到新题和已有聚类，一步到位
- [ ] 重新分析面经时，彻底清理旧的 questions_detail + question_bank 引用
- [ ] 队列持久化到 DB，重启不丢任务
- [ ] batch_size 触发 + 全部完成触发，两种方式都能正确触发聚类
- [ ] 聚类写入是原子的，失败则回滚，不留半成品
- [ ] user_practice_history 孤儿引用在重建时被清理

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | 队列入队出队基本操作 | interview_ids | 队列状态正确 | ⏳ 待写 |
| T-002 | 队列持久化到DB | 入队后重启 | 从DB恢复pending任务 | ⏳ 待写 |
| T-003 | 打标签只写questions_detail不碰QB | 一条面经 | qd有记录，QB无变化 | ⏳ 待写 |
| T-004 | 彻底清理旧数据 | 重新分析面经 | old oqs/oqs_source/qd全部清理 | ⏳ 待写 |
| T-005 | batch_size触发聚类 | 20条入队 | 自动触发聚类 | ⏳ 待写 |
| T-006 | 全部完成触发聚类 | 5条入队+全部tag完成 | 触发聚类（不足batch_size） | ⏳ 待写 |
| T-007 | 聚类看到已有聚类+新题 | 已有QB+新题 | LLM同时处理两者 | ⏳ 待写 |
| T-008 | 聚类写入原子性 | 聚类中途失败 | QB无变化，队列仍pending | ⏳ 待写 |
| T-009 | 重建清理practice_history | 有孤儿引用的PH | 孤儿记录被清理 | ⏳ 待写 |
| T-010 | 聚类后生成unified question | 2+题的聚类 | 有统一代表题 | ⏳ 待写 |

## 红-绿-重构循环计划

- [x] 循环 1: T-001 队列基本操作 ✅
- [x] 循环 2: T-002 队列持久化 ✅
- [x] 循环 3: T-003 打标签隔离 ✅
- [x] 循环 4: T-004 彻底清理 ✅ (实现 `_cleanup_old_sources_txn_v2`)
- [x] 循环 5: T-005/T-006 触发条件 ✅
- [x] 循环 6: T-007 聚类上下文 ✅
- [x] 循环 7: T-008 原子写入 ✅
- [x] 循环 8: T-009 孤儿清理 ✅
- [x] 循环 9: T-010 unified question ✅
