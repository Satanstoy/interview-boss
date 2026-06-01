# 修复计划

**Bug ID:** BUG-006
**日期:** 2026-05-22
**优先级:** P1

## 修复步骤

### 步骤 1: 修改 data.py 的 get_data 端点

**文件:** `backend/app/routers/data.py`
**行号:** 7, 183-184
**修改类型:** 修正

**修改前:**
```python
from app.db.connection import get_db_connection, run_db, get_current_job_position
# ...
from app.db.connection import get_current_job_position
current_pos = get_current_job_position()
```

**修改后:**
```python
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_user_job_position
# ...
from app.db.connection import get_user_job_position
_, current_pos = get_user_job_position(user['id'])
```

### 步骤 2: 修复面经表脏数据

**文件:** `backend/data/interview-boss.db`
**修改类型:** 数据修正

```sql
UPDATE interview SET job_position = 'agent开发/大模型应用开发/大模型开发' WHERE job_position = 'backend';
```

## 验证方法

1. 切换岗位后面经库数据应随之变化
2. 测试代码验证 `get_data` 使用 `get_user_job_position`

## 回滚方案

`git checkout backend/app/routers/data.py`，数据库脏数据不需回滚。
