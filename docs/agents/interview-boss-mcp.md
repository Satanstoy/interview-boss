# InterviewBoss MCP 外部 Agent 使用说明

这份说明给配置了 InterviewBoss MCP 的外部 agent 使用。它解决两个容易混淆的问题：MCP 能发现哪些工具，以及 agent 如何把这套工具调用规则保存成自己的 skill。

## 先说结论：MCP 不等于完整的 Agent Skill

MCP 和 skill 是两层东西：

| 部分 | 作用 | 是否自动永久保存 |
|---|---|---|
| MCP 初始化 instructions | 自动把 InterviewBoss 的工具使用 skill 交给已配置的 agent | 当前连接/客户端上下文有效 |
| InterviewBoss `load_skill` | 在当前 MCP `session_id` 中按需加载领域面试技能 | 否，只对当前 session 生效 |
| 客户端 `SKILL.md` | 服务端自动加载 skill 的规范来源；也可作为客户端兼容兜底 | 可选，客户端支持时才需保存 |

因此，正常情况下只需要配置 MCP：

1. MCP 初始化时自动收到 `interview-tool-use` 使用 skill，并在服务端 session 中自动激活。
2. 根据岗位和面试阶段调用其他领域 skill 的 `load_skill`。

如果某个客户端不消费 MCP 初始化 instructions，再把 [SKILL.md](interview-boss-mcp/SKILL.md) 复制到它的项目级 skill 目录作为兜底即可。MCP 服务端同时通过工具 schema、工具 docstring 和 `instructions` 提供工具能力说明。

## 1. 配置 MCP

在 agent 客户端导入设置页生成的 JSON：

```json
{
  "mcpServers": {
    "interview-boss": {
      "url": "http://你的地址/mcp",
      "headers": {
        "Authorization": "Bearer ib_mcp_..."
      }
    }
  }
}
```

以后服务器切换到 HTTPS，只需把 `url` 改为 `https://你的域名/mcp`。Token 不需要因为 URL 变化而重置。

HTTP 阶段不要直接暴露到不可信公网；应优先使用内网、VPN 或安全隧道。不要把 Token 放在 URL 查询参数中。

### 只支持 stdio 的客户端：npx 兼容模式

如果客户端不支持远程 Streamable HTTP，可以使用设置页生成的第二份 npx 配置。它通过开源的 `mcp-remote` 把本地 stdio 转发到 InterviewBoss：

```json
{
  "mcpServers": {
    "interview-boss": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://你的地址/mcp",
        "--transport",
        "http-only",
        "--allow-http",
        "--header",
        "Authorization:${INTERVIEW_BOSS_MCP_AUTH}"
      ],
      "env": {
        "INTERVIEW_BOSS_MCP_AUTH": "Bearer ib_mcp_..."
      }
    }
  }
}
```

`npx` 是 Node.js 的包运行器，不需要申请证书；用户本机需要 Node.js 18+。证书是服务器 HTTPS 的问题，不是 npx 的问题。HTTP 下的 `--allow-http` 只应在内网、VPN 或安全隧道中使用；将来切换 HTTPS 时，把 URL 改为 HTTPS 并移除 `--allow-http` 即可。原生支持远程 HTTP 的客户端应优先使用第一份配置，少运行一层桥接进程。

