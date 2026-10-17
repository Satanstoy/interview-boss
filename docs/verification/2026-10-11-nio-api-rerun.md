# 蔚来 Agent 一面 API 复跑

本轮用户授权：修复讨论中的问题，清理之前上传的这个 case，然后通过 API 重跑。主线未合并。

## 代码与部署

- 分支：`codex/frontend-ui-hierarchy-cleanup`，origin GitHub。
- `fc8f7651`：补齐 Python基础 / 数据类型 / 对象身份与相等性；迁移保留系统现有分类、自定义标签及个人历史；禁止根据题目猜公司和轮次。
- `402bb416`：聚类后立即派发答案任务，Redis 异常保留 durable outbox；普通题最多一次修订并复核修订稿；审校异常/无参考来源/剩余问题保留待复核状态；空答案拒绝；修改答案或题干清除旧审校状态；API 和页面展示待复核数量与原因。
- 包含上一轮 `d903bace` 元信息与 URL 校验、`85ceaf25` 防误合并修复。
- 前后端、worker image revision 均为 `402bb416293bb0de449f407451b317da6c35e59a`；线上 `/api/health` 返回 status=ok/db=connected，三者 healthy。
- 依赖清单未变化，复用部署中的运行时依赖镜像，复制当前提交的 tracked backend/app 与本地构建的 frontend/dist 形成新镜像。当前镜像保留为 previous；没有重新下载依赖。

## 离线验证

- taxonomy + upload graph recovery：30 passed。
- refine / answer sources / public-personal scope / upload snapshot / status / cross-layer contracts：86 passed。
- job lifecycle + migration identities + upload recovery migrations：35 passed。
- frontend build 通过。任务中心 E2E 第一轮 38 passed，3 个旧文案断言失败；更新为答案已生成/待复核后，相关 4 个用例重跑全部通过。
- reviewer 检出的重写状态残留和空答案误通过问题已修复并有回归测试；最终审查未发现部署阻断项。
- 后续边界：生成过程中如果用户修改题干，旧题干的任务仍可能写回答案；本轮未改变该既有并发行为。

## 精确清理

- 备份：`/data/projects/interview-boss/backups/pre-case-rerun_20261010_235441.db`，SQLite backup API，quick_check=ok。先在备份库事务内演练并 rollback，再停止 worker/backend 后对生产执行事务。
- 旧 root：`403bdfb2-0939-4083-aaea-1e6fd58c5624`，面经 5031。
- 删除 1 条面经、11 条明细、9 道本次新建规范题及级联数据、11 条 resolution/队列记录、公开贡献请求与条目/事件、12 个任务及 payload、26 个步骤结果、68 条上传 LLM 调用账本、1 个 attempt/root。
- 历史规范题 5919 / 6047 保留，各移除本次新增原题及归属索引，恢复频次 10 / 1。没有按空 URL 批量删除其他来源。
- 旧 root / 面经 / 9 道新题都不存在；新增 FK 违反数 0；12 个旧 ARQ ID 对应临时键检查为 0。

## API 复跑（已完成）

- 输入：[同一组 11 道题](import-cases-2026-10-10/01-nio-original.txt)，来源 URL 修复为原始有效链接；content_type 为空自动识别，管理员 1，target=share，2027届秋招，Agent 开发岗位。
- 损坏 Markdown URL 返回 HTTP 400，不创建上传任务；有效提交返回 HTTP 202。
- 新 root：`45f4f6b2-a0e5-4ddb-b643-22b7e294dcd7`；面经 5032。
- 11 条明细公司/轮次均为蔚来/一面；list/tuple 标签 Python基础/数据类型；==/is 标签 Python基础/数据类型/对象身份与相等性；只有算法题使用算法手撕。
- 聚类 11 processed / 11 new，Tool Calling/Skill 与工具权限题没有再并入 5919 / 6047。
- 聚类及答案任务创建于 15:59:43 UTC，第一批答案同秒启动；旧 case 答案创建到首次启动约 142 秒。
- 公开来源 URL 仍按既有审核规则留空，明确的公司/轮次已保留。
- 最终 API 状态 completed：11 extracted / retained / resolved / answered，0 failed；1 passed、10 needs_review。生成与入库已结束，但不能据此声称全部答案质量通过。
- [完整机器验证记录](import-cases-2026-10-10/api-rerun-result.json)，包含逐题标签、规范题 ID、审校状态、任务时间、调用计数和删除对象。
- [线上查看本次面经](https://www.interviewboss.online/interview?highlight=5032&position=1)。

## 本次复跑继续暴露的问题

- 答案修订后仍偏长，审校状态如实保留 needs_review；简单题篇幅控制需要继续优化。
- 确定性字数阈值直接计入 Markdown URL 与代码；最长回文答案含正确的可运行实现也被标为超 700 字。其中心扩展实现对所有长度 0–7 的二元字符串共 255 个用例通过。下一轮应分开核算口述正文与代码/引用。
- list/tuple 答案已写明 tuple 只有所有元素可哈希时才能作为 dict key，但还错误地把 list.pop 等方法都说成返回 None；Python 运行验证 list.pop 返回移除的元素，事实审校仍漏检。
- 上游答案调用发生过三次 120 秒超时；减少派发等待不等于消除模型调用延迟。

## 最终耗时与限制

- 接受至结束共 758 秒；答案派发等待由约 142 秒降至 0 秒，但上游超时重试仍拖长整轮。
- 普通题一次修订后的最终审校结果如实写入数据库/API；10 个待复核不表示 10 道题全错，包含篇幅/代码计数、引用和审校返回损坏等原因。
- 答案阶段记录 42 次成功调用、3 次上游超时（共 45 次物理调用）；旧 case 为 9 道新题 45 次成功、5 次异常（共 50 次）。这只是单次复跑观测，不能视为稳定性能保证。
