# GREEN 阶段记录

## 实现内容

- 新增 `backend/app/services/insights.py`，统一聚合当前用户当前岗位的题库、JD、面经、练习和模拟面试会话事实。
- 新增认证接口 `GET /api/insights`，并在 `backend/app/asgi.py` 注册。
- 新增 `frontend/src/services/insightsApi.js` 和 `useInsightsData.js`。
- 新增 `InsightsView.vue` 及总览、岗位准备度、面试复盘三个业务组件。
- 侧栏增加三个洞察 Tab，旧 `/knowledge-graph` 重定向到岗位准备度的图谱辅助视图。

## 验证

- 后端定向测试：3 passed。
- 前端洞察 Playwright：1 passed（随后增加旧图谱兼容测试后为 2 passed）。
- 前端生产构建：`npm run build` passed。
