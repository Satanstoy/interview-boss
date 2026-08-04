# 洞察工作台 MVP 实施计划

## 目标

以 TDD 实现洞察工作台的三个 Tab：总览、岗位准备度、面试复盘，并保留知识图谱兼容入口。

## 实施顺序

1. **Spec 与测试契约**
   - 固化 API 返回结构、状态计算和路由信息；
   - 编写后端 service/API 测试和前端 Playwright mock 测试；
   - 运行测试确认 RED。
2. **后端 Green**
   - 新增 `app/services/insights.py` 聚合当前用户/岗位事实；
   - 新增 `app/routers/insights.py` 和 `/api/insights`；
   - 注册路由；
   - 运行定向后端测试。
3. **前端 Green**
   - 新增 `insightsApi.js`、`useInsightsData.js`；
   - 新增 `InsightsView.vue` 与三个业务组件；
   - 更新路由、侧栏、兼容重定向；
   - 运行 Playwright 定向测试和构建。
4. **Refactor 与门禁**
   - 检查用户/岗位隔离、空数据文案、移动布局和链接；
   - 更新各目录 `CLAUDE.md`、TDD 记录；
   - 跑项目质量门禁中可用的后端和前端检查。

## 不在本次实现

- 练习评分写入链路改造；
- 复习间隔算法；
- 新的知识图谱算法；
- LLM 生成式洞察。
