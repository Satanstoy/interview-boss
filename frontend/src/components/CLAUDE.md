# Components — 组件目录

> 位置：`frontend/src/components/` | 上游：`App.vue`, composables | 下游：`services/` 调用 API
> 职责：Vue 组件，分为通用组件和业务组件两个子目录。

## 子目录

- `common/` — 通用 UI 组件（DataTable、TabBar、AppDialog、ConfirmDialog 等），无业务依赖
- `business/` — 业务组件（MasterBankList、PracticePanel、SettingsPage 等）
- `ui/` — shadcn-vue 原始组件封装（button/card/dialog/sidebar/tooltip 等）

## 规则

- 通用组件禁止导入 `services/` 或 `composables/` 中的业务模块
- 业务组件优先通过 composables 获取共享数据；局部业务动作可以调用 `services/` 或兼容层 `api/index.js`，但禁止直接 `fetch`
- 组件规范见 `.claude/rules/vue-components.md`（编辑 Vue 文件时自动加载）
- 侧边栏品牌标识统一使用现有方形 favicon 资源 `/favicon-b.png`，不要再用文字 `IB` 或蓝色背景包裹作为主 logo。
