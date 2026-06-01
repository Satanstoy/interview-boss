# 修复计划

**日期:** 2026-06-02
**优先级:** BUG-001~003 为 P1，BUG-004~005 为 P2，其余为 P3

---

## BUG-001: Phase 1.5 验证 ID 空间不匹配

**文件:** `backend/app/services/clustering.py`
**行号:** 428-429
**修改类型:** 修正

**修改前:**
```python
validated_matches, _confidence_map = await _validate_merges(
    phase1_matches, new_questions, existing_clusters, user_id
)
```

**修改后:**
```python
# 合并 recent_singletons 到验证用的 cluster 列表
all_clusters_for_validate = existing_clusters + [
    {"id": r["id"], "question": r["question"]} for r in recent_singletons
]
validated_matches, _confidence_map = await _validate_merges(
    phase1_matches, new_questions, all_clusters_for_validate, user_id
)
```

---

## BUG-002: LLM 重复匹配无去重

**文件:** `backend/app/services/clustering.py`
**行号:** 398-419
**修改类型:** 新增

**修改前:**
```python
for m in result.get("matches", []):
    nid = str(m.get("new_id", ""))
    cid = m.get("cluster_id")
    if nid in unmatched_ids and cid is not None:
        matched_cluster_ids.add(nid)
```

**修改后:**
```python
processed_new_ids = set()
for m in result.get("matches", []):
    nid = str(m.get("new_id", ""))
    cid = m.get("cluster_id")
    if nid in unmatched_ids and nid not in processed_new_ids and cid is not None:
        processed_new_ids.add(nid)
        matched_cluster_ids.add(nid)
```

---

## BUG-003: v2 compaction 无验证

**文件:** `backend/app/services/pipeline/batch_v2.py`
**修改类型:** 新增

在 Step 3 和 Step 4 的合并执行前添加 `_validate_merges` 调用。

---

## BUG-004: v2 compaction 无合并历史

**文件:** `backend/app/services/pipeline/batch_v2.py`
**修改类型:** 新增

导入 `_record_merge_history` 和 `_snapshot_question`，在合并执行时记录历史。

---

## BUG-005: `_build_new_entry` 未去重

**文件:** `backend/app/services/pipeline/writer.py`
**行号:** 193-195
**修改类型:** 修正

**修改前:**
```python
if q:
    original_questions.append(q)
```

**修改后:**
```python
if q and q not in original_questions:
    original_questions.append(q)
```

---

## BUG-006: O(N*M) 线性扫描

**文件:** `backend/app/services/clustering.py`
**行号:** 1174 前
**修改类型:** 新增

在循环前构建 `question_lookup = {q['id']: q['question'] for q in questions}`，循环内用 `question_lookup.get(m, '')`。

---

## BUG-007: frequency 计算不一致

**文件:** `backend/app/services/pipeline/batch_v2.py:217`
**修改类型:** 修正

**修改前:** `frequency = target['frequency'] + 1`
**修改后:** `frequency = len(target_oqs)` （合并后的 original_questions 长度）

---

## 验证方法
1. 运行 `pytest backend/tests/test_clustering_compaction_bugs.py -v`
2. 所有 xfail 测试在修复后应变为 PASS
3. 无回归：现有聚类测试全部通过

## 回滚方案
每个 bug 独立修复，可通过 `git revert` 单独回滚。
