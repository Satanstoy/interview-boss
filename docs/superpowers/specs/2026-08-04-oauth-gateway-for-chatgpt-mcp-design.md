# OAuth Gateway for ChatGPT MCP Connector

## Problem

ChatGPT MCP 连接器要求 OAuth 2.1 + PKCE 认证，不能直接使用 InterviewBoss 的静态 Bearer Token。
需要在不改动现有 MCP 认证的前提下，增加 OAuth 层让 ChatGPT 能连接 InterviewBoss MCP。

## Architecture

**网关模式**：独立 Python 服务（FastAPI），位于 InterviewBoss 前面。

```
ChatGPT ──OAuth 2.1──► OAuth Gateway (:8082) ──Bearer Token──► InterviewBoss (:8081)
                         │                                         │
                    /.well-known/*                           /mcp (原有)
                    /authorize                              
                    /token                                  
                    /mcp (反代)                             

Codex/Cursor ──Bearer Token──► InterviewBoss (:8081) [直连，不走网关]
```

宿主机 nginx 新增 443 server 监听 8082，对外暴露 `https://interviewboss.online:8082/`。
或者复用 443 端口，按路径分流 `/oauth/*` 和 `/.well-known/*` 到网关，`/mcp` 保留原直连。

**推荐按路径分流**（单端口，用户无需记端口号）：
- `https://interviewboss.online/.well-known/*` → 网关
- `https://interviewboss.online/oauth/*` → 网关（/authorize, /token, /register）
- `https://interviewboss.online/mcp` → 原 InterviewBoss（Codex/Cursor 直连）
- ChatGPT 的 /mcp 请求也走网关（网关反代到 InterviewBoss）

## Components

### 1. OAuth Gateway Service

位置：`oauth-gateway/`（项目根目录下独立目录）

技术栈：FastAPI + httpx + SQLite（独立数据库）

