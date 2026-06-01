# 测试验证报告

**Bug ID:** BUG-001 ~ BUG-005 + 脏数据修复
**日期:** 2026-05-22
**状态:** ✅ 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 新增测试 | 9 个，全部通过 |
| 前端构建 | ✅ 成功 (20.41s) |
| 测试覆盖率 | BUG-001~005 ✅ |
| 脏数据修复 | ✅ 2 条记录已修正 |
| 修复状态 | ✅ 全部成功 |

## 2. 修复后测试结果

```
backend/tests/test_settings_position_switch.py
  TestPositionSwitchDBContract
    ✅ test_position_switch_updates_users_table
    ✅ test_position_switch_a_to_b_to_a
  TestTaxonomySaveContract
    ✅ test_save_taxonomy_for_position
    ✅ test_taxonomy_consistent_across_reads
  TestFrontendCodeContract
    ✅ test_profile_api_accepts_options
    ✅ test_on_switch_position_no_api_call
    ✅ test_save_profile_calls_switch_api
    ✅ test_save_profile_invalidates_cache
    ✅ test_on_settings_close_no_load_all_data

9 passed in 1.91s
```

## 3. 代码变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `frontend/src/components/business/SettingsPanel.vue` | 修改 | BUG-001: onSwitchPosition 不再调用后端 API; saveProfile 中添加 switchPosition/switchMyPosition + 全量缓存清除 |
| `frontend/src/App.vue` | 修改 | BUG-002: onSettingsClose 移除 loadAllData(); 新增 `__VUE_APP_READY__` 标记 |
| `frontend/src/services/profileApi.js` | 修改 | BUG-003: fetchProfile/fetchPublicProfile 透传 options 参数 |
| `frontend/src/main.js` | 修改 | BUG-005: 白屏检测等待 Vue 初始化完成再检测，增加检测延迟 |
| `backend/data/interview-boss.db` | 数据修复 | 脏数据: 2 条 `job_position='backend'` 修正为正确值 |

## 4. Bug 详细说明

### BUG-001: 点击岗位按钮立即生效
- **根因**: `onSwitchPosition` 立即调用 `switchPosition()` API
- **修复**: 移除 API 调用，仅本地更新；`saveProfile` 中统一提交

### BUG-002: 保存后双重刷新
- **根因**: `onSettingsClose` 和 `onPositionChanged` 都调用 `loadAllData()`
- **修复**: `onSettingsClose` 仅关闭 modal，不触发数据刷新

### BUG-003: A→B→A 切换后缓存返回旧数据
- **根因**: HTTP GET 缓存 30s TTL，`fetchPublicProfile` 返回旧岗位数据
- **修复**: `fetchProfile`/`fetchPublicProfile` 支持 `noCache` 选项

### BUG-004: 保存配置后页面不刷新
- **根因**: `saveProfile` 只清除 `/api/profile` 缓存，`loadAllData()` 中的 `fetchMasterBank`、`fetchAnalytics`、`fetchPracticeStats` 仍命中 30s 缓存
- **修复**: `saveProfile` 中 `invalidateCache()` 清除全部缓存（无参数 = 全量清除）

### BUG-005: 刷新页面导致用户被登出
- **根因**: `main.js` 中的 `detectBlankScreen()` 在 Vue `initAuth()` 完成前就开始检测，此时页面内容不足 100 字符，误判为白屏并调用 `location.reload()`。刷新后内存中的 access token 丢失，refresh token cookie 若过期则用户被登出
- **修复**:
  - `main.js`: 白屏检测器等待 `window.__VUE_APP_READY__` 标记，初始检测延迟从 1s 增加到 2s，重试间隔从 2s 增加到 3s
  - `App.vue`: `initAuth()` 完成后设置 `window.__VUE_APP_READY__ = true`

### 脏数据修复
- **问题**: `question_bank` 表中 2 条记录的 `job_position` 为 'backend'（应该是 'agent开发/大模型应用开发/大模型开发'）
- **修复**: 直接 UPDATE 修正为正确值

## 5. 测试覆盖矩阵

| Bug ID | Bug 描述 | 测试函数 | 修复前 | 修复后 |
|--------|---------|---------|--------|--------|
| BUG-001 | 点击岗位不调用后端 API | test_on_switch_position_no_api_call | ❌ | ✅ |
| BUG-001 | saveProfile 统一提交 | test_save_profile_calls_switch_api | ❌ | ✅ |
| BUG-002 | onSettingsClose 不刷新 | test_on_settings_close_no_load_all_data | ❌ | ✅ |
| BUG-003 | fetchProfile 支持 noCache | test_profile_api_accepts_options | ❌ | ✅ |
| BUG-003 | saveProfile 清除缓存 | test_save_profile_invalidates_cache | ❌ | ✅ |
| BUG-004 | 保存后全量缓存清除 | test_save_profile_invalidates_cache | — | ✅ |
| BUG-005 | 白屏检测等待 Vue 初始化 | (手动验证 main.js 代码) | — | ✅ |
| — | 数据库岗位切换 | test_position_switch_updates_users_table | — | ✅ |
| — | A→B→A 切换 | test_position_switch_a_to_b_to_a | — | ✅ |
| — | taxonomy 保存 | test_save_taxonomy_for_position | — | ✅ |
| — | taxonomy 一致性 | test_taxonomy_consistent_across_reads | — | ✅ |

## 6. 结论

- [x] BUG-001~005 全部修复
- [x] 脏数据已清理
- [x] 所有测试通过（9/9）
- [x] 前端构建成功
- [x] 代码可安全部署
