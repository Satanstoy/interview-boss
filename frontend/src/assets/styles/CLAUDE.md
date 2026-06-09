# Styles — 全局样式

CSS 变量、重置、全局样式 + Tailwind。

## 文件职责

| 文件 | 职责 |
|------|------|
| `variables.css` | CSS 变量定义（颜色、间距、字体、阴影） |
| `reset.css` | 浏览器样式重置 |
| `global.css` | 全局样式（动画、工具类、组件基础样式） |

## 核心规则

- Tailwind 配置在 `frontend/tailwind.config.js`，不要在这里重复定义
- 新增 CSS 变量先加到 `variables.css`，再在 Tailwind config 中引用
- `global.css` 中的工具类应与 Tailwind 互补，不要冲突
- 全局基础组件类遵循 shadcn-vue 方向：实色主按钮、细边框、低阴影、8px 左右圆角，避免品牌渐变覆盖数据型工作台气质。

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件
