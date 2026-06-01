# Bug 验证报告

**Bug ID:** BUG-001, BUG-002, BUG-003
**验证日期:** 2026-05-22

## 可追溯性矩阵

| Bug ID | Bug 描述 | 修改文件 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | PDF 提取缺少 Authorization 头 | NewChatModal.vue | ✅ 已修复 |
| BUG-002 | SSE retrieved 事件静默失败 | ChatView.vue | ✅ 已修复 |
| BUG-003 | api/index.js 缺少 chat re-export | api/index.js | ✅ 已修复 |

## 覆盖率检查

✅ **100% 已识别 bug 已覆盖**

## 验证方法

### BUG-001 验证
- **修复前:** `extractPdfText()` 使用原生 `fetch()` 无 Authorization header → 后端返回 401
- **修复后:** 使用 `http.js` 的 `upload()` 函数 → 自动携带 Authorization header → 后端返回 200 + 提取文本
- **验证:** 浏览器 Network 面板确认 `/api/chat/extract-pdf` 请求包含 `Authorization: Bearer <token>` 头

### BUG-002 验证
- **修复前:** `streamingContent.value._retrieved = [...]` 在字符串上赋值 → 静默失败
- **修复后:** 使用独立的 `pendingRetrievedQuestions` ref 存储 → metadata 正确包含 `retrieved_questions`
- **验证:** Vue DevTools 检查 messages 数组中最新 assistant message 的 metadata

### BUG-003 验证
- **修复前:** `api/index.js` 不包含 chat 模块的导出
- **修复后:** 包含 10 个 chat 函数的 re-export
- **验证:** `grep 'chatApi' frontend/src/api/index.js` 确认存在

## 前端构建验证

```
✓ built in 13.01s
```

前端构建成功，无编译错误。

## 后端测试

后端 464 passed / 71 failed（均为历史遗留失败，与本次前端修改无关）。
