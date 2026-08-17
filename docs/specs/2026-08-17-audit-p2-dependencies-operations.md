# Tech Audit P2：依赖、构建复现与运维闭环

> 日期：2026-08-17
> 前置：P1 gate 已具备可阻断能力
> 原则：依赖升级必须先锁版本、跑兼容性测试和 audit；运维改动必须有 dry-run 或结构测试。

## 目标

清理 npm/Python 依赖漏洞，统一运行时版本和镜像来源，补齐健康检查、备份轮转、cron 监控和运维手册。

## Task P2-A：依赖漏洞和版本统一

**Files**

- Modify: `frontend/package.json`、`frontend/package-lock.json`、`pyproject.toml`、`uv.lock`
- Create: `.github/dependabot.yml`
- Test: `frontend/tests/smoke/dependency-contract.spec.js`、`backend/tests/infra/test_dependency_contract.py`

- [ ] RED：测试锁文件存在、Node/Python 版本声明一致、生产依赖没有已知 high/critical 漏洞。
- [ ] GREEN：升级受影响 npm/Python 包，删除未使用生产依赖，升级 Vite；提交锁文件。
- [ ] GREEN：统一 Docker、CI、`.python-version` 和 package engines 的 Node/Python 版本。
- [ ] REFACTOR：增加 Dependabot weekly 更新和安全更新分组。

**Done when**：`npm audit --omit=dev` 与 `pip-audit` 达到项目定义阈值；构建、后端结构测试、关键 API 测试全部通过。

## Task P2-B：可复现镜像与 setup

**Files**

- Modify: `Dockerfile`、`oauth-gateway/Dockerfile`、`docker-compose.yml`、`backend/.env.example`
- Test: `backend/tests/infra/test_docker_config.py`、`backend/tests/infra/test_env_example.py`

- [ ] RED：测试镜像基础 image 有 digest、env example 覆盖代码支持的配置、HF cache 不依赖固定用户目录。
- [ ] GREEN：记录并 pin 基础镜像 digest；补齐可选 env、默认值、敏感性说明；改用项目/XDG cache 路径。
- [ ] REFACTOR：将镜像 digest、Node/Python 版本和配置表集中到可审查文档。

**Done when**：fresh clone 按 README 可以完成 build/compose config；换用户和机器不依赖 `/home/ubuntu`。

## Task P2-C：健康检查、cron 观测和备份轮转

**Files**

- Modify: `backend/app/routers/health.py`、`docker-compose.yml`、`backend/app/worker.py`、`deploy/docker-deploy.sh`
- Test: `backend/tests/infra/test_health_contract.py`、`backend/tests/services/test_worker_observability.py`、`backend/tests/infra/test_backup_retention.py`

- [ ] RED：Redis/worker 不可用时 readiness 失败；nginx/oauth-gateway 无探针时结构测试失败；超出保留期备份可被 dry-run 识别。
- [ ] GREEN：区分 liveness/readiness；增加 Redis ping、worker heartbeat、nginx/OAuth healthcheck；实现备份保留期、容量告警和 dry-run。
- [ ] REFACTOR：备份路径、保留天数和容量阈值均由配置提供，日志不暴露 secret。

**Done when**：故障能在健康检查或诊断输出中被发现；cleanup 不影响其他项目；备份恢复演练有记录。

## Task P2-D：运维 runbook

**Files**

- Create: `docs/runbooks/operations.md`
- Create: `docs/runbooks/database-restore.md`
- Create: `docs/runbooks/dependency-response.md`

- [ ] RED：runbook 检查脚本验证所有必须场景和命令存在：DB down、LLM 5xx、quota、disk full、OOM、worker offline、restore rollback。
- [ ] GREEN：补充检测、止损、恢复、验证、升级和责任人步骤。
- [ ] REFACTOR：链接到 deploy 命令、health endpoint、备份校验和审计报告。

**Done when**：新运维者可以按文档完成一次 dry-run 和一次恢复演练，且所有破坏性命令有确认和备份前置。

## P2 验证命令

```bash
docker compose config --quiet
docker build --target app-runtime .
docker build -f oauth-gateway/Dockerfile oauth-gateway
cd frontend && npm audit --omit=dev && npm run build
uv export --frozen --no-dev --format requirements-txt --no-hashes -o /tmp/requirements-audit.txt
uv run pip-audit -r /tmp/requirements-audit.txt --no-deps --disable-pip
```
