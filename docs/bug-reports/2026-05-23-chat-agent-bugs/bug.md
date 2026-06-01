# Bug 详细分析报告

**日期:** 2026-05-23
**状态:** 已确认

## BUG-001: `_llm_compress` 不传递 user_id

- **位置:** `backend/app/agents/chat/budget.py:204`
- **症状:** LLM 结构化压缩时 `state_user_id=None`，无法使用用户特定配置
- **根因:** `compress()` 方法接收了 `user_id` 参数，但调用 `_llm_compress` 时硬编码为 `None`
- **影响:** 多用户环境下，压缩可能使用默认 API key 而非用户专属配置
- **严重程度:** P1 (High)

```python
# 当前代码 (budget.py:204)
llm_compressed = await self._llm_compress(old_messages, state_user_id=None)

# 应该是
llm_compressed = await self._llm_compress(old_messages, state_user_id=user_id)
```

## BUG-002: SYSTEM_BUDGET 常量不一致

- **位置:** `backend/app/agents/chat/nodes.py:26` vs `backend/app/agents/chat/budget.py:61`
- **症状:** 两个文件对系统 prompt 预算的定义不同
- **根因:** `nodes.py` 定义 `SYSTEM_BUDGET = 3000`（用于截断），`budget.py` 定义 `self.system_budget = 2000`（用于预算计算）
- **影响:** 预算管理器低估系统 prompt 大小 1000 字符，可能导致：
  - 上下文总大小超出 API 限制
  - 其他 section 的可用空间计算错误
- **严重程度:** P1 (High)

```python
# nodes.py:26
SYSTEM_BUDGET = 3000  # 用于 _truncate_to_budget

# budget.py:61
self.system_budget = 2000  # 用于预算计算

# 差异: 1000 字符（~250 tokens）
```

## BUG-003: 错误内容作为正常 chunk 输出

- **位置:** `backend/app/agents/chat/nodes.py:323-334`
- **症状:** LLM 调用失败时，错误消息以 `{"type": "chunk"}` 返回
- **根因:** except 块 yield chunk 而非 error，后续 yield done 事件
- **影响:**
  1. 前端无法区分错误和正常回复
  2. 错误消息被 `graph.py:187` 累加到 `state["response"]`
  3. 错误消息被 `chat_service.save_message()` 持久化到数据库
  4. `extract_memory` 可能从错误消息中提取无意义记忆
- **严重程度:** P2 (Medium)

```python
# 当前代码 (nodes.py:323-326)
except Exception as e:
    logger.error(f"生成回复失败: {e}")
    yield {"type": "chunk", "content": "抱歉，生成回复时出现错误，请稍后重试。"}
# 后续 yield {"type": "done", "metadata": metadata}
```

## BUG-004: session_notes 截断切断标签

- **位置:** `backend/app/agents/chat/nodes.py:395-396`
- **症状:** `updated_notes[-2000:]` 简单切片可能在 `[weakness]` 标签中间截断
- **根因:** 切片不感知行边界和标签格式
- **影响:** 被截断的行如 `ss] xxx` 无法被 `flush_session_to_memories` 的正则匹配，导致记忆丢失
- **严重程度:** P2 (Medium)

```python
# 当前代码 (nodes.py:395-396)
if len(updated_notes) > 2000:
    updated_notes = updated_notes[-2000:]

# 问题示例:
# 原始: "[weakness] Redis不熟悉\n[strength] Java精通\n..."
# 截断后: "ss] Redis不熟悉\n[strength] Java精通\n..."
# 第一行的 [weakness] 标签被切断
```
