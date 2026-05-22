# Utils — 纯工具函数

无副作用的纯函数，无业务依赖。

## 文件清单

| 文件 | 职责 |
|------|------|
| `http.js` | HTTP 工具函数（非 axios，纯 fetch 封装） |
| `markdown.js` | Markdown 渲染（marked + DOMPurify） |
| `validate.js` | 表单验证工具 |

## 核心规则

- 纯函数，无副作用，无状态
- 禁止 import services/ 或 composables/
- 禁止访问 DOM 或 Vue 实例

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件
