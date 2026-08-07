# 管理员全局模型配置 — 设计文档

> 日期：2026-08-07 | 状态：已批准（brainstorming 流程）
> 关联：`docs/analysis/tech-audit-2026-08-05.md`（embedding 配置痛点）

## 背景与问题

系统当前模型配置存在两处痛点，管理员无法通过 UI 配置：

1. **全局 LLM 配置有后端但无前端 UI**
   - 后端能力已完整：`user_profile` 表 4 个 key（`llm_api_key`/`llm_base_url`/`llm_model`/`llm_timeout`），`GET/PUT /api/profile`（admin-only，掩码返回），热加载闭环（`_reload_from_db()` → `rebuild_clients()`）已存在。
   - 但前端只有 per-user 的 `SettingsAIConfig.vue`（`/api/profile/llm`），管理员无法从 UI 改全局 LLM，只能改数据库或 `.env`。
   - per-user 配置已实现"用户未配置 → 回退全局"（`get_user_llm_config()`，`core/config.py:109-127`），设计全局默认时无需改动解析链。

2. **Embedding 配置纯 env、无任何 UI**
   - `embedding_service.py` 全部配置来自模块级 env 常量（`EMBEDDING_BACKEND`/`EMBEDDING_MODEL_REPO`/`EMBEDDING_MODEL_DIR`/`EMBEDDING_DIMENSION`/`SILICONFLOW_*` 等），无 DB 存储、无 API、非热更新。
   - 换 embedding 模型必须改 env + 重建容器，且 `question_bank` 每题存 `embedding_model`/`embedding_dim` 列，换模型后旧向量失效需重算（生产 2026-08-06 切 SiliconFlow bge-m3 后重算 320 题）。

## 目标

- 管理员在设置页 → 管理员管理界面新增 **「模型配置」tab**，统一配置全局 LLM 和 embedding。
- 全局 LLM：管理员可从 UI 读/改主模型 Base URL、模型名、API Key、超时，测试连接。
- Embedding：管理员可从 UI 选后端模式、模型名、维度、API Key，测试连接；更换模型时自动触发全量向量重算并显示进度。
- 避免"每次都要在后端修改"。

## 非目标

- 不改 per-user LLM 配置（`SettingsAIConfig.vue` / `/api/profile/llm`）的现有行为。
- 不重写 embedding 的服务逻辑（仅把配置来源从 env 常量改为 DB 优先 + env 兜底）。
- 不新增独立的 settingsApi 服务层（复用 `profileApi.js`）。

## 方案设计

### 入口

`SettingsAdmin.vue` 现有 2 个 admin tab（`taxonomy` 分类管理 / `quality` 聚合质量）→ 新增第 3 个 **「模型配置」** tab。该页本身 admin-only，无需额外权限判断。新增 `SettingsGlobalModel.vue` 业务组件，挂在 `SettingsAdmin.vue` 的 tab 切换区。

### 后端 — 全局 LLM（改动最小）

复用现有 `GET/PUT /api/profile`，无需新增存储。

- **读取**：`GET /api/profile` 已返回掩码的 `llm_api_key`（+ `llm_api_key_set`）、`llm_base_url`、`llm_model`、`llm_timeout`（`profile.py:178-255`）。
- **写入**：`PUT /api/profile` 已支持这些 key（`ALLOWED_PROFILE_KEYS` 白名单），保存后 `_reload_from_db()` + `rebuild_clients()` 热加载，`_sync_env_file()` 回写 `.env`。
- **新增：全局 LLM 测试连接** `POST /api/profile/llm/test-global`（admin-only）：用当前全局配置（`_get_global_llm_config()`，`core/config.py:162-188`）探测 base_url/api_key 连通性。参照现有 per-user `GET /api/profile/llm/status`（`profile_pkg/llm.py:54`）实现，但数据源用全局配置。

### 后端 — Embedding（核心新增）

#### 存储：复用 `user_profile` 表新增 key

| key | 说明 | 默认 |
|-----|------|------|
| `embedding_backend` | `onnx` / `siliconflow` / `auto` | `auto` |
| `embedding_model_repo` | ONNX HF repo（如 `Xenova/bge-small-zh-v1.5`） | env 兜底 |
| `embedding_model_dir` | ONNX 本地模型目录 | env 兜底 |
| `embedding_dimension` | 向量维度 | `512` |
| `embedding_api_key` | SiliconFlow API Key（掩码读取） | 空 |
| `embedding_api_model` | SiliconFlow 模型名（如 `BAAI/bge-m3`） | env 兜底 |
| `embedding_api_base_url` | SiliconFlow Base URL | env 兜底 |

读取链：`get_profile_setting(key, env_default)` 已有 env 兜底语义（`config.py:93-106`），`embedding_service.py` 改为在加载时/重载时从 DB 读取覆盖 env 常量。

#### API：独立端点（避免污染现有 `PUT /api/profile`）

