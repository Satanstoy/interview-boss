# 真实多轮面试模拟 E2E 测试计划

## Context

当前 87 个测试全是单轮 mock pipeline 内部函数的测试，缺少**从 API 层面发起、跨轮状态累积、前端渲染验证**的完整面试模拟。

用户要求：用 Playwright 或后端 API 方式，进行多次完整的多轮面试 E2E 测试。

## 方案选择：双轨并行

### 轨道 A：后端 API E2E（httpx + 真实后端）

**目标**：从 HTTP 层面测试完整面试流程，验证 router → pipeline → SSE → message persistence 链路。

**方式**：
- 启动真实 Docker 后端（已有）
- 通过 `POST /api/auth/register` 注册测试用户
- 通过 `POST /api/chat/conversations` 创建对话
- 通过 `POST /api/chat/conversations/{id}/messages` 发送消息，解析 SSE 流
- LLM 调用通过 Docker 容器内的环境变量配置（使用真实 API key）
- 每轮收集 SSE 事件，验证节奏、检索、basis、insight 等

**优势**：测试真实链路，发现 pipeline 集成 bug
**劣势**：依赖外部 LLM API，结果不确定，速度慢，有成本

### 轨道 B：Playwright 前端 E2E（mock LLM，真实 UI）

**目标**：从用户视角测试完整面试体验，验证前端渲染、交互、SSE 消费。

**方式**：
- Playwright 启动前端（已有配置）
- Mock 所有 API 响应（`page.route()`），包括 SSE 流
- 预录制多个完整面试场景的 SSE 事件序列
- 验证前端正确渲染：消息气泡、thinking block、insight card、basis 引用、检索结果卡片
- 测试多轮对话的状态管理（streaming、processing steps、auto-scroll）

**优势**：确定性结果，速度快，无外部依赖
**劣势**：不测试真实 LLM 交互

## 决策：先 A 后 B

**轨道 A（后端 API）** 优先，因为：
1. 测试真实 pipeline 集成（router → pipeline → tools → SSE）
2. 验证跨轮状态累积（message_history、active_skills、session_notes）
3. 发现单轮 mock 测试覆盖不到的 bug

**轨道 B（Playwright）** 作为补充，测试前端渲染。

---

## 轨道 A：后端 API E2E 测试

### 文件结构

```
backend/tests/e2e/
├── conftest_e2e.py          # E2E fixtures: httpx client, auth, SSE parser
├── test_interview_flow.py   # 多场景完整面试模拟
```

### 基础设施

```python
# conftest_e2e.py

@pytest.fixture(scope="session")
def base_url():
    """Docker 后端地址"""
    return "http://localhost:8000"

@pytest.fixture(scope="session")
def auth_token(base_url):
    """注册并登录测试用户，返回 access token"""
    # POST /api/auth/register → token
    # 如果用户已存在，POST /api/auth/login → token

@pytest.fixture
def api_client(auth_token):
    """带认证的 httpx.AsyncClient"""
    # headers = {"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"}

async def parse_sse(response) -> list[dict]:
    """解析 SSE 响应为事件列表"""
    # 按行解析 "data: {JSON}\n\n"

async def send_and_collect(api_client, conversation_id, message) -> InterviewTurn:
    """发送消息并收集所有 SSE 事件"""
    # POST /api/chat/conversations/{id}/messages
    # 解析 SSE → InterviewTurn(events, response_text, basis, metadata)
```

### 测试场景

#### 场景 1：自由练习完整面试（10 轮）

```python
async def test_free_practice_full_interview(api_client):
    """完整的自由练习面试：开场 → 项目深挖 → 理论 → 算法 → 收尾"""
    # 1. 创建对话: POST /api/chat/conversations {mode: "free_practice"}
    # 2. 自我介绍轮
    turn1 = await send_and_collect(client, conv_id, "你好，我是后端开发工程师，3年经验")
    assert turn1.has_event("step")
    assert turn1.has_event("chunk")
    assert turn1.has_event("done")
    
    # 3. 项目深挖轮（模拟好回答）
    turn2 = await send_and_collect(client, conv_id, 
        "我做过一个分布式缓存系统，用 Redis Cluster 做热数据缓存，..."
        "通过一致性哈希分片，读写分离，解决了缓存雪崩问题。QPS 从 500 提升到 5000。")
    assert turn2.has_event("retrieved")  # 应该检索题目
    assert turn2.basis_type in ("interview_question", "mixed")
    
    # 4-10. 继续多轮...验证节奏和分布
    
    # 验证整体面试统计
    all_turns = [turn1, turn2, ...]
    assert 8 <= len(all_turns) <= 15  # 问题数量合理
```