参考：[mcp-remote 使用说明](https://github.com/geelen/mcp-remote#readme)。

## 2. 自动装载 MCP 使用 skill

InterviewBoss MCP 在连接初始化时会自动附带 `interview-tool-use` skill。外部 agent 不需要先手动复制文件，也不需要调用 `load_skill` 加载这个工具使用 skill。它会自动获得以下规则：

- 先维护同一场面试的 `session_id`；
- 按岗位使用 `job_position`；
- 区分搜索、抽题和选题；
- 只能选择服务端返回的候选题；
- 正确处理空结果；
- 不泄露 Token、账户字段和内部调试信息。

服务端还会在每个 MCP session 自动激活该 skill，因此即使客户端没有本地 skill 文件，服务端 session 仍然能记录它的激活状态。

本仓库中的 [SKILL.md](interview-boss-mcp/SKILL.md) 是这套自动加载内容的规范来源。只有当某个客户端忽略 MCP `instructions` 时，才需要将它复制到：

```text
<agent-project>/skills/interview-boss-mcp/SKILL.md
```

这个客户端 skill 主要保存：

- 如何创建并持续复用 `session_id`；
- 何时加载 `project-deep-dive`、`theory-qa`、`algorithm-coding` 等服务端 skill；
- 何时搜索、抽题和选题；
- 如何处理空结果和失效候选；
- 不信任客户端 `user_id` / `bank_mode`，不泄露内部元数据。

## 3. 推荐调用流程

### 首次连接或新面试

agent 应生成一个只用于本次面试的 `session_id`，例如 UUID，并保存服务端返回的 `metadata.session_id`。之后每次调用都传同一个值。

### 加载面试技能

根据当前任务按需加载，不要每轮重复加载：

```text
load_skill(
  skill_name="project-deep-dive",
  session_id="<session-id>"
)
```

可用服务端 skill：

| 名称 | 适用场景 |
|---|---|
| `project-deep-dive` | 项目经历、架构、个人贡献、技术取舍 |
| `theory-qa` | 操作系统、网络、数据库、Redis、JVM 等基础题 |
| `algorithm-coding` | 算法、手撕代码、边界、复杂度、测试 |
| `adaptive-difficulty` | 根据回答质量升降难度 |
| `interview-rhythm` | 控制项目、八股、系统设计、算法、行为面的节奏 |
| `hr-soft-skills` | 行为面、职业规划、协作、收尾反问 |

`interview-tool-use` 已经由 MCP 初始化自动提供；下面的 `load_skill` 只用于加载具体面试领域策略。

### 搜索题目

用户指定技术点时使用 `search_questions`，关键词应具体，通常提取 2–5 个：

```text
search_questions(
  keywords=["Redis", "缓存穿透", "布隆过滤器"],
  job_position="后端开发",
  question_type="knowledge_probe",
  session_id="<session-id>"
)
```

### 按岗位抽题

用户要求随机出题、指定难度或需要新题时使用 `draw_questions`：

```text
draw_questions(
  count=3,
  job_position="Java 工程师",
  difficulty="medium",
  question_type="algorithm_coding",
  session_id="<session-id>"
)
```

`job_position` 是岗位过滤条件，未传时使用账户当前岗位。可选题型、难度和分类由服务端校验。

### 选择题目

搜索或抽题返回多个 `items` 时，agent 根据当前面试目标选择一个零基索引，然后调用：

```text
select_question(
  candidate_index=1,
  session_id="<session-id>"
)
```

服务端会重新校验题目的可见性和账户权限。不要把自己构造的题目列表、题目文本或题目 ID 传给 `select_question`。

选题成功后，agent 下一句应直接把 `selected_question` 作为面试问题问出来，不要先解释工具调用过程。

## 4. 返回值怎么判断

工具返回统一结构：

- `ok`：调用是否成功；
- `items`：搜索/抽题候选题；
- `selected_question`：选定的下一道题；
- `question_plan`：服务端绑定的出题计划；
- `metadata.session_id`：应持续复用的 session；
- `metadata.debug_reason`：仅供 agent 内部诊断。

注意：`ok=true` 仍可能 `items=[]`。空结果时依次尝试：

1. 搜索为空 → 按同岗位和主题抽题；
2. 抽题为空 → 换一组更具体的关键词搜索；
3. 两者都为空 → 明确说明题库暂时没有合适题目，再自行构造一道备用题；
4. 选题失败 → 重新搜索或抽题，不要伪造候选题。

## 5. 账户边界

MCP Token 已绑定账户。即使工具 schema 中出现 `user_id` 或 `bank_mode`，服务端也会以 Token 对应账户为准。外部 agent 不应尝试覆盖它们，也不能通过改参数访问其他账户的个人题库。

## 6. HTTP 切换 HTTPS

当前可以先通过 HTTP 使用。未来申请 HTTPS 后：

1. 修改后端 `MCP_PUBLIC_URL` 为 `https://你的域名/mcp`；
2. 配置 Nginx 或安全隧道的 HTTPS 证书和转发；
3. 重启后端；
4. 在 agent 配置里只更新 `url`；
5. 原 MCP Token 可以继续使用。

详细服务端实现见 [README 的 MCP 章节](../../README.md#外部-mcp-接入)。
