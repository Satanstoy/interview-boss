# 优化 1 完成：强化增量聚类（Phase 1.5）

## ✅ 完成状态

**状态：已完成** ✅
**测试：14/14 通过** ✅
**实现：clustering.py 已更新** ✅

## 📝 修改内容

### 1. 新增常量

```python
RECENT_DAYS = 7  # 默认匹配最近 7 天的 frequency=1 题目
```

### 2. 新增函数

```python
async def _load_recent_singletons(cat2: str, days: int = RECENT_DAYS) -> List[Dict]:
    """加载最近 N 天入库的 frequency=1 题目（同 cat2）"""
    # SQL: SELECT id, question FROM question_bank 
    #      WHERE cat2 = ? AND frequency = 1 AND deleted_at IS NULL 
    #      AND created_at > datetime('now', ?)
    #      ORDER BY id DESC
```

### 3. 修改函数

#### `process_incremental_batch()`
- 新增参数：`recent_days: int = RECENT_DAYS`
- 向后兼容：不传参数时使用默认值 7

#### `_match_and_cluster_cat2()`
- 新增参数：`recent_days: int = RECENT_DAYS`
- 新增 Phase 1.5：匹配最近 N 天的 frequency=1 题目
- Phase 1 失败不影响 Phase 1.5 执行

## 🔄 执行流程

```
Phase 1: 匹配已有聚类（现有逻辑）
    ↓
Phase 1.5: 匹配最近 N 天的 frequency=1 题目（新增）
    ↓
Phase 2: 剩余新题内部聚类（现有逻辑）
```

## 📊 测试覆盖

### TestLoadRecentSingletons (5 个测试)
- ✅ 正确加载最近 N 天的题目
- ✅ 按 cat2 过滤
- ✅ 按天数过滤
- ✅ 空结果返回
- ✅ 默认天数参数

### TestMatchAndClusterCat2Logic (4 个测试)
- ✅ Phase 1.5 被调用并匹配成功
- ✅ 没有最近题目时不调用
- ✅ 正确使用 days 参数
- ✅ recent_days=0 时跳过

### TestProcessIncrementalBatch (3 个测试)
- ✅ 正确传递 recent_days 参数
- ✅ 默认 recent_days 为 7
- ✅ 按 cat2 正确分组

### TestIntegration (2 个测试)
- ✅ 完整流程测试
- ✅ 向后兼容性测试

## 💡 关键设计

### 1. 向后兼容
- 所有新参数都有默认值
- 不传参数时使用 RECENT_DAYS = 7
- 现有调用代码无需修改

### 2. 错误处理
- Phase 1 失败不影响 Phase 1.5
- Phase 1.5 失败不影响 Phase 2
- 所有异常都有日志记录

### 3. 性能优化
- 只查询指定 cat2 的题目
- 只查询最近 N 天的题目
- 使用 ORDER BY id DESC 优先匹配新题

## 🎯 预期效果

### 解决的问题
**问题**：两道语义相同的题在不同时间提交，第二批匹配不到第一批

**解决**：新题提交时，不仅匹配已有聚类，还匹配最近 7 天入库的 frequency=1 题目

### 示例场景
```
时间 T1: 提交题目 A（Redis 持久化方式有哪些？）
         → 创建新聚类（frequency=1）

时间 T2: 提交题目 B（Redis 的 RDB 和 AOF 持久化有什么区别？）
         → Phase 1: 无已有聚类匹配
         → Phase 1.5: 匹配到最近 7 天的题目 A
         → 结果：A 和 B 合并（frequency=2）
```

## 📈 成本分析

### 新增 LLM 调用
- 每次增量聚类最多增加 1 次 LLM 调用（Phase 1.5）
- 只在有最近题目时才调用
- Token 消耗：约 100-200 tokens/次

### 收益
- 提高聚类召回率
- 减少重复题目
- 改善用户体验

## 🔧 使用方式

### 现有代码（无需修改）
```python
result = await process_incremental_batch(
    new_rows,
    existing_by_cat2,
    user_id=user_id
)
```

### 自定义天数
```python
result = await process_incremental_batch(
    new_rows,
    existing_by_cat2,
    user_id=user_id,
    recent_days=14  # 匹配最近 14 天
)
```

### 禁用 Phase 1.5
```python
result = await process_incremental_batch(
    new_rows,
    existing_by_cat2,
    user_id=user_id,
    recent_days=0  # 跳过 Phase 1.5
)
```

## 📁 修改的文件

- `backend/app/services/clustering.py` - 核心逻辑修改
- `backend/tests/test_clustering_v2_final.py` - 测试文件

## ✅ 验证清单

- [x] 实现 `_load_recent_singletons()` 函数
- [x] 修改 `_match_and_cluster_cat2()` 添加 Phase 1.5
- [x] 修改 `process_incremental_batch()` 传递参数
- [x] 新增常量 RECENT_DAYS = 7
- [x] 所有测试通过（14/14）
- [x] 向后兼容性验证
- [x] 错误处理验证
- [x] 日志记录验证

## 🚀 下一步

优化 1 已完成，可以继续实施：
- **优化 2**：增大 batch size（降本）
- **优化 3**：跨 cat2 聚类（扩覆盖）
- **优化 4**：定时 compaction（兜底）

---

**完成时间**: 2026-05-30
**测试状态**: ✅ 14/14 通过
**实现状态**: ✅ 已完成
