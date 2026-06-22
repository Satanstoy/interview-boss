# 2026-06-22 Chat Tools Gateway 与题目计划绑定实现

## 变更摘要

- 新增 `backend/app/agents/chat/tool_gateway.py`，统一 chat tools 的输入校验、题目 item 规范化、成功/失败 envelope。
- `search_questions` / `draw_questions` 返回 `ok/items/metadata/error` 结构，同时保持 legacy state：`retrieved_questions`、`candidate_questions`、`question_source`。
- ReAct loop 支持 envelope 解析、trace summary、tool result top-3 裁剪。
- 出新题场景新增 `next_question_plan`：本地选择 `selected_question`、注入生成约束、生成后做 adherence 校验。
- 偏离计划时触发一次 repair；repair 仍失败时使用确定性 fallback。
- metadata 优先使用计划绑定的 `selected_question`。

## 测试命令

```bash
DEPLOY_MIN_FREE_MB=2048 ./deploy/docker-deploy.sh test -k TestToolGatewayModels -q
DEPLOY_MIN_FREE_MB=2048 ./deploy/docker-deploy.sh test -k 'TestExecuteToolSearchQuestions or TestExecuteToolDrawQuestions' -q -o asyncio_mode=auto
DEPLOY_MIN_FREE_MB=2048 ./deploy/docker-deploy.sh test -k 'test_tools or test_react_loop' -q -o asyncio_mode=auto
```

## 测试环境说明

- 当前根分区可用空间低于部署脚本默认 4096MB 构建阈值，已按用户确认使用 `DEPLOY_MIN_FREE_MB=2048` 跑测试。
- `test-runtime` 镜像未复制根目录 `pyproject.toml`，因此 pytest 需要显式传 `-o asyncio_mode=auto` 才能运行 async tests。

## README 检查

本次未新增 API、路由、数据库迁移、环境变量、前端入口或部署方式，通常不需要更新 README。
