# Frontend lint warning register

基线日期：2026-08-26。`npm run lint` 当前为 0 errors / 38 warnings，并以
`--max-warnings=38` 作为 blocking budget：新增 warning 会使门禁失败。

责任人：frontend-maintainers。整改期限：2026-09-30。修复一项后删除对应编号，
并同步降低 `frontend/package.json` 中的 warning budget；禁止通过上调 budget 消除新告警。

| 编号 | 位置 | 处理范围 |
|---|---|---|
| W01 | `components/AppSidebar.vue` | 移除未使用回调 |
| W02 | `components/DragHandle.vue` | 使用或移除 sortable |
| W03 | `components/SiteHeader.vue` | 移除未使用 props |
| W04-W05 | `components/business/AnalyticsSidebar.vue` | 收敛 props/emit |
| W06-W07 | `components/business/ChatView.vue` | 移除未使用图标 |
| W08 | `components/business/ExamDistribution.vue` | 收敛 emit |
| W09 | `components/business/InsightsOverview.vue` | 移除未使用 ref |
| W10 | `components/business/MasterBankList.vue` | 移除未使用 nextTick |
| W11 | `components/business/PracticeMode.vue` | 收敛异常变量 |
| W12 | `components/business/PracticeQuadChart.vue` | 移除未使用颜色变量 |
| W13 | `components/business/SettingsNav.vue` | 移除未使用 props |
| W14 | `components/business/SettingsProfile.vue` | 移除未使用 isDark |
| W15 | `components/common/AppPage.vue` | 移除未使用 props |
| W16 | `components/common/AppPageHeader.vue` | 移除未使用 props |
| W17 | `components/common/AppTable.vue` | 移除未使用 props |
| W18 | `components/ui/chart/ChartTooltipContent.vue` | 收敛未使用参数 |
| W19 | `composables/useAuth.js` | 移除未使用 invalidateCache |
| W20 | `composables/useBatchActions.js` | 收敛异常变量 |
| W21 | `composables/useHighlightNav.js` | 移除未使用函数 |
| W22 | `composables/useQuestionOps.js` | 收敛异常变量 |
| W23 | `composables/useSubmitJobs.js` | 移除未使用 job |
| W24-W33 | `layouts/AuthenticatedLayout.vue` | 清理未使用状态/回调 |
| W34 | `services/authApi.js` | 移除未使用 del |
| W35 | `services/dataApi.js` | 收敛未使用参数 |
| W36 | `utils/validate.js` | 收敛未使用字段名 |
| W37 | `views/ChatView.vue` | 移除未使用 KeepAlive |
| W38 | `views/MasterBankView.vue` | 移除未使用 total |

验证命令：`cd frontend && npm run lint`。
