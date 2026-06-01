# 绿灯阶段报告

**测试编号:** T-001 ~ T-003
**实现时间:** 2026-05-10

## 修复内容

### 修改文件：`backend/app/services/pipeline.py` — `cluster_batch` 函数

**核心变更：** 将 `_cleanup_old_sources_txn_v2` 从 `_atomic_write`（聚类之后）移到加载 `existing_rows` 之前。

### 变更前（问题代码）
```
步骤1: 加载 questions_detail
步骤2: 加载 existing question_bank  ← 旧条目在这里
步骤3: 合并聚类                     ← 旧条目干扰决策
步骤4: _atomic_write:
       ├─ _cleanup_old_sources_txn_v2  ← 清理太晚
       └─ INSERT 新聚类
```

### 变更后（修复代码）
```
步骤1: 加载 questions_detail
步骤2: 保存旧 AI 答案 + _cleanup_old_sources_txn_v2  ← 先清理
步骤3: 加载 existing question_bank                     ← 已不含旧条目
步骤4: 合并聚类                                        ← 干净的上下文
步骤5: _atomic_write: INSERT 新聚类
```

### 附加修复

1. `existing_rows` 查询补充了 `ai_answer` 字段（原代码遗漏）
2. AI 答案恢复增加 fallback：从 pre-clean 前保存的 `saved_answers` 中查找

## 测试运行结果

```bash
$ /root/.local/bin/uv run pytest backend/tests/test_reprocess_cleanup_order.py -v

backend/tests/test_reprocess_cleanup_order.py::TestCleanupBeforeClustering::test_old_qb_excluded_from_clustering_context PASSED
backend/tests/test_reprocess_cleanup_order.py::TestCleanupBeforeClustering::test_shared_qb_kept_but_url_removed PASSED
backend/tests/test_reprocess_cleanup_order.py::TestCleanupBeforeClustering::test_ai_answer_preserved_after_recluster PASSED

3 passed in 1.90s
```

## 回归测试

```bash
$ /root/.local/bin/uv run pytest backend/tests/test_two_phase_pipeline.py backend/tests/test_pipeline_e2e.py -v

36 passed (21 单元 + 15 E2E), 无回归
```

## 阶段状态
- [x] 最小实现已编写
- [x] 新测试通过（绿色）
- [x] 已有测试无回归
- [ ] 进入重构阶段
