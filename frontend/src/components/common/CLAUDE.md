# Common Components — 通用 UI 组件

无业务依赖的可复用 UI 组件。

## 组件清单

| 组件 | 职责 |
|------|------|
| `AppCard.vue` | 卡片容器（title/description/content/footer 卡槽，noPadding/hover props） |
| `AppDialog.vue` | 弹窗封装（open/title/description/maxWidth/size props，footer 卡槽） |
| `AppEmpty.vue` | 空状态展示（title/description/icon props，icon 卡槽可覆盖） |
| `AppLoading.vue` | 加载状态（type: spinner/page/skeleton/cards/table，rows/gridCols props） |
| `AppPage.vue` | 页面容器（title/description/actions 卡槽，showBackButton/backTo props） |
| `AppPageHeader.vue` | 页面头（breadcrumbs/title/description/actions 卡槽，back 按钮） |
| `AppSearchForm.vue` | 搜索表单（modelValue/placeholder props，filters 卡槽） |
| `AppTable.vue` | 数据表格（columns/rows/loading/emptyText props，cell 卡槽） |
| `BaseModal.vue` | 通用弹窗（动画、遮罩、关闭） |
| `BatchActionPanel.vue` | 批量操作栏 |
| `ConfirmDialog.vue` | 确认对话框 |
| `DataTable.vue` | 数据表格（排序、分页） |
| `InlineEdit.vue` | 行内编辑 |
| `PaginationBar.vue` | 分页栏 |
| `RoundedSelect.vue` | 圆角下拉选择 |
| `TabBar.vue` | Tab 导航栏 |

## 核心规则

- **禁止业务依赖**：不能 import services/、composables/use*、或任何业务 API
- **Props 驱动**：通过 props 接收数据，通过 emit 向外通信
- **可复用**：组件应该能在不同页面/场景中复用
- **视觉基线**：通用表格、按钮、Tab、分页优先保持 shadcn-vue 式细边框、低阴影、紧凑密度和明确 hover/selected 状态。

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件（如新增组件）
