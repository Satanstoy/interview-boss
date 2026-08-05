# 模型可用性预检守卫设计（Model Status Guard）

日期：2026-08-05
状态：已批准，实施中

## 背景

系统内需要调用 LLM 模型的功能（Chat、AI 答案、手撕代码评审、导入解析、题库重建等），在模型未配置或未接通时，用户点击后才会收到后端错误 toast，体验差。目标：**点击前**预检，未就绪时弹 Dialog 提醒并引导到设置页的 AI 配置区。

## 判定策略（已确认）

配置检查 + 会话内首次探测缓存：

- **configured**：基于 `get_user_llm_config()`（用户 `user_llm_config` 表 OR 全局 env 回退），比现有 `GET /api/profile/llm` 只查用户行更准确。
- **connected**：最小 LLM 探测（`max_tokens=1` 的 chat completion，验证模型真实可用，比 `/v1/models` 更可靠），结果按 `user_id + 配置指纹(api_key/base_url/model)` 缓存 **120 秒**（后端内存 dict）。`?probe=1` 强制刷新。
- 配置变更（PUT/DELETE `/api/profile/llm`）时清除探测缓存（与现有 `clear_user_client_cache` 同位置）。
- 前端侧额外做 60 秒本地缓存，避免每次点击都请求。

## 后端

### `services/llm.py` 新增 `check_llm_status(user_id, force_probe=False) -> dict`

返回 `{ configured, connected, error, using_global, model }`：

- `configured`：`get_user_llm_config()` 有值且 key/base_url/model 完整。
- `connected`：缓存命中直接返回；未命中则用 `get_llm_client_for_user` 发最小 chat completion（`max_tokens=1`，prompt "ping"），成功为 True，异常为 False + `error` 摘要（鉴权/连接/超时区分）。
- 探测失败也缓存（TTL 120s），避免每次点击重复探测。
- 探测用 `asyncio.shield`/超时控制，整体不拖慢点击（非强探场景）。

### `routers/profile_pkg/llm.py` 新增 `GET /api/profile/llm/status`

`?probe=1` 强制重新探测。返回上述 dict。

## 前端

### `services/profileApi.js`

```js
export const fetchLLMStatus = (opts = {}) => get(`${API}/profile/llm/status`, opts.probe ? '?probe=1' : '')
```

### 新 composable `composables/useModelGuard.js`

- `modelStatus`：模块级 ref 缓存 `{ configured, connected, error }`，TTL 60s。
- `ensureModelReady({ action }) -> Promise<boolean>`：
  - 未配置 → false + 弹 Dialog「请先配置 AI 模型」→ 去设置按钮跳 `/settings?section=ai`
  - 已配置但未探测 → 触发探测；失败 → false + 弹 Dialog「模型连接失败: 原因」
  - 就绪 → true
- `invalidateModelStatus()`：设置页保存/清除配置后调用，清缓存并重新加载。
- Dialog：新组件 `components/business/ModelGuardDialog.vue`（复用 useConfirm 同款全局弹窗模式，由 AuthenticatedLayout 挂载），主按钮「去配置」→ `router.push({ name: 'settings', query: { section: 'ai' } })`，取消 = 中止操作。
- preview 模式（`route.query.preview === '1'`）跳过守卫。

### 设置页

- `SettingsPage.vue`：`activeSection` 初始化为 `route.query.section`（支持 `?section=ai`），并 watch query 变化。
- `SettingsAIConfig.vue`：新增「测试连接」按钮（调 `fetchLLMStatus({ probe: true })`），保存/清除后调用 `invalidateModelStatus()`。

## 接入点（点击前拦截，全部 await ensureModelReady 后再发起请求）

| 入口 | 位置 |
|---|---|
| Chat 发消息/重新生成 | `ChatView.vue` `handleSend`（preview 跳过） |
| 题库 AI 答案（管理员） | `useQuestionOps.js` `generateAnswer` |
| 刷题 AI 答案/自测评估 | `usePractice.js` `generateAnswerForQuestion` + `evaluateAnswer` |
| 手撕代码 提示/评审/AI 导入 | `CodingPractice.vue` `submitCode` + 导入 |
| JD/面经提交解析 | `StagingPanel.vue` 提交 |
| 题库重建 | `useBuildTrigger.js` build 触发 |
| 模拟面试评估 | `MockInterview.vue` 评估/自测 |
| 管理员批量生成/聚类/合并 | `useBatchActions.js` / `AdminReview.vue` / `useMergeDialog.js` 中 LLM 动作 |

## 测试

- 后端：`tests/services/test_llm_status.py` — 未配置 / 探测成功 / 401 鉴权失败 / 超时 / 缓存命中 / force probe / 配置变更清缓存；路由测试 `GET /api/profile/llm/status`。
- 前端：`npm run build` + smoke（Playwright mock API）。
- 门禁：`./deploy/docker-deploy.sh check`。

## 文档更新

- `frontend/CLAUDE.md`：composable 清单 + 代码路由表。
- `backend/CLAUDE.md`：services/llm.py 职责。
- 根 `CLAUDE.md`：测试命令不变。