#### 场景 2：JD 模式面试

```python
async def test_jd_mode_interview(api_client):
    """JD 模式：基于 JD 内容定制面试"""
    # 创建对话时传入 jd_text
    # 验证问题围绕 JD 技术栈展开
```

#### 场景 3：算法手撕代码面试

```python
async def test_algorithm_coding_interview(api_client):
    """算法面试：load_skill → 算法题 → 代码回答 → 复杂度追问"""
    # 发送"开始算法面试"
    # 验证 load_skill 被触发（insight 事件）
    # 验证算法题被抽取（retrieved 事件）
    # 回答代码，验证追问
```

#### 场景 4：短回答触发追问

```python
async def test_short_answer_triggers_followup(api_client):
    """短回答 → answer_complete=False → 面试官追问而非出新题"""
    # 面试官出题后，回答"嗯..."
    # 验证下一轮不是新题目，而是追问
```

#### 场景 5：强制关闭

```python
async def test_forced_closing_at_45_messages(api_client):
    """45 条消息后强制关闭"""
    # 快速轮转 45 条消息
    # 验证最后出现"你有什么想问我们的吗"
```

### SSE 事件验证器

```python
@dataclass
class InterviewTurn:
    events: list[dict]
    
    @property
    def response_text(self) -> str:
        return "".join(e.get("content", "") for e in self.events if e["type"] == "chunk")
    
    @property
    def basis(self) -> dict | None:
        return next((e for e in self.events if e["type"] == "basis"), None)
    
    @property
    def steps(self) -> list[str]:
        return [e["step"] for e in self.events if e["type"] == "step"]
    
    @property
    def retrieved_questions(self) -> list[dict]:
        return next((e.get("questions", []) for e in self.events if e["type"] == "retrieved"), [])
    
    @property
    def insights(self) -> list[str]:
        return [e.get("text", "") for e in self.events if e["type"] == "insight"]
    
    def has_event(self, event_type: str) -> bool:
        return any(e["type"] == event_type for e in self.events)
```

---

## 轨道 B：Playwright 前端 E2E 测试

### 文件

```
frontend/tests/e2e/chat-interview.spec.js
```

### 测试场景

#### 场景 1：完整面试 UI 流程

```javascript
test('完整自由练习面试 UI 流程', async ({ page }) => {
    // Mock auth
    // Mock 对话列表
    // Mock 多轮 SSE 响应（预录制的事件序列）
    // 1. 打开聊天页面
    // 2. 输入自我介绍 → 发送
    // 3. 验证消息气泡渲染
    // 4. 验证 thinking block 出现/展开
    // 5. 验证 insight card 渲染
    // 6. 验证 retrieved questions 卡片
    // 7. 验证 basis 引用显示
    // 8. 输入技术回答 → 发送
    // 9. 验证多轮消息的时间分组
    // 10. 验证 streaming 光标动画
})
```

#### 场景 2：算法面试模式

```javascript
test('算法手撕代码面试', async ({ page }) => {
    // Mock 算法面试 SSE 序列
    // 验证代码题渲染（代码块、复杂度要求）
})
```

---

## 实施步骤

### Step 1：创建后端 API E2E 基础设施
- `backend/tests/e2e/conftest_e2e.py`：httpx client、auth、SSE parser、InterviewTurn

### Step 2：实现场景 1 — 自由练习完整面试
- `backend/tests/e2e/test_interview_flow.py`：10 轮完整面试

### Step 3：实现场景 2-5 — JD 模式、算法、短回答、强制关闭

### Step 4：实现 Playwright 前端 E2E
- `frontend/tests/e2e/chat-interview.spec.js`

### Step 5：运行验证

---

## 验证方式

```bash
# 后端 API E2E（需要 Docker 后端运行）
docker compose exec backend python -m pytest tests/e2e/test_interview_flow.py -v

# Playwright E2E（需要前端 dev server 或 nginx）
cd frontend && npx playwright test tests/e2e/chat-interview.spec.js
```

## 关键约束

1. **LLM 依赖**：后端 API E2E 使用真实 LLM API（已有 key），结果不确定但测试真实链路
2. **超时**：每轮 LLM 调用可能需要 5-30s，总测试时间可能 5-10 分钟
3. **幂等性**：每次测试注册新用户，避免状态污染
4. **CSRF**：所有 POST 请求需要 `X-Requested-With: XMLHttpRequest` 或 `Content-Type: application/json`