端点：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/.well-known/oauth-protected-resource` | GET | MCP 资源元数据（RFC 9728） |
| `/.well-known/oauth-authorization-server` | GET | 授权服务器元数据（RFC 8414） |
| `/oauth/authorize` | GET | 授权页（登录 + 同意） |
| `/oauth/token` | POST | 签发/刷新 access_token |
| `/oauth/register` | POST | 动态客户端注册（DCR） |
| `/mcp` | * | 反代 InterviewBoss MCP |

### 2. Discovery Endpoints

#### GET /.well-known/oauth-protected-resource

```json
{
  "resource": "https://interviewboss.online/mcp",
  "authorization_servers": ["https://interviewboss.online"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["mcp:read", "mcp:write"]
}
```

#### GET /.well-known/oauth-authorization-server

```json
{
  "issuer": "https://interviewboss.online",
  "authorization_endpoint": "https://interviewboss.online/oauth/authorize",
  "token_endpoint": "https://interviewboss.online/oauth/token",
  "registration_endpoint": "https://interviewboss.online/oauth/register",
  "code_challenge_methods_supported": ["S256"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "response_types_supported": ["code"],
  "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
  "scopes_supported": ["mcp:read", "mcp:write"]
}
```

### 3. OAuth Flow

#### 3.1 Dynamic Client Registration (DCR)

ChatGPT 首次连接时调用 `POST /oauth/register`：

```json
// Request
{
  "client_name": "ChatGPT Connector",
  "redirect_uris": ["https://chatgpt.com/connector/oauth/{callback_id}"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none"
}

// Response
{
  "client_id": "chatgpt_xxxx",
  "client_name": "ChatGPT Connector",
  "redirect_uris": ["https://chatgpt.com/connector/oauth/..."],
  "grant_types": ["authorization_code", "refresh_token"],
  "client_id_issued_at": 1722700000
}
```

#### 3.2 Authorization (PKCE)

```
GET /oauth/authorize?
  response_type=code&
  client_id=chatgpt_xxxx&
  redirect_uri=https://chatgpt.com/connector/oauth/...&
  code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&
  code_challenge_method=S256&
  state=xyz&
  resource=https://interviewboss.online/mcp
```

网关展示登录页（InterviewBoss 账号密码），用户登录后同意授权，302 回调：

```
HTTP/1.1 302 Found
Location: https://chatgpt.com/connector/oauth/{callback_id}?code=SplxlOBeZQQYbYS6WxSbIA&state=xyz
```

#### 3.3 Token Exchange

```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&
code=SplxlOBeZQQYbYS6WxSbIA&
redirect_uri=https://chatgpt.com/connector/oauth/...&
client_id=chatgpt_xxxx&
code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk
```

Response:
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "tGzv3JOkF0XG5Qx2TlKW...",
  "scope": "mcp:read mcp:write"
}
```

access_token 是 JWT（HS256），claims: `iss`, `sub=user_id`, `aud=mcp`, `scope`, `exp`, `iat`, `client_id`。

#### 3.4 MCP Request (Token Validation + Proxy)

```
GET/POST /mcp
Authorization: Bearer eyJ...
```

网关验证 JWT：
1. 解码 JWT，验证签名（HS256，网关自己的 secret）
2. 验证 iss、aud、exp
3. 提取 user_id（sub claim）
4. 查询 InterviewBoss 数据库获取该用户的 MCP Token
5. 转发到 InterviewBoss:8081/mcp，替换 Authorization: Bearer <mcp_token>

### 4. Database Schema

```sql
-- OAuth 客户端
CREATE TABLE oauth_clients (
  client_id       TEXT PRIMARY KEY,
  client_secret   TEXT,                    -- bcrypt hash，public client 为 NULL
  client_name     TEXT NOT NULL,
  redirect_uris   TEXT NOT NULL,           -- JSON array
  grant_types     TEXT NOT NULL,           -- JSON array
  auth_method     TEXT DEFAULT 'none',     -- none | client_secret_post
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 授权码（一次性，10 分钟过期）
CREATE TABLE oauth_codes (
  code              TEXT PRIMARY KEY,
  client_id         TEXT NOT NULL,
  user_id           INTEGER NOT NULL,
  code_challenge    TEXT NOT NULL,
  code_method       TEXT DEFAULT 'S256',
  scopes            TEXT,
  resource          TEXT,
  expires_at        TIMESTAMP NOT NULL,
  used              BOOLEAN DEFAULT FALSE,
  FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id)
);

-- OAuth access tokens
CREATE TABLE oauth_access_tokens (
  token_hash    TEXT PRIMARY KEY,
  user_id       INTEGER NOT NULL,
  client_id     TEXT NOT NULL,
  scopes        TEXT,
  expires_at    TIMESTAMP NOT NULL,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- OAuth refresh tokens
CREATE TABLE oauth_refresh_tokens (
  token_hash    TEXT PRIMARY KEY,
  user_id       INTEGER NOT NULL,
  client_id     TEXT NOT NULL,
  scopes        TEXT,
  expires_at    TIMESTAMP NOT NULL,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5. Token Forwarding

网关转发 /mcp 请求时需要获取用户的 InterviewBoss MCP Token：

1. 网关通过 `GET /api/profile/mcp`（带 admin 权限或直接查 DB）获取用户的 MCP Token
2. 或者直接查 InterviewBoss 的 SQLite `mcp_tokens` 表（共享 volume）

**推荐直接查 DB**（同机部署，共享 `backend/data/interview-boss.db`）：
- 网关读 `mcp_tokens.token_seed` → 用 HMAC 派生 raw token → 转发
- 或者如果用户还没有 MCP Token，自动调用 `issue_mcp_token` 创建一个

### 6. Settings UI Changes

SettingsMCP.vue 新增「ChatGPT 接入」卡片：

```
┌─────────────────────────────────────────────────────┐
│ ChatGPT 接入                                        │
│                                                     │
│ 通过 OAuth 2.1 + PKCE 让 ChatGPT 连接 InterviewBoss │
│                                                     │
│ 状态：已配置 / 未配置                                │
│                                                     │
│ 授权页 URL:  https://interviewboss.online/oauth/authorize  │
│ Token URL:   https://interviewboss.online/oauth/token      │
│ MCP URL:     https://interviewboss.online/mcp              │
│                                                     │
│ [复制 ChatGPT 配置提示词]                           │
│                                                     │
│ ⚠ ChatGPT 连接器需要在 ChatGPT 设置中添加 MCP：    │
│   URL: https://interviewboss.online/mcp              │
│   认证: OAuth (自动发现)                            │
└─────────────────────────────────────────────────────┘
```

### 7. Nginx Routing

宿主机 nginx 的 default server（443 IP 证书）增加分流规则。
所有 /mcp 请求统一走网关，由网关区分 OAuth token 和 static token：

```nginx
# OAuth 网关：discovery + authorize + token + register + /mcp 反代
location /.well-known/oauth- {
    proxy_pass http://127.0.0.1:8082;
}
location /oauth/ {
    proxy_pass http://127.0.0.1:8082;
}
location = /mcp {
    proxy_pass http://127.0.0.1:8082/mcp;
}
location /mcp/ {
    proxy_pass http://127.0.0.1:8082;
}
```

网关收到 /mcp 请求后：
1. 有 Authorization: Bearer <token>？
   - token 以 `eyJ` 开头（JWT）→ 解码验证 OAuth JWT → 提取 user_id → 查 InterviewBoss DB 获取该用户的 MCP Token → 转发到 InterviewBoss:8081/mcp（替换 Authorization 头）
   - token 以 `ib_mcp_` 开头（static）→ 直接转发到 InterviewBoss:8081/mcp（不替换）
2. 无 Authorization → 401 + WWW-Authenticate 头指向 oauth-protected-resource

### 8. Deployment

```yaml
# docker-compose.yml 新增
oauth-gateway:
  build:
    context: ./oauth-gateway
    dockerfile: Dockerfile
  ports:
    - "127.0.0.1:8082:8082"
  volumes:
    - ./backend/data:/app/data:ro  # 共享 InterviewBoss DB（只读）
    - oauth-gateway-data:/app/oauth-data  # OAuth 网关自己的 DB
  environment:
    - OAUTH_SECRET_KEY=...
    - INTERVIEW_BOSS_DB=/app/data/interview-boss.db
    - GATEWAY_BASE_URL=https://interviewboss.online
  networks:
    - app-network
```

### 9. Security Considerations

- OAuth access_token 是 JWT（HS256），网关本地验证，无需查 DB
- refresh_token 是不透明字符串，SHA-256 哈希存储
- 授权码一次性使用，10 分钟过期
- PKCE S256 强制要求（`code_challenge_methods_supported` 必须包含 S256）
- 网关 DB 独立于 InterviewBoss DB（不同 volume）
- ChatGPT 的 redirect_uri 白名单校验
- /mcp 反代时替换 Authorization 头，不暴露 InterviewBoss MCP Token 给 ChatGPT

### 10. Testing Strategy

- 单元测试：OAuth 端点（authorize, token, register, discovery）
- 集成测试：完整 OAuth 流程（DCR → authorize → token → MCP proxy）
- E2E 测试：ChatGPT 连接器实际连接验证
