# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-010
**发现日期:** 2026-06-02
**状态:** 已确认

---

## BUG-001: Phase 1.5 匹配验证永远失败（ID 空间不匹配）

- **位置:** `backend/app/services/clustering.py:428-429`
- **症状:** Phase 1.5 的 LLM 匹配结果全部被丢弃，所有题目回退到 Phase 2 内部聚类
- **根因:** `_validate_merges()` 的第三个参数传了 `existing_clusters`（Phase 1 的高频聚类），但 Phase 1.5 匹配的是 `recent_singletons`（近期孤岛题）。验证函数在 `existing_clusters` 中找不到 `recent_singletons` 的 ID，`cluster_q` 为 None，所有对被跳过
- **影响:** Phase 1.5 的 LLM API 调用全部浪费；近期入库的孤岛题无法与新题合并，导致重复聚类
- **严重程度:** P1（HIGH）

## BUG-002: LLM 重复匹配无去重保护（一题多合并）

- **位置:** `backend/app/services/clustering.py:401-419`
- **症状:** 当 LLM 返回同一个 `new_id` 映射到多个 `cluster_id` 时，该题被合并到多个聚类
- **根因:** 遍历 `result.get("matches", [])` 时只检查了 `nid in unmatched_ids`，没检查 `nid` 是否已在本轮被处理过
- **影响:** 数据损坏：一道题的 frequency 和 sources 被重复计入多个聚类
- **严重程度:** P1（HIGH）

## BUG-003: v2 compaction 无验证保护

- **位置:** `backend/app/services/pipeline/batch_v2.py:29-372`
- **症状:** LLM 的匹配结果直接执行合并，无二次验证
- **根因:** v1 的 `compact_singletons_in_db` 有 `_validate_merges` 步骤，v2 版本跳过了这一步
- **影响:** LLM 幻觉直接导致错误合并写入数据库，无安全网
- **严重程度:** P1（HIGH）

## BUG-004: v2 compaction 无合并历史记录

- **位置:** `backend/app/services/pipeline/batch_v2.py:142-231, 288-361`
- **症状:** 通过 v2 compaction 执行的合并不写 `merge_history` 表
- **根因:** `_do_match_merge` 和 `_do_merge` 函数未调用 `_record_merge_history`
- **影响:** 无法审计、无法回滚错误合并
- **严重程度:** P2（MEDIUM）

## BUG-005: `_build_new_entry` 未去重 `original_questions`

- **位置:** `backend/app/services/pipeline/writer.py:186-209`
- **症状:** 新建聚类的 frequency 可能虚高（包含重复题目文本）
- **根因:** 追加 `original_questions` 时未检查是否已存在，而 `apply_matched` 中有此检查
- **影响:** frequency 不准确，影响排序和展示
- **严重程度:** P2（MEDIUM）

## BUG-006: `full_recluster_hybrid` O(N*M) 性能问题

- **位置:** `backend/app/services/clustering.py:1188-1193`
- **症状:** 全量重聚类的合并阶段逐个线性扫描 questions 列表
- **根因:** `next((q['question'] for q in questions if q['id'] == m), '')` 在循环内
- **影响:** 大数据量时合并阶段显著变慢
- **严重程度:** P3（LOW）

## BUG-007: frequency 计算方式不一致

- **位置:** `batch.py:385` vs `batch_v2.py:217` vs `writer.py:100`
- **症状:** 三条合并路径计算 frequency 的方式不同（len vs +1）
- **根因:** 历史演进中各文件独立实现，未统一
- **影响:** 混合使用不同路径时 frequency 可能漂移
- **严重程度:** P2（MEDIUM）

## BUG-008: `full_recluster_hybrid` 合并循环逐条执行

- **位置:** `backend/app/services/clustering.py:1174-1202`
- **症状:** 每个合并对单独开事务执行，200 个合并 = 200 次线程切换
- **根因:** `await _scan_async(_do_merge)` 在 for 循环内
- **影响:** 全量重聚类性能差
- **严重程度:** P3（LOW）

## BUG-009: 异常静默吞没

- **位置:** `backend/app/services/pipeline/batch.py:393-404`
- **症状:** normalized table 写入失败时 `try/except: pass`，无日志
- **根因:** 防御性编程但过于宽松
- **影响:** JSON 列与 normalized table 数据不一致
- **严重程度:** P3（LOW）

## BUG-010: 空 `existing_clusters` 绕过验证

- **位置:** `backend/app/services/clustering.py:150-152`
- **症状:** 当 `pairs_text` 为空时验证被跳过，所有原始匹配直接通过
- **根因:** 检查的是 `pairs_text` 而非 `existing_clusters` 是否为空
- **影响:** 边缘情况下 LLM 的无效匹配绕过验证
- **严重程度:** P3（LOW）

---

## 复现步骤

### BUG-001 复现
1. 提交一批新面经，触发增量聚类
2. 观察 Phase 1.5 日志：LLM 返回匹配结果
3. 验证日志：匹配结果被 `_validate_merges` 全部拒绝
4. 所有题目回退到 Phase 2

### BUG-002 复现
1. Mock LLM 返回 `{"matches": [{"new_id": "100", "cluster_id": "1"}, {"new_id": "100", "cluster_id": "2"}]}`
2. 执行 `_match_and_cluster_cat2`
3. 题目 100 被同时合并到聚类 1 和 2

### BUG-003 复现
1. Mock LLM 返回错误的匹配结果（不同知识点的题被匹配）
2. 执行 `compact_singletons_in_db_v2`
3. 错误合并直接写入数据库，无验证拦截
