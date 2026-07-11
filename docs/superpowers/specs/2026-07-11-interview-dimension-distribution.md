# 面经维度分布记录系统设计文档

**日期**: 2026-07-11
**状态**: 待审核
**作者**: MiMoCode

## 1. 概述

### 1.1 问题陈述

当前系统在面经上传时只记录题目的分类信息（cat1/cat2），但没有记录面试的维度分布（项目深挖 vs 八股题）。这导致：
- 无法统计真实面试的维度分布
- 无法根据分布优化面试阈值
- 无法支持用户调整维度比值

### 1.2 目标

1. **记录真实面试的维度分布** - 在上传面经时自动提取
2. **支持维度分布统计** - 为后续优化提供数据基础
3. **支持用户调整阈值** - 前端可配置维度比值

### 1.3 范围

- 数据库schema修改
- 后端逻辑修改
- 迁移脚本
- 前端展示（后续）

## 2. 设计方案

### 2.1 维度分类定义

| 维度 | 包含的cat1 | 说明 |
|------|-----------|------|
| **项目深挖** (project_deep_dive) | A.项目经验与设计 | 测试候选人对项目的端到端思考 |
| **八股题** (knowledge_probe) | B, C, D, E, 其他 | 测试候选人的基础知识 |

### 2.2 维度映射规则

```python
def map_dimension(cat1: str, cat2: str) -> str:
    """将分类映射到维度"""
    if cat1.startswith("A."):
        return "project_deep_dive"
    else:
        return "knowledge_probe"
```

### 2.3 数据库设计

#### 2.3.1 questions_detail表修改

**新增字段**: `dimension` (TEXT, 默认空字符串)

```sql
ALTER TABLE questions_detail ADD COLUMN dimension TEXT DEFAULT '';
```

**用途**: 记录每道题的维度分类

#### 2.3.2 interview表修改

**新增字段**: `dimension_distribution` (TEXT, 默认'{}')

```sql
ALTER TABLE interview ADD COLUMN dimension_distribution TEXT DEFAULT '{}';
```

**用途**: 记录整场面经的维度分布

**数据格式**: JSON
```json
{
  "project_deep_dive": 3,
  "knowledge_probe": 7
}
```

### 2.4 代码修改

#### 2.4.1 submit_service.py

**新增函数**:
```python
def map_dimension(cat1: str, cat2: str) -> str:
    """将分类映射到维度"""
    if cat1.startswith("A."):
        return "project_deep_dive"
    else:
        return "knowledge_probe"

def calculate_distribution(tagged_rows: list) -> dict:
    """计算维度分布"""
    distribution = {"project_deep_dive": 0, "knowledge_probe": 0}
    for row in tagged_rows:
        cat1 = row[4] if len(row) > 4 else ""
        cat2 = row[5] if len(row) > 5 else ""
        dimension = map_dimension(cat1, cat2)
        distribution[dimension] += 1
    return distribution
```

#### 2.4.2 operations.py

**修改函数**:

1. `_insert_details_txn` - 添加dimension字段
```python
def _insert_details_txn(cursor, tagged_rows, job_position=""):
    for tr in tagged_rows:
        dimension = map_dimension(tr[4], tr[5])  # cat1, cat2
        cursor.execute(
            "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position, dimension) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*tr, job_position, dimension)
        )
```

2. `_insert_interview_txn` - 添加dimension_distribution字段
```python
def _insert_interview_txn(cursor, saved_url, data, questions, season, owner_id, status, job_position, dimension_distribution):
    sig = _extract_url_signature(saved_url)
    cursor.execute(
        "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, season, owner_id, status, url_signature, job_position, dimension_distribution) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (saved_url, data.get("公司", "未提供"), data.get("面试轮次", "未提供"), data.get("考察重点", "未提供"),
         questions, data.get("难易程度", "未提供"), season, owner_id, status, sig, job_position, json.dumps(dimension_distribution, ensure_ascii=False))
    )
```

#### 2.4.3 classify_node.py

**修改函数**: classify_node
```python
async def classify_node(state: SubmitState) -> dict:
    # ... 现有代码 ...
    
    # 统计维度分布
    dimension_distribution = calculate_distribution(tagged_rows)
    
    return {
        "tagged_rows": tagged_rows,
        "tagging_quality": quality,
        "tagging_retries": retry_count,
        "taxonomy_config": taxonomy_config,
        "dimension_distribution": dimension_distribution,  # 新增
        "node_timings": {**state.get("node_timings", {}), "classify": timer.elapsed},
        "llm_call_count": state.get("llm_call_count", 0) + 1,
    }
```

