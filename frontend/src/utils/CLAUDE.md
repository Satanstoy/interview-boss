# Utils — 纯工具函数

无副作用的纯函数，无业务依赖。

## 文件清单

| 文件 | 职责 |
|------|------|
| `highlight.js` | 关键词/文本高亮工具 |
| `http.js` | HTTP 工具函数（非 axios，纯 fetch 封装） |
| `logger.js` | 前端日志与错误上报到 `/api/error-report` |
| `markdown.js` | Markdown 渲染（marked + DOMPurify） |
| `validate.js` | 表单验证工具 |

## 核心规则

- 纯函数，无副作用，无状态
- 禁止 import services/ 或 composables/
- 工具函数默认不访问 Vue 实例；确需访问浏览器 API 时保持封装清晰并可测试

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件
