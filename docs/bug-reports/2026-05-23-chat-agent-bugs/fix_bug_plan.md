# 修复计划

**日期:** 2026-05-23

## BUG-001: `_llm_compress` 不传递 user_id

**文件:** `backend/app/agents/chat/budget.py:204`

修改前:
```python
llm_compressed = await self._llm_compress(old_messages, state_user_id=None)
```

修改后:
```python
llm_compressed = await self._llm_compress(old_messages, state_user_id=user_id)
```

## BUG-002: SYSTEM_BUDGET 常量不一致

**文件:** `backend/app/agents/chat/budget.py:61`

修改前:
```python
self.system_budget = 2000
```

修改后:
```python
self.system_budget = 3000  # 与 nodes.py SYSTEM_BUDGET 一致
```

## BUG-003: 错误内容作为正常 chunk 输出

**文件:** `backend/app/agents/chat/nodes.py:323-326`

修改前:
```python
except Exception as e:
    logger.error(f"生成回复失败: {e}")
    yield {"type": "chunk", "content": "抱歉，生成回复时出现错误，请稍后重试。"}
```

修改后:
```python
except Exception as e:
    logger.error(f"生成回复失败: {e}")
    yield {"type": "error", "message": "生成回复时出现错误，请稍后重试。"}
    return
```

## BUG-004: session_notes 截断切断标签

**文件:** `backend/app/agents/chat/nodes.py:395-396`

修改前:
```python
if len(updated_notes) > 2000:
    updated_notes = updated_notes[-2000:]
```

修改后:
```python
if len(updated_notes) > 2000:
    # 在行边界处截断，避免切断 [tag] 标签
    lines = updated_notes.split("\n")
    truncated = ""
    for line in reversed(lines):
        if len(truncated) + len(line) + 1 > 2000:
            break
        truncated = line + "\n" + truncated if truncated else line
    updated_notes = truncated
```
