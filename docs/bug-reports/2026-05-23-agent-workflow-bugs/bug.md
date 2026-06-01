# Bug 详细分析报告

**Bug ID:** BUG-005 ~ BUG-010
**发现日期:** 2026-05-23
**状态:** 已确认

## 问题概述

跨 submit/build/batch_generate/shared 四个 agent 模块的系统性 bug 排查，共发现 6 个 bug。

---

## BUG-005: classify_node 未传递 user_id 给 get_taxonomy_for_position

- **位置:** `agents/submit/classify.py:94`
- **症状:** 用户设置了个人分类体系，但提交面经时使用的是系统默认分类
- **根因:** `await run_db(get_taxonomy_for_position)` 将函数引用传给 `run_db`，`run_db` 调用 `func()` 无参数。`get_taxonomy_for_position(user_id=xxx)` 需要 user_id 才能查到用户个人分类
- **影响:** 用户个人分类配置被忽略，始终使用系统默认分类
- **严重程度:** P1

**修复前代码:**
```python
taxonomy_config = await run_db(get_taxonomy_for_position)
```

**修复后代码:**
```python
taxonomy_config = await run_db(lambda: get_taxonomy_for_position(user_id=state.get("user_id")))
```

---

## BUG-006: classify_node taxonomy children 解析假设类型为字符串

- **位置:** `agents/submit/classify.py:115`
- **症状:** 当 taxonomy children 是字典列表时，`set(cat.get("children", []))` 会把字典对象加入集合，导致分类匹配全部失败
- **根因:** `children` 字段可以是 `["前端", "后端"]`（字符串列表）或 `[{"name": "前端"}, {"name": "后端"}]`（字典列表），代码只处理了字符串情况
- **影响:** valid_cat2_by_cat1 包含字典对象而非字符串，所有 cat2 匹配都会失败，评分被错误扣分
- **严重程度:** P1

**修复前代码:**
```python
valid_cat2_by_cat1[cname] = set(cat.get("children", []))
```

**修复后代码:**
```python
children = cat.get("children", [])
valid_cat2_by_cat1[cname] = set(
    c if isinstance(c, str) else c.get("name", "")
    for c in children
)
```

---

## BUG-007: evaluate_tagging_quality 不按题目数归一化评分

- **位置:** `agents/shared/quality.py:48-68`
- **症状:** 50 道题中有 7 道分类错误 → 扣 10.5 分 → 得 0 分；3 道题中有 1 道错误 → 扣 1.5 分 → 得 8.5 分。同样的错误率，评分差异巨大
- **根因:** 评分从固定 10.0 开始，每道错题扣固定分值，不按题目数归一化。题目越多，总扣分越高
- **影响:** 多题场景下质量评分被错误压低，触发不必要的重试（重试 2 次仍可能得 0 分），浪费 LLM 调用
- **严重程度:** P2

**修复方案:** 先计算错误率，再用错误率映射到 0-10 分

---

## BUG-008: clear_qb_node 使用裸 BEGIN/COMMIT 可能冲突

- **位置:** `agents/build/nodes.py:31-42`
- **症状:** Python sqlite3 模块自动管理事务，手动调用 `BEGIN` 可能导致 "cannot start a transaction within a transaction" 错误
- **根因:** `get_db_connection()` 返回的连接由 sqlite3 自动事务管理。手动 `BEGIN`/`COMMIT` 与自动事务冲突
- **影响:** 在某些情况下（如连接已有未提交事务时），清空题库操作可能失败
- **严重程度:** P2

**修复方案:** 使用 `with conn:` 上下文管理器替代手动事务控制

---

## BUG-009: 黑名单使用精确匹配，过滤不完全

- **位置:** `agents/submit/extract.py:76`
- **症状:** LLM 提取的 "请做自我介绍"、"我想问一下薪资" 等变体无法被黑名单过滤
- **根因:** `q.strip() == b` 使用精确匹配，但 LLM 输出的措辞可能与黑名单关键词不完全一致
- **影响:** 非面试题（自我介绍、反问等）混入题目列表，影响题库质量
- **严重程度:** P3

**修复方案:** 使用 `b in q` 子串匹配替代精确匹配

---

## BUG-010: build 节点在 async 函数中直接使用 get_db_connection

- **位置:** `agents/build/nodes.py:17` (backup_db_node), `agents/build/nodes.py:31` (clear_qb_node), `agents/build/nodes.py:53` (load_all_node)
- **症状:** async 节点函数直接调用 `get_db_connection()` 获取连接并执行 SQL，绕过了 `run_db` 的线程池隔离
- **根因:** `get_db_connection()` 返回线程级连接，在 async 事件循环线程中直接使用可能与其他并发操作冲突
- **影响:** 在高并发场景下可能出现数据库锁定或连接状态异常
- **严重程度:** P3

**修复方案:** 将数据库操作包装在 `run_db` lambda 中
