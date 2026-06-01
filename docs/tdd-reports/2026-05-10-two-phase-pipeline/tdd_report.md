# TDD 开发完成报告

**功能名称:** 两阶段流水线（Tag → Queue → Cluster）
**完成日期:** 2026-05-10
**TDD 状态:** ✅ 完整

## 执行摘要

| 指标 | 结果 |
|------|------|
| 完成测试数 | 36（21 单元 + 15 端到端） |
| TDD循环数 | 10 |
| 最终测试通过率 | 100% |
| 重构次数 | 2 |

## 架构变更

### 旧架构（问题）
```
面经A → [tag → match → save] → 首经B → [tag → match → save]
              ↑ 每步都读写 question_bank，互相干扰
```

### 新架构（修复）
```
阶段1（并发）: 面经A → tag → questions_detail + enqueue
              面经B → tag → questions_detail + enqueue

阶段2（串行）: queue达到batch_size 或 全部完成
              → 加载所有pending的questions_detail
              → 加载已有question_bank聚类
              → LLM聚类（新题+已有聚类一起处理）
              → 原子写入question_bank
```

## 修复的问题

| Bug | 问题 | 修复方式 |
|-----|------|----------|
| AI答案丢失 | `cluster_batch` 查询已有QB时未SELECT `ai_answer`，导致重新聚类时AI答案丢失 | 在existing_rows查询中添加 `ai_answer` 字段 |
| 孤儿数据 | `_cleanup_old_sources_txn` 不清理 original_questions | 新增 `_cleanup_old_sources_txn_v2`，彻底清理 oqs/oqs_sources/qposition |
| 增量聚类质量差 | `MATCH_PROMPT` 上下文贫乏 | 删除增量匹配，改为批量聚类（新题+已有聚类一起处理） |
| 并发干扰 | 面经间共享 QB 状态 | 阶段1无共享状态，阶段2串行执行 |
| rebuild 孤儿 PH | 重建不清理 practice_history | 在 `_save()` 中增加 PH 清理 |
| batch 无断点续传 | 非 SSE 端点无状态持久化 | 队列持久化到 DB，重启可恢复 |

## 文件变更

| 文件 | 变更 |
|------|------|
| `backend/app/services/pipeline.py` | **新增** - 两阶段流水线核心（队列管理 + 打标签 + 批量聚类） |
| `backend/app/db/operations.py` | 新增 `_cleanup_old_sources_txn_v2` + `submit_interview_txn_tag_only` |
| `backend/app/db/connection.py` | 新增 `analysis_queue` 表 |
| `backend/app/routers/interview.py` | 重写 reprocess 端点，使用新 pipeline |
| `backend/app/routers/submit.py` | 公共题库提交改用 queue 模式 |
| `backend/app/routers/master_bank.py` | rebuild 增加 practice_history 清理 |
| `backend/tests/test_two_phase_pipeline.py` | **新增** - 21 个测试用例 |
| `backend/tests/test_analysis_flow.py` | 更新 BUG-003/004 测试适配新架构 |

## 测试覆盖

| 测试ID | 场景 | 状态 |
|--------|------|------|
| T-001 | 队列入队出队基本操作 | ✅ PASS |
| T-002 | 队列持久化到DB | ✅ PASS |
| T-003 | 打标签只写questions_detail | ✅ PASS |
| T-004 | 彻底清理旧数据 | ✅ PASS |
| T-005 | batch_size触发聚类 | ✅ PASS |
| T-006 | 全部完成触发聚类 | ✅ PASS |
| T-007 | 聚类上下文完整性 | ✅ PASS |
| T-008 | 聚类写入原子性 | ✅ PASS |
| T-009 | 孤儿practice_history清理 | ✅ PASS |
| T-010 | unified question生成 | ✅ PASS |

### 端到端测试（15 个）

| 测试ID | 场景 | 状态 |
|--------|------|------|
| E2E-001 | 单条面经完整流程（标签→入队→聚类→QB生成） | ✅ PASS |
| E2E-002 | 多条面经批量处理（相同cat2合并） | ✅ PASS |
| E2E-003 | 重建题库（清空→入队→聚类→练习历史清理） | ✅ PASS |
| E2E-004 | 阶段1不碰question_bank | ✅ PASS |
| E2E-005 | 重新聚类无重复sources | ✅ PASS |
| E2E-006 | 队列状态生命周期（pending→processing→done/failed） | ✅ PASS |
| E2E-007 | 清理指定URL的oqs，保留其他URL | ✅ PASS |
| E2E-008 | 所有来源移除后QB删除+question_position清理 | ✅ PASS |
| E2E-009 | 清理不存在的URL不报错 | ✅ PASS |
| E2E-010 | 空题目列表不产生数据 | ✅ PASS |
| E2E-011 | 空队列出队返回空 | ✅ PASS |
| E2E-012 | 空列表标记完成不报错 | ✅ PASS |
| E2E-013 | 空batch聚类返回0 | ✅ PASS |
| E2E-014 | 重新聚类保留AI答案 | ✅ PASS |
| E2E-015 | 5条面经完整重建（数据一致性验证） | ✅ PASS |

## TDD 原则遵守情况

- [x] 测试先行：每个功能都先写测试
- [x] 红灯验证：每个测试先确认失败
- [x] 最小实现：只写让测试通过的代码
- [x] 持续重构：每次绿灯后都考虑重构
- [x] 一次一个测试：每个循环只处理一个测试

## 结论

✅ 两阶段流水线按 TDD 方法完成开发
✅ 所有 21 个测试通过
✅ 修复了 5 个核心数据完整性问题
✅ 可安全集成到主干
