# 面经接口与迁移冲突定向审计 — 2026-10-08

范围：D9 数据模型完整性、D14 正确性与健壮性。Python/FastAPI、Vue/JavaScript、SQLite、Docker。此报告是本次事故及连带路径的定向审计，不是全仓安全认证。

## 已确认的问题与修复

| 严重度 | 位置 | 问题 | 处理 |
|---|---|---|---|
| 4 | backend/app/db/migrations/__init__.py:401 | 迁移只按编号跳过；已上线 onboarding/evaluation 的 121–126 与 upload recovery 重复 | 校验迁移名称；识别已发布旧分支名称，按依赖次序补齐遗漏增量，以 127 记录完成，不改写历史记录 |
| 3 | backend/app/routers/health.py:16 | SELECT 1 探活无法识别缺少应用表列 | 本次通过启动迁移名称校验与兼容补偿防止静默跳过；探活本身仍是连接检查 |
| 3 | frontend/src/views/InterviewView.vue:46 | 请求失败误显示空列表；翻页失败时新页码显示旧数据 | 独立面经 loading/error、隐藏旧表格、提供重试 |
| 3 | frontend/src/composables/useMasterBankData.js:129 | 招聘季只取前 100 条，且按当前季筛选后选项缩水 | 每页 100 条遍历完整授权数据，不传 season，防止旧请求覆盖新岗位结果 |
| 3 | frontend/src/layouts/AuthenticatedLayout.vue:498 | 来源导航只在当前面经页找记录，局部索引无法计算真实页码 | 遍历授权来源后请求 location，由服务端定位；消费状态需支持多次导航 |
| 3 | backend/app/routers/data.py:1090 | NULL 日期在升序列表中末尾，但 location 当作最早，导航到错误页 | ROW_NUMBER 直接复用列表排序，覆盖 NULL、同日期 ID 次序 |

根因与连带影响已通过源码和真实库结构核验，排除“启动没有调用迁移”与“面经被删除”：启动确实执行迁移，但旧 registry 仅按数字判断已执行。

缺失结构同时影响 upload_imports（上传与恢复）、question_resolutions（解析与公共发布）、公共贡献 revision/projection、question_promotion_requests（单题公共化审核）、publish_status（面经与统计）。兼容修复补齐整个功能组，保留 onboarding/evaluation 表与原 121–126 历史，不重跑旧破坏性迁移。

## 数据安全与线上证据

- 在真实数据库副本演练，补偿耗时 0.217 秒；全部原有表行数保持，原历史记录保持；重复运行成功。
- 修复前创建 SQLite backup API 一致性快照；备份压缩前后 SHA-256 一致。备份位于 backend/data/backups/pre_branch_identity_repair_20261008.db.gz，不纳入 Git。
- 线上迁移后 interview 总计 69、未删除 37、已发布公共 33，均保持；管理员列表显示 34（33 公共与 1 私人）。
- 线上 integrity_check = ok，foreign_key_check = 0；原 121–126 名称保持，新增 127。
- HTTP 面经列表、upload-imports、analytics、模拟面试 experiences、面经 location 均返回 200；公开 /api/health 返回 ok。
- backend 与 worker 容器恢复 healthy，恢复后的日志未见新的 error 事件。
- 宿主机磁盘空间不足以安全完成依赖重建，本次镜像沿用已有依赖并复制完整 backend/app，避免旧镜像缺少新模块；旧镜像保留 before-migration-repair-20261008 标签。前端静态资源在验证构建后更新。

## 回归与限制

- 针对迁移身份、所有旧迁移前缀、未知冲突、重复运行、schema hygiene、上传恢复、面经分页/岗位/软删除，64 passed。
- 首次扩大基础设施测试：345 passed、2 skipped；18 个 schema hygiene fixture 使用虚构 preseed 名称而被新校验拒绝，已改为真实 registry 名称，18 项单独及合并回归均通过。
- 仍有两项既有检查失败，与本次生产修改无关：test_check_secrets.py 把 9 个 e2e seed 的测试密码字面量报告为疑似密钥；test_docker_config.py 期待不存在的 DEPLOY_PRUNE_HOST_ARTIFACTS 配置。这两项没有通过放宽校验或跳过测试来掩盖。
- 审计 accepted.tsv/debt.tsv 已交叉检查，本次发现不在既有接受/延期项目内。既有全仓类型与旧 mocked e2e 债务未纳入本次修复。
- 并未在生产创建新上传/审批任务或调用付费模型；上传与审批写入契约由隔离测试验证，线上只执行读取探针。
- 前端最终 4 个相关 Playwright spec：11 passed（42.9 秒），覆盖首屏 500 重试、翻页失败、排序竞态、100 条后的招聘季、筛选后选项、跨页来源、连续不同来源、同来源翻页后重访、预览离线定位、跨岗位任务结果与 404。
- 前端生产构建通过，最终代码复审未发现必须修复项。静态产物打入 nginx 镜像，容器重新创建仍可保留修复。

## 交付与后续

确认的事故与导航问题已修复，不另建未完成的实施里程碑。健康探针依然只检查数据库连接，属于已说明的监控边界；本次通过启动强制校验阻断未知迁移身份冲突。

代码按任务归属本地提交。原有 bank_mode SQL 测试、question_bank_integrity 测试、ac029-db-trace 以及原有未跟踪文件均保留并排除在本次提交外。未获远端同步授权，因此未 push；需要同步时执行 `git push -u origin codex/frontend-ui-hierarchy-cleanup`。
- 变更文件 ESLint：0 errors；保留 10 项既有 unused-vars warnings。顺手移除了 appData 的重复同名字段，字段值及行为保持一致。
- 本地后端检查点：d8952da4，分支 codex/frontend-ui-hierarchy-cleanup；远端 origin 为 GitHub，未同步。
- 最终再次回归：11 passed（41.5 秒）；线上 HTML 主模块与最后一次构建的 index-eqGeGLgh.js 匹配。backend、worker、nginx 均 healthy。
- 与 2026-09-23 findings.tsv 在 D9/D14 范围按 dim/location/title 机械比较：新增 6、同键仍存 0；本次六项均已修复或通过启动校验缓解，趋势不用于推断范围外发现是否已解决。
