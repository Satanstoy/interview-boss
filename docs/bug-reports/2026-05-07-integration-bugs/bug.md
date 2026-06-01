# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-003
**发现日期:** 2026-05-07
**状态:** 已确认

## 问题概述

前后端 API 接口存在 3 个不匹配问题，涉及端点权限、响应格式和 API 函数缺失。

## 根本原因分析

### BUG-001: loadActiveSeason 调用管理员专属端点

- **位置:** `frontend/src/App.vue:964-968`
- **症状:** 非管理员用户打开页面后，招聘季筛选器始终为空
- **根因:** `loadActiveSeason()` 调用 `api.fetchProfile()`（`GET /api/profile`，仅管理员可访问）。非管理员收到 403 后被 `catch {}` 静默捕获，`activeSeason` 保持空字符串
- **影响:** 非管理员用户无法按招聘季筛选题目
- **严重程度:** P1 (High)

**问题代码:**
```javascript
// frontend/src/App.vue:964-968
const loadActiveSeason = async () => {
  try {
    const data = await api.fetchProfile()  // GET /api/profile — 仅管理员!
    activeSeason.value = data.settings?.active_season || ''
  } catch { /* ignore */ }
}
```

**后端对比:**
```python
# backend/app/routers/profile.py:106
@router.get("/api/profile")
async def get_profile(admin: dict = Depends(get_admin_user)):  # 仅管理员
    ...

# backend/app/routers/profile.py:52 — 已有公开端点
@router.get("/api/profile/public")
async def get_public_profile(user: dict = Depends(get_current_user)):  # 所有用户
    ...  # 返回 active_season
```

### BUG-002: buildMasterBank 使用 post() 请求 SSE 端点

- **位置:** `frontend/src/App.vue:906`
- **症状:** 管理员点击"重建题库"后，提示"重建完成，共 undefined 道题目"
- **根因:** `triggerBuildMasterBank()` 调用 `api.buildMasterBank()`，该函数使用 `post()`（普通 HTTP 请求）。但后端 `POST /api/master-bank/build` 返回 `StreamingResponse`（SSE 格式，`text/event-stream`）。`post()` 将 SSE 流作为纯文本返回，`data.total_unique` 为 `undefined`
- **影响:** 管理员无法看到题库重建的正确结果
- **严重程度:** P2 (Medium)

**问题代码:**
```javascript
// frontend/src/api/index.js:41
export const buildMasterBank = () => post(`${API}/master-bank/build`, null, { timeout: 600_000, noRetry: true })
// ↑ 使用 post()，后端返回 SSE 流

// frontend/src/api/index.js:42 — 已有 SSE 版本但未使用
export const buildMasterBankSSE = (onEvent) => postSSE(`${API}/master-bank/build`, null, onEvent)
```

```javascript
// frontend/src/App.vue:906
const data = await api.buildMasterBank()  // 应使用 buildMasterBankSSE
toast.success(`重建完成，共 ${data.total_unique} 道题目`)  // data 是纯文本，total_unique 为 undefined
```

**后端对比:**
```python
# backend/app/routers/master_bank.py:146-349
async def build_master_bank(admin: dict = Depends(get_admin_user)):
    async def event_stream():
        ...
        yield f"data: {json.dumps({'type': 'done', 'total_unique': len(cluster_details), 'restored': restored})}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

### BUG-003: 前端缺少 fetchPublicProfile API 函数

- **位置:** `frontend/src/api/index.js`
- **症状:** 非管理员用户无法获取公开配置（岗位列表、招聘季等）
- **根因:** 后端已有 `GET /api/profile/public` 端点，但前端 `api/index.js` 中未定义对应的 API 函数
- **影响:** 非管理员用户缺少公开配置数据
- **严重程度:** P2 (Medium)

**后端已有端点:**
```python
# backend/app/routers/profile.py:52
@router.get("/api/profile/public")
async def get_public_profile(user: dict = Depends(get_current_user)):
    """公开配置（普通用户可访问）：岗位列表、分类配置、招聘季"""
    return {
        "settings": {
            "current_job_position": ...,
            "available_positions": [...],
            "taxonomy_config": "...",
            "active_season": "...",
        },
        "available_seasons": [...],
    }
```

## 复现步骤

### BUG-001
1. 以非管理员用户登录
2. 打开页面，查看招聘季筛选器
3. 预期：显示可用的招聘季列表
4. 实际：筛选器为空

### BUG-002
1. 以管理员用户登录
2. 点击"重建题库"按钮
3. 等待重建完成
4. 预期：提示"重建完成，共 X 道题目"
5. 实际：提示"重建完成，共 undefined 道题目"

### BUG-003
1. 以非管理员用户登录
2. 查看网络请求
3. 预期：调用 `GET /api/profile/public`
4. 实际：调用 `GET /api/profile`（返回 403）

## 修复建议

| Bug ID | 修复方向 |
|--------|---------|
| BUG-001 | `loadActiveSeason` 改用 `fetchPublicProfile()` |
| BUG-002 | `triggerBuildMasterBank` 改用 `buildMasterBankSSE()` |
| BUG-003 | 在 `api/index.js` 中添加 `fetchPublicProfile` 函数 |
