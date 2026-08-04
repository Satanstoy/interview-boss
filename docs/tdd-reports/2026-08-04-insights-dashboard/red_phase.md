# RED 阶段记录

## 预期失败

测试先于实现添加，当前预期失败原因是：

- `app.services.insights` 尚不存在；
- `/api/insights` 尚未注册；
- 前端尚无洞察三 Tab 路由、视图和 API 调用。

运行命令与实际结果将在 RED 阶段执行后补充。

## 实际结果

- 后端：`docker compose --profile test run --rm test uv run pytest backend/tests/services/test_insights.py -q` → 3 failed。失败分别对应 `app.services.insights` 缺失，以及 `/api/insights` 返回 404。
- 前端：`cd frontend && npx playwright test tests/e2e/insights.spec.js` → 1 failed。页面尚未接入洞察路由，找不到“洞察总览”标题。

失败原因与测试预期一致，进入 GREEN。
