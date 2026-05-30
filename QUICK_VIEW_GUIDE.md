# 聚类系统优化 - 快速查看指南

## 📁 项目文件总览

### 核心实现文件

```bash
# 优化 1：强化增量聚类
/home/ubuntu/sj/interview-boss/backend/app/services/clustering.py

# 优化 2、3：增大 batch size + 跨 cat2 聚类
/home/ubuntu/sj/interview-boss/backend/app/services/pipeline/batch.py

# 优化 4：定时 compaction
/home/ubuntu/sj/interview-boss/backend/app/worker.py
```

### 测试文件

```bash
# 优化 1 测试（14 个）
/home/ubuntu/sj/interview-boss/backend/tests/test_clustering_v2_final.py

# 优化 2 测试（9 个）
/home/ubuntu/sj/interview-boss/backend/tests/test_batch_optimization.py

# 优化 3 测试（9 个）
/home/ubuntu/sj/interview-boss/backend/tests/test_cross_cat2.py

# 优化 4 测试（6 个）
/home/ubuntu/sj/interview-boss/backend/tests/test_scheduler.py
```

### 文档文件

```bash
# 完整总结
/home/ubuntu/sj/interview-boss/ALL_OPTIMIZATIONS_COMPLETE.md

# 优化 1 详细说明
/home/ubuntu/sj/interview-boss/OPTIMIZATION_1_COMPLETE.md

# 优化 4 详细说明
/home/ubuntu/sj/interview-boss/OPTIMIZATION_4_COMPLETE.md

# 快速查看指南（本文件）
/home/ubuntu/sj/interview-boss/QUICK_VIEW_GUIDE.md
```

## 🧪 运行测试

### 运行所有测试

```bash
cd /home/ubuntu/sj/interview-boss

# 优化 1 测试
uv run pytest backend/tests/test_clustering_v2_final.py -v

# 优化 2 测试
uv run pytest backend/tests/test_batch_optimization.py -v

# 优化 3 测试
uv run pytest backend/tests/test_cross_cat2.py -v

# 优化 4 测试
uv run pytest backend/tests/test_scheduler.py -v
```

### 一键运行所有测试

```bash
cd /home/ubuntu/sj/interview-boss

uv run pytest backend/tests/test_clustering_v2_final.py \
              backend/tests/test_batch_optimization.py \
              backend/tests/test_cross_cat2.py \
              backend/tests/test_scheduler.py \
              -v
```

## 📊 查看测试结果

### 优化 1 测试结果

```bash
uv run pytest backend/tests/test_clustering_v2_final.py -v -s
```

**预期输出：**
```
14 passed in 0.09s
```

### 优化 2 测试结果

```bash
uv run pytest backend/tests/test_batch_optimization.py -v -s
```

**预期输出：**
```
原始分组数: 20
合并后 batch 数: 2
每个 batch 的题目数: [79, 24]
每个 batch 的 cat2 数: [10, 10]
9 passed in 0.04s
```

### 优化 3 测试结果

```bash
uv run pytest backend/tests/test_cross_cat2.py -v -s
```

**预期输出：**
```
总共找到 1 个跨 cat2 候选对
Redis 相关候选对: 1
9 passed in 0.04s
```

### 优化 4 测试结果

```bash
uv run pytest backend/tests/test_scheduler.py -v
```

**预期输出：**
```
6 passed in 0.04s
```

## 📖 查看文档

### 查看完整总结

```bash
cat /home/ubuntu/sj/interview-boss/ALL_OPTIMIZATIONS_COMPLETE.md
```

### 查看优化 1 详细说明

```bash
cat /home/ubuntu/sj/interview-boss/OPTIMIZATION_1_COMPLETE.md
```

### 查看优化 4 详细说明

```bash
cat /home/ubuntu/sj/interview-boss/OPTIMIZATION_4_COMPLETE.md
```

## 🔍 查看代码实现

### 优化 1：强化增量聚类

```bash
# 查看新增函数
grep -n "_load_recent_singletons" /home/ubuntu/sj/interview-boss/backend/app/services/clustering.py

# 查看 Phase 1.5 实现
grep -n "Phase 1.5" /home/ubuntu/sj/interview-boss/backend/app/services/clustering.py
```

