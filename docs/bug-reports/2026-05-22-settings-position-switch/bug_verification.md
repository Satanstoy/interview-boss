# Bug 验证报告

**Bug ID:** BUG-001, BUG-002, BUG-003
**验证日期:** 2026-05-22

## 可追溯性矩阵

| Bug ID | Bug 描述 | 关键代码位置 | 测试验证方式 |
|--------|---------|-------------|------------|
| BUG-001 | 点击岗位按钮立即调用后端 API | `SettingsPanel.vue:532-539` | 手动验证：DevTools Network 面板无 PUT 请求 |
| BUG-002 | 保存后 loadAllData 被调用两次 | `App.vue:889` + `SettingsPanel.vue:783-787` | 手动验证：Network 面板只出现一组数据请求 |
| BUG-003 | A→B→A 切换后缓存返回旧数据 | `http.js:23-36` + `SettingsPanel.vue:560` | 手动验证：快速切换后保存，页面显示最后选择的岗位 |

## 覆盖率检查

三个 bug 的根因分布在三个文件中：
- `SettingsPanel.vue` — onSwitchPosition 和 saveProfile 逻辑
- `App.vue` — 事件处理函数
- `profileApi.js` — API 函数参数透传

所有三个文件均在修复计划中覆盖。

## 测试结果预测

### 修复前

| Bug | 修复前行为 | 修复后行为 |
|-----|----------|----------|
| BUG-001 | 点击岗位 → PUT 请求发出 → toast 成功 | 点击岗位 → 仅本地状态更新，无 API 请求 |
| BUG-002 | 保存 → loadAllData × 2 | 保存 → loadAllData × 1 |
| BUG-003 | A→B→A → 保存 → 页面显示 B | A→B→A → 保存 → 页面显示 A |

## 修复前后对比验证清单

- [ ] **BUG-001**: 点击岗位按钮，DevTools Network 面板无 `PUT /api/profile/position` 或 `PUT /api/profile/my-position`
- [ ] **BUG-001**: 点击岗位按钮，无 toast 提示
- [ ] **BUG-001**: 点击岗位按钮后，本地分类预览正确更新
- [ ] **BUG-002**: 保存配置后，Network 面板中 loadAllData 相关请求只出现一次
- [ ] **BUG-002**: 取消修改（点关闭），不触发数据刷新
- [ ] **BUG-003**: A→B→A 快速切换后保存，页面显示 A
- [ ] **BUG-003**: DevTools 验证 fetchPublicProfile 请求在 onSwitchPosition 期间绕过了缓存
- [ ] **回归**: 管理员和普通用户两种角色均正常工作
- [ ] **回归**: 新增岗位、删除岗位功能不受影响