#### 2.4.4 persist_personal.py / persist_public.py

**修改**: 调用_insert_interview_txn时传递dimension_distribution

### 2.5 迁移脚本

**文件**: `backend/app/db/migrations/migration_040_add_dimension_fields.py`

```python
def migrate(conn):
    # questions_detail表新增dimension字段
    conn.execute("ALTER TABLE questions_detail ADD COLUMN dimension TEXT DEFAULT ''")
    
    # interview表新增dimension_distribution字段
    conn.execute("ALTER TABLE interview ADD COLUMN dimension_distribution TEXT DEFAULT '{}'")
    
    # 回填现有数据
    rows = conn.execute("SELECT id, cat1, cat2 FROM questions_detail WHERE deleted_at IS NULL").fetchall()
    for row in rows:
        dimension = map_dimension(row[1], row[2])
        conn.execute("UPDATE questions_detail SET dimension = ? WHERE id = ?", (dimension, row[0]))
    
    # 统计每场面经的维度分布
    interviews = conn.execute("SELECT id, url FROM interview WHERE deleted_at IS NULL").fetchall()
    for interview in interviews:
        details = conn.execute("SELECT cat1, cat2 FROM questions_detail WHERE url = ? AND deleted_at IS NULL", (interview[1],)).fetchall()
        distribution = calculate_distribution([(None, None, None, None, d[0], d[1]) for d in details])
        conn.execute("UPDATE interview SET dimension_distribution = ? WHERE id = ?", (json.dumps(distribution, ensure_ascii=False), interview[0]))
```

## 3. 数据流

### 3.1 上传面经流程

```
用户上传面经
    ↓
LLM提取题目清单
    ↓
分类标注（cat1/cat2/tags/difficulty）
    ↓
维度映射（dimension）
    ↓
统计维度分布（dimension_distribution）
    ↓
入库（interview + questions_detail）
```

### 3.2 查询流程

```
查询面经列表
    ↓
读取interview.dimension_distribution
    ↓
展示维度分布统计
```

## 4. 接口设计

### 4.1 面经详情接口

**GET** `/api/interview/{id}`

**响应**:
```json
{
  "id": 1,
  "company": "携程",
  "round": "一面",
  "questions_list": "...",
  "dimension_distribution": {
    "project_deep_dive": 3,
    "knowledge_probe": 7
  }
}
```

### 4.2 面经列表接口

**GET** `/api/interview/experiences`

**响应**:
```json
{
  "experiences": [
    {
      "id": 1,
      "company": "携程",
      "round": "一面",
      "dimension_distribution": {
        "project_deep_dive": 3,
        "knowledge_probe": 7
      }
    }
  ]
}
```

## 5. 测试计划

### 5.1 单元测试

1. 测试map_dimension函数
2. 测试calculate_distribution函数
3. 测试_insert_details_txn函数
4. 测试_insert_interview_txn函数

### 5.2 集成测试

1. 测试面经上传流程
2. 测试维度分布统计
3. 测试数据迁移

### 5.3 E2E测试

1. 上传面经 → 检查dimension字段
2. 查询面经 → 检查dimension_distribution字段

## 6. 部署计划

### 6.1 数据库迁移

1. 运行migration_040_add_dimension_fields.py
2. 验证数据迁移正确性

### 6.2 代码部署

1. 部署后端代码
2. 验证功能正常

### 6.3 回滚计划

1. 回滚代码
2. 回滚数据库迁移

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 迁移脚本失败 | 数据丢失 | 备份数据库，分步执行 |
| 性能影响 | 响应变慢 | 索引优化，批量处理 |
| 数据不一致 | 统计错误 | 事务保证，数据校验 |

## 8. 后续扩展

### 8.1 前端展示

- 面经详情页展示维度分布
- 面经列表页展示维度分布统计

### 8.2 阈值优化

- 根据维度分布调整面试阈值
- 支持用户自定义维度比值

### 8.3 分析报表

- 维度分布趋势分析
- 岗位维度分布对比

## 9. 附录

### 9.1 相关代码文件

- `backend/app/services/submit_service.py`
- `backend/app/db/operations.py`
- `backend/app/agents/submit/classify.py`
- `backend/app/agents/submit/persist_personal.py`
- `backend/app/agents/submit/persist_public.py`

### 9.2 相关数据库表

- `interview`
- `questions_detail`

### 9.3 参考资料

- [Google re:Work - Structured Interviewing](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices)
- [RATE Framework](https://ratiomodel.com/methodology/rate)
- [Engineering Interview Rubric Playbook](https://jobsbyculture.com/blog/engineering-interview-rubric-2026)
