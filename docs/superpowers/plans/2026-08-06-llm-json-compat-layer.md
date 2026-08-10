# LLM JSON 兼容层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `app/services/llm.py` 增加"供应商能力兼容层"：provider 能力矩阵（json_mode / max_output_tokens）+ 自动降级（json_object 不可用时 prompt 指令 + 容错解析兜底）+ 显式 max_tokens，让有问题的模型供应商（如 mimo Token Plan json_object 当前截断）不破坏任何调用方。

**Architecture:** 调用方保持声明式传参（`response_format={"type": "json_object"}`），llm.py 适配层按 base_url 前缀匹配能力矩阵决定是否下发 json_object；json_mode=false 时自动在 system 指令附加"只输出 JSON"并靠调用方已有容错解析器兜底。供应商修复后改矩阵一行即恢复。生产 8 处调用点零改动。

**Tech Stack:** Python 3.10 / FastAPI / tenacity / openai + anthropic SDK。改动仅限 `backend/app/services/llm.py` + 测试。

**背景事实（2026-08-06 实测）：**
- mimo-v2.5（Token Plan, `token-plan-cn.xiaomimimo.com`）`response_format=json_object` 模式输出被服务端截断（即使显式 `max_tokens=2000` 也只返回 `'```json\n['`），不带 json_object 则输出完整
- mimo 官方文档警告：`max_completion_tokens` 过小会截断 JSON；mimo-v2.5 真实输出上限 128K（openclaw PR#95934）
- 本项目 `_call_llm_with_retry`（llm.py:787-827）不传 max_tokens → 依赖服务端默认，有截断风险
- 生产 8 处调用点传 `response_format={"type": "json_object"}`：`matcher.py:253/537/703`、`clusterer.py:160/389`、`compact.py:397`、`memory_recall_service.py:55/861`、`answer_enrichment.py:236`；`submit_service.py:76` 动态传

**不做的（YAGNI）：** 不新增 jsonschema 校验依赖；不改 8 处生产调用点；不改 Anthropic 分支行为（其已有 prompt 指令降级 + 默认 max_tokens=8192）。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `backend/app/services/llm.py` | 能力矩阵 `_PROVIDER_CAPABILITIES`、`get_provider_capabilities()`、`_should_use_response_format()` 升级、`_call_llm_with_retry`/`raw_llm_call`/`_call_llm_with_retry_messages` 加 max_tokens + 降级 |
| `backend/tests/services/test_llm_compat.py` | 新测试：矩阵匹配 / 降级路径 / max_tokens 默认 / override 开关 |

---

### Task 1: Provider 能力矩阵 + get_provider_capabilities()

**Files:**
- Modify: `backend/app/services/llm.py`（在 `_detect_provider` 之后、`_should_use_response_format` 之前插入）
- Test: `backend/tests/services/test_llm_compat.py`

- [ ] **Step 1: 写失败测试**

```python
"""LLM 供应商能力兼容层测试：矩阵匹配 / 降级 / max_tokens / override"""
import pytest


@pytest.mark.parametrize(
    "base_url,expected",
    [
        ("https://token-plan-cn.xiaomimimo.com/v1", False),
        ("https://api.siliconflow.cn/v1", True),
        ("https://api.openai.com/v1", True),
        ("https://unknown.example.com/v1", False),  # 未知端点保守默认
        (None, None),  # 未配置时由 provider 判定兜底
    ],
)
def test_get_provider_capabilities_json_mode(base_url, expected):
    from app.services.llm import get_provider_capabilities

    caps = get_provider_capabilities(base_url)
    if expected is None:
        return  # None 分支只验证不抛错
    assert caps["json_mode"] is expected


def test_get_provider_capabilities_max_tokens_default():
    from app.services.llm import get_provider_capabilities

    assert get_provider_capabilities("https://token-plan-cn.xiaomimimo.com/v1")["max_output_tokens"] == 4096
    assert get_provider_capabilities("https://api.openai.com/v1")["max_output_tokens"] == 4096
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py -q`
Expected: FAIL（ImportError: cannot import name 'get_provider_capabilities'）

- [ ] **Step 3: 实现能力矩阵**

在 `llm.py` 的 `_detect_provider`（L52）之后插入：

```python
# --------------- 供应商能力矩阵 ---------------
#
# 兼容层：部分 OpenAI 兼容端点（如 mimo Token Plan）的 json_object 模式
# 输出会被服务端截断（2026-08-06 实测）。调用方保持声明式传参，
# 由本层按 base_url 前缀匹配能力决定是否下发 response_format。
# 供应商修复后，把对应前缀的 json_mode 改回 True 即恢复原生模式。

_PROVIDER_CAPABILITIES: list[tuple[str, dict]] = [
    # mimo Token Plan：json_object 当前被服务端截断 → 降级为 prompt 指令
    ("token-plan-cn.xiaomimimo.com", {"json_mode": False, "max_output_tokens": 4096}),
    # SiliconFlow：json_object 正常（embedding/chat 均验证过）
    ("api.siliconflow.cn", {"json_mode": True, "max_output_tokens": 4096}),
    # OpenAI 官方：原生支持
    ("api.openai.com", {"json_mode": True, "max_output_tokens": 4096}),
    # OpenAI 兼容代理（未知端点）：保守默认 → 降级，宁可 prompt 指令 + 容错解析
    ("*", {"json_mode": False, "max_output_tokens": 4096}),
]

_DEFAULT_CAPS = {"json_mode": False, "max_output_tokens": 4096}


def get_provider_capabilities(base_url: str = None) -> dict:
    """按 base_url 前缀匹配供应商能力。

    Returns: {"json_mode": bool, "max_output_tokens": int}
    未匹配到具名供应商时回退到 "*" 保守默认（json_mode=False）。
    """
    if not base_url:
        return dict(_DEFAULT_CAPS)
    lower = base_url.lower()
    for prefix, caps in _PROVIDER_CAPABILITIES:
        if prefix == "*" or prefix in lower:
            return dict(caps)
    return dict(_DEFAULT_CAPS)


def _json_mode_override() -> str:
    """应急开关：force-on / force-off / auto（默认）"""
    return os.environ.get("LLM_JSON_MODE_OVERRIDE", "auto").strip().lower()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/llm.py backend/tests/services/test_llm_compat.py
git commit -m "feat(llm): provider capability matrix for json_mode compatibility"
```

---

### Task 2: _should_use_response_format 升级（读矩阵 + override）

**Files:**
- Modify: `backend/app/services/llm.py:55-61`
- Test: `backend/tests/services/test_llm_compat.py`

- [ ] **Step 1: 写失败测试**

```python
def test_should_use_response_format_mimo_false():
    """mimo Token Plan json_object 截断 → 返回 False（降级）"""
    from app.services.llm import _should_use_response_format

    assert _should_use_response_format("https://token-plan-cn.xiaomimimo.com/v1") is False


def test_should_use_response_format_siliconflow_true():
    from app.services.llm import _should_use_response_format

    assert _should_use_response_format("https://api.siliconflow.cn/v1") is True


def test_should_use_response_format_override(monkeypatch):
    """应急开关 force-on 强制启用（供应商修复后使用）"""
    from app.services.llm import _should_use_response_format

    monkeypatch.setenv("LLM_JSON_MODE_OVERRIDE", "force-on")
    assert _should_use_response_format("https://token-plan-cn.xiaomimimo.com/v1") is True

    monkeypatch.setenv("LLM_JSON_MODE_OVERRIDE", "force-off")
    assert _should_use_response_format("https://api.siliconflow.cn/v1") is False


def test_should_use_response_format_anthropic_never():
    """Anthropic 永远不用 response_format（原生不支持，走 prompt 指令）"""
    from app.services.llm import _should_use_response_format

    monkeypatch = None
    assert _should_use_response_format("https://api.anthropic.com/v1") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py -q`
Expected: FAIL（mimo 现在按 provider 判定为 openai → True，断言 False 失败）

- [ ] **Step 3: 实现升级**

替换 `_should_use_response_format`（L55-61）：

```python
def _should_use_response_format(base_url: str = None) -> bool:
    """判断当前配置的 LLM 端点是否应下发 response_format（json_object）。

    优先级：LLM_JSON_MODE_OVERRIDE（应急开关）→ 能力矩阵 → provider 兜底。
    Anthropic 原生不支持，恒 False（走 prompt 指令降级，见 _call_anthropic）。
    """
    override = _json_mode_override()
    if override == "force-on":
        return True
    if override == "force-off":
        return False
    if base_url is None:
        from app.core.config import LLM_BASE_URL

        base_url = LLM_BASE_URL
    if _detect_provider(base_url) != "openai":
        return False
    return get_provider_capabilities(base_url)["json_mode"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/llm.py backend/tests/services/test_llm_compat.py
git commit -m "feat(llm): capability-matrix driven response_format decision with override"
```

---

### Task 3: _call_llm_with_retry 降级 + 显式 max_tokens

**Files:**
- Modify: `backend/app/services/llm.py:787-827`
- Test: `backend/tests/services/test_llm_compat.py`

- [ ] **Step 1: 写失败测试**（mock resolved client 捕获 kwargs）

```python
class FakeResponse:
    def __init__(self, content="{\"ok\": true}"):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})})()]


class FakeCompletions:
    def __init__(self, captured, content=None):
        self._captured = captured
        self._content = content or "{\"ok\": true}"

    async def create(self, **kwargs):
        self._captured.update(kwargs)
        return FakeResponse(self._content)


class FakeChat:
    def __init__(self, captured, content=None):
        self.completions = FakeCompletions(captured, content)


class FakeClient:
    def __init__(self, captured, content=None):
        self.chat = FakeChat(captured, content)


async def test_call_with_retry_mimo_downgrades(monkeypatch):
    """mimo：json_object 不下发，system 附加 JSON 指令，max_tokens 显式"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "mimo-v2.5", 60,
                         "https://token-plan-cn.xiaomimimo.com/v1", "openai"),
    )
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("给个 JSON", response_format={"type": "json_object"}, user_id=1)

    assert "response_format" not in captured
    assert captured["max_tokens"] == 4096
    system_msg = captured["messages"][0]["content"]
    assert "严格以 JSON 格式输出" in system_msg


async def test_call_with_retry_siliconflow_keeps_json_mode(monkeypatch):
    """SiliconFlow：json_object 正常下发"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "BAAI/bge-m3", 60,
                         "https://api.siliconflow.cn/v1", "openai"),
    )
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("给个 JSON", response_format={"type": "json_object"}, user_id=1)

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_tokens"] == 4096
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py::test_call_with_retry_mimo_downgrades -q`
Expected: FAIL（当前 kwargs 无 max_tokens；mimo 时 response_format 被下发）

- [ ] **Step 3: 实现**

替换 `_call_llm_with_retry` 的 OpenAI 分支（L815-827）：

```python
    kwargs = dict(
        model=resolved_model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    caps = get_provider_capabilities(base_url)
    if response_format and _should_use_response_format(base_url):
        kwargs["response_format"] = response_format
    else:
        # 降级：端点不支持/不可靠 json_object → prompt 指令约束
        if response_format and response_format.get("type") == "json_object":
            kwargs["messages"][0]["content"] = (
                f"{system_msg}\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。"
            )
    kwargs["max_tokens"] = caps["max_output_tokens"]

    response = await resolved_client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()
```

注意：保持 `kwargs["max_tokens"]` 恒在（避免服务端默认值截断）；测试断言 `captured["max_tokens"] == 4096`。

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/llm.py backend/tests/services/test_llm_compat.py
git commit -m "feat(llm): explicit max_tokens + json downgrade in _call_llm_with_retry"
```

---

### Task 4: raw_llm_call / _call_llm_with_retry_messages 同步

**Files:**
- Modify: `backend/app/services/llm.py:740-773`（raw_llm_call OpenAI 分支）
- Modify: `backend/app/services/llm.py:838-861`（_call_llm_with_retry_messages OpenAI 分支）
- Test: `backend/tests/services/test_llm_compat.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_raw_llm_call_mimo_downgrades(monkeypatch):
    """raw_llm_call：mimo 时 response_format 被剥离，max_tokens 默认显式"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "mimo-v2.5", 60,
                         "https://token-plan-cn.xiaomimimo.com/v1", "openai"),
    )
    from app.services.llm import raw_llm_call

    await raw_llm_call(
        user_id=1,
        model="mimo-v2.5",
        messages=[{"role": "user", "content": "给个 JSON"}],
        response_format={"type": "json_object"},
    )

    assert "response_format" not in captured
    assert captured["max_tokens"] == 4096


async def test_raw_llm_call_siliconflow_keeps(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "model", 60,
                         "https://api.siliconflow.cn/v1", "openai"),
    )
    from app.services.llm import raw_llm_call

    await raw_llm_call(
        user_id=1,
        model="model",
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )

    assert captured["response_format"] == {"type": "json_object"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py::test_raw_llm_call_mimo_downgrades -q`
Expected: FAIL（response_format 原样透传）

- [ ] **Step 3: 实现**

3a) `raw_llm_call` OpenAI 分支（L772-773 前）插入：

```python
    caps = get_provider_capabilities(base_url)
    response_format = kwargs.get("response_format")
    if response_format and not _should_use_response_format(base_url):
        # 降级：剥离 response_format；json 指令在 messages 的 system 里追加
        kwargs.pop("response_format", None)
        if response_format.get("type") == "json_object":
            msgs = list(kwargs.get("messages", []))
            if msgs and msgs[0].get("role") == "system":
                msgs[0] = {
                    **msgs[0],
                    "content": f"{msgs[0].get('content', '')}\n请严格以 JSON 格式输出，不要包含任何其他文字或 markdown 代码块。",
                }
                kwargs["messages"] = msgs
    kwargs.setdefault("max_tokens", caps["max_output_tokens"])

    response = await resolved_client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()
```

3b) `_call_llm_with_retry_messages` OpenAI 分支（L857-861）插入：

```python
    caps = get_provider_capabilities(base_url)
    response_format = kwargs.get("response_format")
    if response_format and not _should_use_response_format(base_url):
        kwargs.pop("response_format", None)
    kwargs.setdefault("max_tokens", caps["max_output_tokens"])

    response = await resolved_client.chat.completions.create(
        messages=messages, **kwargs
    )
    return response.choices[0].message.content.strip()
```

注意：`_call_llm_with_retry_messages` 的 messages 是调用方传入的 list，降级时**不改 messages**（只剥离 response_format，指令靠调用方 prompt 已含的 JSON 要求 + 统一容错解析兜底）。若调用方传了 system 消息需要指令，可在 kwargs 处理，但保持最小改动。

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_llm_compat.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: 全量回归**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/ -q`
Expected: 全绿（既有 200+ 测试不受影响）

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/llm.py backend/tests/services/test_llm_compat.py
git commit -m "feat(llm): apply json compat layer to raw_llm_call and messages path"
```

---

### Task 5: 真实供应商验证 + 文档

**Files:**
- Modify: `backend/app/services/CLAUDE.md`（llm.py 职责行追加兼容层说明）

- [ ] **Step 1: 真实 mimo 降级验证**

Run: `docker compose run --rm backend python -c "
import asyncio
from app.services.llm import _call_llm_with_retry
async def main():
    raw = await _call_llm_with_retry('输出 JSON 对象：{\"status\": \"ok\"}（只需这一个字段）', response_format={'type': 'json_object'}, user_id=1)
    print('len:', len(raw))
    print('RAW:', repr(raw)[:150])
asyncio.run(main())
"`
Expected: 输出**完整** JSON（不再是 `'```json\n['` 截断），长度明显 > 5

- [ ] **Step 2: override 应急开关验证**

Run: `LLM_JSON_MODE_OVERRIDE=force-on docker compose run --rm backend python -c "
import asyncio
from app.services.llm import _should_use_response_format
print(_should_use_response_format('https://token-plan-cn.xiaomimimo.com/v1'))
"`
Expected: True（force-on 生效）

- [ ] **Step 3: 更新 CLAUDE.md**

在 `backend/app/services/CLAUDE.md` 的 llm.py 职责行补充：
```
- 供应商能力兼容层：`_PROVIDER_CAPABILITIES` 矩阵（json_mode/max_output_tokens）+ `LLM_JSON_MODE_OVERRIDE` 应急开关（force-on/force-off/auto）；json_object 不可靠的端点（如 mimo Token Plan 2026-08-06 实测截断）自动降级为 prompt 指令 + 容错解析兜底，调用方保持声明式传参零改动
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/CLAUDE.md
git commit -m "docs(llm): record provider capability compat layer"
```

---

## Self-Review

**Spec 覆盖：**
- ✅ 能力矩阵（Task 1：mimo→False / siliconflow→True / openai→True / 未知→False / max 4096）
- ✅ _should_use_response_format 升级 + override（Task 2）
- ✅ _call_llm_with_retry 降级 + max_tokens（Task 3）
- ✅ raw_llm_call / _call_llm_with_retry_messages 同步（Task 4）
- ✅ 生产 8 处调用点零改动（未触碰）
- ✅ 真实 mimo 验证 + 文档（Task 5）

**类型一致性：** `get_provider_capabilities(base_url) -> dict`（{"json_mode": bool, "max_output_tokens": int}）；`_json_mode_override() -> str`（auto/force-on/force-off）；Task 3/4 均消费同一函数与同一 caps 结构。

**风险提示：**
- `_call_llm_with_retry_messages` 降级不改 messages（最小改动）；若调用方需 system 指令需在调用侧 prompt 处理
- 测试的 FakeClient 未实现 `chat.completions.create` 之外的接口——仅测 OpenAI 分支路径，Anthropic 分支不动
- mimo 修复 json_object 后：改 `_PROVIDER_CAPABILITIES` 对应行 `"json_mode": True`，或临时 `LLM_JSON_MODE_OVERRIDE=force-on`