- `GET /api/profile/embedding`（admin-only）：返回全部 embedding 配置，API key 掩码 + `_set` 标记。
- `PUT /api/profile/embedding`（admin-only）：校验 backend 合法值、dimension 正整数；写 `user_profile`；调用 `reload_embedding_config()` 热加载；若 backend/model/dimension 变化 → 触发全量 embedding 重算 job。
- `POST /api/profile/embedding/test`（admin-only）：用提交的配置探连通性（SiliconFlow 模式下用 api_key 调一次 embedding 接口；ONNX 模式验证模型目录/文件存在）。

#### 热加载

`embedding_service.py` 从模块级 env 常量改为：模块级保持 env 默认值兜底 + 新增 `reload_embedding_config()` 从 DB 读覆盖模块级变量，重建 ONNX session / SiliconFlow client / FAISS 索引管理器。保存端点调用后立即生效。

#### 自动重算 job

保存 embedding 配置且 `(backend, model, dimension)` 任一变化时，后台触发全量重算：
- 复用现有 `jobs` 表 + SSE 进度推送机制（`bank_build.py` `/api/jobs/{id}/stream`）。
- 遍历 `question_bank` 重编码向量，更新每题 `embedding_model`/`embedding_dim`，重建 FAISS 索引。
- 前端保存后若检测到重算 job，显示进度条。

### 前端

- 新组件 `frontend/src/components/business/SettingsGlobalModel.vue`：两段表单。
  - **全局 LLM**：主模型 Base URL / 主模型名称 / API Key（掩码，空保留旧）/ 超时 + 「测试连接」。
  - **Embedding**：后端模式下拉（ONNX 本地 / SiliconFlow API / 自动）+ 模型名 + 维度 + API Key（SiliconFlow 模式显示）+ 「测试连接」。
  - 保存 embedding 且模型变化 → 显示重算进度条（SSE）。
- 服务层：复用 `profileApi.js`，新增 `fetchGlobalEmbeddingConfig` / `updateGlobalEmbeddingConfig` / `testGlobalLLM` / `testGlobalEmbedding`。
- `SettingsAdmin.vue`：`adminTabs` 增加 `{ id: 'model', label: '模型配置' }`，tab 切换区挂载 `SettingsGlobalModel`。

## 数据流

```
管理员打开设置 → 管理员管理 → 模型配置 tab
  ├─ LLM: GET /api/profile → 表单 → PUT /api/profile → _reload_from_db + rebuild_clients（热生效）
  │        测试连接: POST /api/profile/llm/test-global
  └─ Embedding: GET /api/profile/embedding → 表单 → PUT /api/profile/embedding
       → reload_embedding_config()（热生效）
       → 模型变化 → 触发重算 job → SSE 进度 → 前端进度条
```

## 测试计划

- **后端**（`backend/tests/services/` 或新增）：
  - embedding 配置读写端点（admin-only、掩码、校验）。
  - `reload_embedding_config()` 后 embedding_service 使用 DB 值。
  - 保存模型变化触发重算 job 创建；不变则不触发。
  - 全局 LLM 测试连接端点（mock OpenAI client）。
- **前端**（E2E，mock API）：`SettingsAdmin` 模型配置 tab 存在、LLM 表单读写、embedding 表单后端模式切换显示对应字段、测试连接、重算进度条。

## 风险与注意

- **embedding 换模型重算耗时**：生产全量重算数百题需数分钟，必须走后台 job 而非同步请求。
- **question_bank 每题 embedding_model/dim 列**：换模型后旧题须更新该列，避免与 FAISS 索引维度不一致导致检索崩溃。
- **FAISS 索引重建**：`faiss_index_manager` 的 per-cat2 centroid 缓存须在重算后失效重建。
- **敏感字段**：embedding_api_key 沿用 `llm_api_key` 明文存 `user_profile` + 掩码读取模式。
- **`_sync_env_file` 目前对 LLM key 是跳过**（`config.py:240-246` 注释"已迁移 per-user"）：本设计不改动它，全局 LLM 保存后 `rebuild_clients()` 已保证热生效，`.env` 回写非必需。

## grill-me 决策确认（2026-08-07）

以下为追问式工作流确认的方案级决策，实现必须遵循：

1. **重算失败原子性**：逐批 UPDATE 前先读取旧 `embedding` 值，失败时逆向恢复已更新行（"全成功或全不动"），job 标 failed 并提示重试。杜绝新旧模型向量混库导致 FAISS 维度不一致崩溃。
2. **重算范围**：`question_bank` 全部未删除题（`deleted_at IS NULL`），含个人题与 pending——与 FAISS 按 `(job_position, owner_id)` 分池口径一致，避免个人池维度不一致。
3. **配置切换时序（方案 A）**：保存配置立即 reload + invalidate FAISS，接受过渡窗口（重算完成前 embedding 检索/聚类短暂不可用或失真，几十秒，其余功能不受影响）。不加"重算期间禁用 embedding"防护。
4. **启动配置同步**：`asgi.py` 与 `worker.py` 启动加载处，紧跟 `_reload_from_db()` 之后调用 `reload_embedding_config()`，保证容器重启后配置保持；DB 无 `embedding_*` key 时 no-op（env 兜底兼容）。
