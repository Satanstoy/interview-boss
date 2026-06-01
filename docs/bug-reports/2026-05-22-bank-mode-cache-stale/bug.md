# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-22
**状态:** 已确认

## 问题概述
切换题库模式（公共/个人/混用）后，题库列表不更新。根本原因是 HTTP GET 请求的 TTL 缓存未在模式切换时清除。

## 根本原因分析

### BUG-001: 切换题库模式后 GET 缓存返回旧数据
- **位置:** `frontend/src/services/http.js:20-36`（缓存定义）+ `frontend/src/App.vue:957`（handleBankModeChanged）
- **症状:** 切换 bank_mode 后，题库列表显示上一次模式的数据，不会刷新
- **根因:** `http.js` 的 `get()` 函数维护了一个 URL→response 的 TTL 缓存（30秒）。`fetchMasterBank()` 的 URL 不包含 bank_mode（模式由服务端从 DB 读取），因此切换模式后 URL 不变，`get()` 返回缓存的旧响应
- **影响:** 题库模式切换功能完全失效；快速来回切换时，30秒内所有请求都命中缓存
- **严重程度:** P1

## 数据流分析

```
用户点击切换 → UserMenu.switchBankMode()
  → PUT /api/auth/bank-mode (更新 DB)
  → emit('bank-mode-changed')
  → App.vue handleBankModeChanged()
    → fetchTableData()
      → fetchMasterBank()
        → get('/api/master-bank?...')  ← 缓存命中，返回旧数据！
```

关键：URL `/api/master-bank?page=1&page_size=500&sort=frequency_desc&compact=true` 在模式切换前后完全一致，缓存无法区分。

## 复现步骤
1. 以管理员身份登录
2. 默认在公共题库模式，确认题目列表正常显示
3. 切换到个人题库模式 → **预期**：显示个人题目；**实际**：可能显示旧的公共题目数据（如果 30 秒内切换）
4. 切换回公共题库模式 → **预期**：显示公共题目；**实际**：显示缓存的个人题目数据或无数据

## 修复建议
在 `handleBankModeChanged` 中，调用 `fetchTableData()` 前清除 master-bank 相关的 GET 缓存。
