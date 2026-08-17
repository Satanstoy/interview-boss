# Secret rotation runbook

本 runbook 只描述操作流程，不包含任何真实凭据。生产环境的密钥轮换应由有权限的运维人员执行，并在变更记录中记录时间、操作者、影响范围和验证结果。

## 范围

需要纳入轮换的凭据包括：

- `SILICONFLOW_API_KEY` 或其他第三方 LLM provider key；
- OAuth client secret；
- `JWT_SECRET_KEY`；
- `ADMIN_PASSWORD`；
- 部署平台、Redis、数据库和监控系统使用的同类凭据。

## 轮换前

1. 确认当前部署、发布窗口和回滚负责人；不要在 issue、聊天或 shell 历史中粘贴 secret。
2. 在数据库变更前先执行整库备份，并确认备份可读：

   ```bash
   ./deploy/docker-deploy.sh backup
   ```

3. 生成轮换值：`ADMIN_PASSWORD` 需要配置且保持可用，`JWT_SECRET_KEY` 和 OAuth/第三方 key 至少 32 个字符；使用密码管理器或 secret manager 保存。
4. 检查仓库工作树和当前部署配置，确认新值只会通过环境变量或 secret manager 注入：

   ```bash
   python3 backend/scripts/check_secrets.py
   git grep -n -I -E 'sk-[A-Za-z0-9]|SILICONFLOW_API_KEY\s*=' -- ':!uv.lock' || true
   ```

## 执行轮换

1. 在 provider/OAuth 控制台创建新凭据，并验证新凭据的权限范围尽可能小。
2. 将新值写入生产 secret manager 或部署环境变量，保留旧值一小段受控重叠窗口，仅用于回滚。
3. 重启或滚动重启依赖服务，使新环境变量生效。
4. 对第三方 key 做一次最小权限健康检查；确认 chat、评测 worker 和管理端登录均使用新配置。
5. 确认没有错误率、401/403、队列积压或 worker heartbeat 异常后，立即在 provider/OAuth 控制台撤销旧凭据。

JWT secret 和管理员密码会使既有会话或登录状态失效。轮换后应验证：新管理员密码可登录、旧密码不可登录、旧 JWT 不再被接受，并通知用户重新登录（如适用）。

## 历史泄露处理

如果 secret 曾经进入 Git 历史，先完成 provider 侧撤销/轮换，再清理历史。历史重写会影响所有协作者，必须单独审批；不要在部署脚本或自动化任务中执行：

```bash
git filter-repo --sensitive-data-removal \
  --replace-text /path/to/replacements.txt
gitleaks git --log-opts="--all" --redact
```

历史清理后需要强制所有协作者重新克隆或按批准流程同步重写后的分支；禁止未经确认的 force-push。清理只降低再次暴露风险，不能替代撤销旧凭据。

## 验证

```bash
python3 backend/scripts/check_secrets.py
docker compose config --quiet
docker compose up -d backend
docker compose logs --tail=100 backend
```

验证结果至少应包括：服务启动成功、生产 secret policy 没有报错、LLM 调用正常、管理端认证正常、eval worker 心跳恢复、Redis/数据库连接正常。不要把环境变量值或完整请求头写入日志。

## 回滚

1. 如果新凭据导致服务异常，在旧凭据仍处于受控重叠窗口时恢复上一个已验证的 secret 版本。
2. 重启受影响服务并重复“验证”章节；确认队列任务、登录和 LLM 调用恢复。
3. 若旧凭据已撤销，不要恢复被撤销的值；应在 provider 侧重新签发一个新值，并重新执行本流程。
4. 记录失败原因和影响范围，修复配置后再次轮换并撤销所有失效值。
