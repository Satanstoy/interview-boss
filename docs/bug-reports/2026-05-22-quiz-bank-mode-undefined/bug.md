# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-22
**状态:** 已确认

## 问题概述
前端抽测功能点击"抽测"后，后端 API `GET /api/master-bank/random` 因 `NameError` 返回 500，前端显示空状态。

## 根本原因分析

### BUG-001: bank_mode 变量未定义导致抽测 API 500 错误
- **位置:** `backend/app/routers/practice.py:90`
- **症状:** 点击抽测按钮后页面显示"暂无符合条件的题目"
- **根因:** `get_random_questions()` 函数中缺少 `bank_mode = user.get('bank_mode', 'public')`，导致第90行 `get_dynamic_frequency_sql(bank_mode, user['id'])` 抛出 `NameError: name 'bank_mode' is not defined`
- **影响:** 抽测功能完全不可用，所有用户受影响
- **严重程度:** P0

### 对比正确实现
`backend/app/routers/questions.py:70` 中有正确的写法：
```python
bank_mode = user.get('bank_mode', 'public')
dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user['id'])
```

而 `practice.py` 中直接使用 `bank_mode` 却未定义：
```python
# 缺少: bank_mode = user.get('bank_mode', 'public')
dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user['id'])  # NameError!
```

## 复现步骤
1. 登录前端，进入抽测页面（MockInterview）
2. 选择领域和难度（或不选，使用默认）
3. 点击"抽测"按钮
4. **预期:** 显示随机题目列表
5. **实际:** 显示"暂无符合条件的题目"

## 修复建议
在 `practice.py` 的 `get_random_questions()` 函数中，`_query()` 闭包定义前添加：
```python
bank_mode = user.get('bank_mode', 'public')
```
