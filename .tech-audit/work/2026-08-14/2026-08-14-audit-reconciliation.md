# 全量 Audit 文档对账 — 2026-08-14

**对账方法**: 3 个并行 reconciliation subagent（security-fix-plan 40 / tech-audit-08-13 61 / tech-audit-08-14 104）逐一读当前代码验证 + 主 agent 交叉复核关键项。

## 一、各来源状态分布

| 来源 | FIXED | MITIGATED | STILL-OPEN | NEEDS-VERIFICATION |
|---|---|---|---|---|
| security-fix-plan-08-05（40） | 11 | 11 | 18 | 0 |
| tech-audit-08-13（61） | 14 | 7 | 38 | 2 |
| tech-audit-08-14（104） | 27 | 17 | 58 | 2 |

## 二、已确认 FIXED（真正落地）

- 安全/密钥：SiliconFlow key 改读 env（历史仍需轮换）；CI+secret 扫描（check_secrets 修复）；JWT_SECRET/OAUTH 占位注释化+oauth-gateway fail-closed；users.email 唯一索引(079)；sqlite .backup 备份；PROJECT_DIR 自定位；commit-msg hook；EOL 镜像；oauth-gateway 非 root；answers.py 异步+SSE
- 数据完整性（migration 081-086）：FK 孤儿清理+foreign_key_check；FTS 重建+sync triggers；重复索引删除；时间戳归一+error 列移除+available_at 哨兵；十二表 FK+username lower+taxonomy 唯一；死列删除；run_migrations 破坏性迁移自动备份；run_db_retention 每日清理
- 我的本轮交互层修复(e7f11b2)：限速 key→get_client_ip+asgi 全局默认；insights high_frequency owner 作用域；MCP token 出 sessionStorage；login-form 同源校验

## 三、关键「看似已修实为半修/静默失效」

1. **静态检查静默失效**：pyproject 有 [tool.ruff]/[tool.mypy]、frontend 有 eslint.config.js，但 scripts/check.sh:145-146 调用 run_static_backend/run_static_frontend 两个函数**整仓未定义** → bash command not found 静默跳过，ruff/eslint 实际没跑
2. **CI gate fresh-clone 必挂 + gitleaks 必红**：ci.yml 直接 check.sh all，fresh clone 无 node_modules + backend/.env 未入库；gitleaks 全史扫描因历史 key + test_secret_scan 真实字面量 + 无 .gitleaks.toml allowlist 而必红
3. **并发重复 email 注册 500**：migration 079 后竞态从重复账号→未捕获 IntegrityError→500（应 409）
4. **验证码双用竞态仍在**：verify_code 无 used=0 rowcount 门控；email 时间仍 naive

## 四、仍开放集群（STILL-OPEN）

**D4/D5 安全**：API key 明文落库无 Fernet；python-jose/passlib 弃维护；LLM 无 per-user 配额；admin 弱口令；动态频率 SQL/practice_deck difficulty f-string 插值
**D14 正确性**：复习提交无幂等键；并发注册 IntegrityError→500；verify_code 双用/ login_failures SELECT-then-INSERT 竞态；FTS IDF 缓存；email 时间 naive；聚类代表题统一 COMMIT 后异步
**D8 工程化**：CI fresh-clone 依赖引导；gitleaks 历史清洗；门禁只跑子集；无真实全栈 E2E；commit-msg 无安装脚本
**D9 数据完整性(14)**：test 挂生产 data 卷；软删读路径漏过滤×4；JD 批量删/restore owner 限定不完整；任务持久化碎片化；备份同盘 SPOF；owner_id 无 ON DELETE
**D3/D6/D7/D11/D15**：无 real-Redis 集成/无 fuzz/coding 测试薄/测试含真实 key 字面量；worker/nginx/oauth 无 healthcheck/无 restore/runbook 缺失/cron 无可见性；Vite4 EOL/uvicorn 0.24 硬钉/无 Dependabot；隐私/账号删除/sub-processor/数据导出全缺失；window.confirm/AppTooltip 触点无文本

## 五、MITIGATED 代表
- OTP 标记原子化（_mark_code_used UPDATE used=1，但 verify_code 返回未按 rowcount 门控）；MCP query 参数（遗留 fallback 仍接受但主路径 fail-closed）；nodes prompt 已移出（仍 2028 行）；chartTokens.js 建了但 2 组件仍内联；tsconfig 非 strict；init_db FK/迁移破坏性自动备份缓解

## 六、方法说明
- 每项读当前真实代码验证，非记忆；🟡 经代码路径复核；无法运行时标 NEEDS-VERIFICATION
- 离线产物：findings_08-14_reconciled.tsv（104 行+status 列）
