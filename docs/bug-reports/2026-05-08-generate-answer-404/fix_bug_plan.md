# 修复计划

**Bug ID:** BUG-010
**日期:** 2026-05-08
**优先级:** P1

## 修复步骤

### 步骤 1: 修改 generate_master_answer 端点
**文件:** `backend/app/routers/master_bank.py`
**行号:** 779-816
**修改类型:** 修正

**修改前:**
```python
@router.post("/api/master-bank/generate-answer/{question_id}")
async def generate_master_answer(question_id: int, user: dict = Depends(get_current_user)):
    from_clause, where_clause, base_params = _build_bank_where_clause(user, "qb")

    def _get():
        with get_db_connection() as conn:
            return conn.execute(
                f"SELECT qb.question, qb.ai_answer {from_clause} WHERE qb.id = ? AND {where_clause[6:]}",
                [question_id] + base_params
            ).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该题目或无权访问")
```

**修改后:**
```python
@router.post("/api/master-bank/generate-answer/{question_id}")
async def generate_master_answer(question_id: int, user: dict = Depends(get_current_user)):
    mode = user.get('bank_mode', 'public')
    uid = user['id']

    def _get():
        with get_db_connection() as conn:
            # 先检查题目是否存在且未删除
            row = conn.execute(
                "SELECT qb.id, qb.question, qb.ai_answer, qb.owner_id, qb.status FROM question_bank qb WHERE qb.id = ? AND qb.deleted_at IS NULL",
                (question_id,)
            ).fetchone()
            if not row:
                return None
            # 根据 bank_mode 检查权限
            if mode == 'personal' and row['owner_id'] != uid:
                return None
            elif mode == 'public' and (row['owner_id'] is not None or row['status'] != 'approved'):
                return None
            elif mode == 'mixed' and not ((row['owner_id'] is None and row['status'] == 'approved') or row['owner_id'] == uid):
                return None
            return row

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该题目或无权访问")
```

### 步骤 2: 修改 batch_generate_answers 端点
**文件:** `backend/app/routers/master_bank.py`
**行号:** 1038-1080
**修改类型:** 修正

使用与步骤1相同的逻辑，不使用 `_build_bank_where_clause` 进行点查询。

### 步骤 3: 修改 evaluate_answer 端点
**文件:** `backend/app/routers/master_bank.py`
**行号:** 1340-1380
**修改类型:** 修正

使用与步骤1相同的逻辑，不使用 `_build_bank_where_clause` 进行点查询。

## 验证方法
1. 以管理员身份登录
2. 进入高频题库
3. 点击"AI生成答案"按钮
4. 验证答案成功生成
5. 运行 pytest 测试

## 回滚方案
如果修复失败，恢复原始代码并重启服务。