### 优化 2：增大 batch size

```bash
# 查看 _merge_small_groups 函数
grep -n "_merge_small_groups" /home/ubuntu/sj/interview-boss/backend/app/services/pipeline/batch.py
```

### 优化 3：跨 cat2 聚类

```bash
# 查看 _extract_technical_keywords 函数
grep -n "_extract_technical_keywords" /home/ubuntu/sj/interview-boss/backend/app/services/pipeline/batch.py

# 查看 _cross_cat2_check 函数
grep -n "_cross_cat2_check" /home/ubuntu/sj/interview-boss/backend/app/services/pipeline/batch.py
```

### 优化 4：定时 compaction

```bash
# 查看定时任务函数
grep -n "scheduled_compaction_task" /home/ubuntu/sj/interview-boss/backend/app/worker.py

# 查看 cron_jobs 配置
grep -n "cron_jobs" /home/ubuntu/sj/interview-boss/backend/app/worker.py
```

## 📈 查看测试覆盖

### 优化 1 测试覆盖

```bash
uv run pytest backend/tests/test_clustering_v2_final.py --cov=app.services.clustering --cov-report=term-missing
```

### 优化 2 测试覆盖

```bash
uv run pytest backend/tests/test_batch_optimization.py --cov=app.services.pipeline.batch --cov-report=term-missing
```

## 🗄️ 查看数据库

### 查看 task_logs 表

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/ubuntu/sj/interview-boss/backend/data/interview-boss.db')
cursor = conn.cursor()

# 查看表结构
cursor.execute('PRAGMA table_info(task_logs)')
columns = cursor.fetchall()
print('task_logs 表结构:')
for col in columns:
    print(f'  {col[1]} ({col[2]})')

# 查看数据
cursor.execute('SELECT * FROM task_logs ORDER BY created_at DESC LIMIT 5')
rows = cursor.fetchall()
print(f'\n最近 5 条记录:')
for row in rows:
    print(f'  {row}')

conn.close()
"
```

## 🚀 部署检查

### 检查数据库表

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/ubuntu/sj/interview-boss/backend/data/interview-boss.db')
cursor = conn.cursor()

# 检查 task_logs 表是否存在
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='task_logs'\")
result = cursor.fetchone()
print(f'task_logs 表存在: {result is not None}')

conn.close()
"
```

### 检查 WorkerSettings

```bash
python3 -c "
import sys
sys.path.insert(0, '/home/ubuntu/sj/interview-boss/backend')
from app.worker import WorkerSettings

settings = WorkerSettings()
print(f'Functions: {settings.functions}')
print(f'Cron jobs: {settings.cron_jobs}')
"
```

## 📝 快速参考

### 优化 1 关键点

- **函数**: `_load_recent_singletons()`
- **参数**: `recent_days` (默认 7 天)
- **流程**: Phase 1 → Phase 1.5 → Phase 2

### 优化 2 关键点

- **函数**: `_merge_small_groups()`
- **参数**: `max_size` (默认 80)
- **策略**: 贪心合并，按组大小降序

### 优化 3 关键点

- **函数**: `_extract_technical_keywords()`, `_cross_cat2_check()`
- **分词**: 2-gram 和 3-gram
- **阈值**: 共享 ≥ 2 个关键词

### 优化 4 关键点

- **函数**: `scheduled_compaction_task()`
- **时间**: 每天凌晨 3:00
- **日志**: task_logs 表

## 🎯 预期效果

### 成本节省

- **LLM 调用**: 从 23 次减少到 2 次
- **Token 消耗**: 显著降低
- **人工成本**: 无需手动触发

### 质量提升

- **召回率**: 提高（优化 1、3）
- **准确率**: 保持（保守策略）
- **覆盖范围**: 扩大（优化 3）

### 运维改善

- **自动化**: 提高（优化 4）
- **监控**: 增强（日志记录）
- **稳定性**: 提高（错误处理）

---

**快速查看**: `cat /home/ubuntu/sj/interview-boss/ALL_OPTIMIZATIONS_COMPLETE.md`
**运行测试**: `uv run pytest backend/tests/ -v`
**部署状态**: ✅ 已准备好部署
