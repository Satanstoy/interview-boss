# Key 轮换执行手册（audit round-3 D4，待用户提供新 key 后执行）

**状态（round 2 更新）**: 历史重写已在 /tmp/ib-rewrite（本地 mirror clone）执行并验证（旧 key 全历史 0 命中、8 个 REDACTED 标记、提交链完整），**尚未推送**；仍等用户新 key + 推送许可。git-filter-repo 2.47.0 已装好
（/home/ubuntu/.local/bin/git-filter-repo）；脱敏映射在 /tmp/interview-boss-redact.txt（含旧 key 值，禁止入库）。

## 泄漏事实（已复核）
- 旧 key（sk-hkaopkq...clym）出现在 8 个历史提交：95fcf63（最旧）、e6f4f0d、78c77d0、d6f70b0、c48260d、eb50a92、42cf667、a26aaf5（最新）
- 同一把 key 至今仍是 backend/.env:22 的 SILICONFLOW_API_KEY（活 key）
- 远端：origin = gitee（fetch）+ github（push）

## 步骤

### 1. 轮换（先做，让旧 key 立即失效）
1. 用户在 platform.siliconflow.cn 控制台生成新 key
2. 更新 backend/.env: SILICONFLOW_API_KEY=<新 key>
3. 重启生效：./deploy/docker-deploy.sh update（或 docker compose restart backend worker）
4. 验证：curl 一次 embedding/LLM 调用确认新 key 可用；控制台确认旧 key 已吊销

### 2. 历史脱敏（第二步，需用户确认 force-push）
```bash
cd /tmp && rm -rf interview-boss-redact-clone && git clone --mirror git@gitee.com:satanstoy/interview-boss.git interview-boss-redact-clone
cd interview-boss-redact-clone
export PATH="/home/ubuntu/.local/bin:$PATH"
git filter-repo --replace-text /tmp/interview-boss-redact.txt --force
git log --all -S 'sk-hkaopkqmnstce…' --oneline | head -3   # 用 /tmp/interview-boss-redact.txt 里的完整值，期望为空
git push --force --mirror git@gitee.com:satanstoy/interview-boss.git
git push --force --mirror https://github.com/Satanstoy/interview-boss.git
```
注意：重写会改变 95fcf63 之后所有提交哈希；本机工作克隆需重新 clone（filter-repo 后旧克隆不可用）。
两个远端均需 force-push 权限；Gitee 仓库若开启保护分支需先调整。

### 3. 验证
- git log 全历史 grep 旧 key 前缀 sk-hkaop 为 0 命中
- ./deploy/docker-deploy.sh check 或最小门禁（gitleaks 扫描）通过
- 生产 LLM/embedding 功能正常（新 key）