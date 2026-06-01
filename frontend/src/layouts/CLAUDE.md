# Layouts — 布局组件

页面布局包装器，通过 `<slot />` 渲染子内容。

## 文件清单

| 文件 | 职责 |
|------|------|
| `DefaultLayout.vue` | 默认布局：`min-h-screen` + 背景色（支持 light/dark） |
| `BlankLayout.vue` | 空白布局：纯 `<slot />`，无样式包装 |

## 核心规则

- 布局组件只负责页面骨架，不包含业务逻辑
- 使用 Tailwind CSS 的 `surface-*` 色系保持主题一致
- 新增布局时保持简洁，只做布局框架
- 当前项目主要使用 DefaultLayout，BlankLayout 用于特殊页面（如全屏预览）

## 修改后必做

1. 新增布局后更新本文件
