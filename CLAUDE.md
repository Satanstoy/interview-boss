# InterviewBoss Monorepo

中文 AI 面试备战平台。JD/面经 → 提取面试题 → LLM 分类打标聚类 → 口述级答案 + 模拟面试 + 知识图谱。

## 目录

- `backend/` — Python FastAPI 后端（→ `backend/CLAUDE.md`）
- `frontend/` — Vue 3 + Vite 前端（→ `frontend/CLAUDE.md`）
- `deploy/` — 部署脚本和配置
- `docs/` — bug-reports、tdd-reports（历史经验库）

## 命令

```bash
./deploy/deploy.sh              # 全量部署
./deploy/deploy.sh frontend     # 仅前端
./deploy/deploy.sh backend      # 仅后端
./deploy/docker-deploy.sh       # Docker 部署
```

Python 依赖必须用 uv（`/root/.local/bin/uv`），禁止 pip。

## 核心规范

- **TDD 原则（强制）**：修 Bug 或开发新功能时，必须**先写测试 → 确认测试失败 → 写最少代码让测试通过 → 重构**。详见 `backend/CLAUDE.md` 和 `frontend/CLAUDE.md` 的测试规则。
- **Commit**：Conventional Commits（`feat(frontend):`、`fix(backend):`），英文
- **语言**：UI/提示词/文档中文简体，代码标识符英文
- **禁止**：根目录装包、跨包引用源码、`--force`/`--no-verify`

## 代码路由表（快速定位文件）

修改功能时，按此表直接找到对应文件，不要盲目搜索：

| 功能 | 后端文件 | 前端文件 |
|------|---------|---------|
| 登录/注册/刷新 | `backend/app/routers/auth.py` + `core/auth.py` | `frontend/src/services/authApi.js` + `components/business/LoginModal.vue` |
| JD/面经提交 | `backend/app/routers/submit.py` + `services/pipeline.py` | `frontend/src/services/dataApi.js` |
| 题库管理 | `backend/app/routers/master_bank.py` | `frontend/src/services/masterBankApi.js` + `components/business/MasterBankList.vue` |
| 答案生成 | `backend/app/routers/answers.py` + `services/llm.py` | `frontend/src/services/practiceApi.js` |
| 练习/模拟面试 | `backend/app/routers/practice.py` + `routers/interview.py` | `frontend/src/components/business/PracticePanel.vue` + `MockInterview.vue` |
| 数据分析 | `backend/app/routers/analytics.py` | `frontend/src/services/analyticsApi.js` + `components/business/AnalyticsSidebar.vue` |
| 用户配置 | `backend/app/routers/profile.py` + `core/config.py` | `frontend/src/services/profileApi.js` + `components/business/SettingsPanel.vue` |
| 题目去重 | `backend/app/services/clustering.py` | — |
| LLM 调用 | `backend/app/services/llm.py` + `core/prompts.py` | — |
| 认证中间件 | `backend/app/core/auth.py` | `frontend/src/services/http.js` |
| 数据库操作 | `backend/app/db/operations.py` + `queries.py` | — |

## Docs（历史经验库）

`docs/bug-reports/` 和 `docs/tdd-reports/` 存放了 20+ 份历史文档。

**修 Bug 前：** 先搜 `docs/bug-reports/` 是否有类似问题的历史记录，避免重复踩坑。
**开发新功能前：** 先搜 `docs/tdd-reports/` 了解相关模块的历史设计决策和已有模式。

## 完成阶段后

1. `uv run pytest backend/tests/ -q` → `cd frontend && npm run build` → `./deploy/docker-deploy.sh`
2. 涉及功能/API/结构变更 → 最小化更新 README.md
3. **创建 docs 记录**（关键修改：README + docs；小修改：仅 docs）
   - `docs/bug-reports/YYYY-MM-DD-描述.md` / `docs/tdd-reports/YYYY-MM-DD-描述.md`
   - 内容：问题描述、根因分析、修复方案、测试验证、影响范围
4. `git add` + `git commit` → `git push`（让用户输入凭据）

## 生产环境

Nginx 反代 `/api/` → uvicorn:8000（180s 超时）；前端 `/var/www/interview-boss/dist/`。`claude_runner` 已配置 NOPASSWD。
