# Triage

| Finding | Suggested milestone | Effort |
|---|---|---|
| 3 D10 @ `backend/app/core/config.py:198` — 私人Key静默回退系统且公共阶段Key不统一 | (group under D10 follow-up milestone) | 2d |
| 3 D14 @ `backend/app/services/clustering/matcher.py:764` — 匹配调用失败被归为不匹配 | (group under D14 follow-up milestone) | 1d |
| 3 D14 @ `backend/app/services/pipeline/queue.py:253` — 全局单批调度未续调剩余owner队列 | (group under D14 follow-up milestone) | 2d |
| 3 D14 @ `backend/app/agents/submit/graph.py:146` — 重试从头运行且写库入队非原子 | (group under D14 follow-up milestone) | 4d |
| 3 D14 @ `backend/app/agents/submit/graph.py:164` — 同用户同秒上传复用checkpoint标识 | (group under D14 follow-up milestone) | 0.5d |
| 3 D14 @ `backend/app/services/pipeline/queue.py:103` — 处理超时按创建时间回收 | (group under D14 follow-up milestone) | 2d |
| 2 D14 @ `backend/app/routers/bank_build.py:42` — pending事件协议与错误重试分类不一致 | (group under D14 follow-up milestone) | 1d |
| 3 D14 @ `backend/app/services/public_contributions.py:437` — 失败贡献再次批准被错误标成已发布 | (group under D14 follow-up milestone) | 2d |
| 3 D14 @ `backend/app/routers/submit.py:398` — 旧尝试重试可绕过运行中的后代任务 | (group under D14 follow-up milestone) | 1d |
| 3 D14 @ `backend/app/agents/submit/extract.py:76` — 优缺点子串黑名单静默丢弃技术题 | (group under D14 follow-up milestone) | 1d |
| 3 D14 @ `backend/app/services/public_contributions.py:537` — 批准撤回交错可留下已撤回但仍公开的内容 | (group under D14 follow-up milestone) | 2d |
| 3 D15 @ `frontend/src/layouts/AuthenticatedLayout.vue:560` — 上传刷新不定位记录或重置面经页码 | (group under D15 follow-up milestone) | 0.5d |
| 3 D15 @ `frontend/src/composables/useMasterBankData.js:75` — 只获取最早100条面经再本地排序 | (group under D15 follow-up milestone) | 1d |
| 3 D15 @ `frontend/src/composables/useSubmitJobs.js:161` — SSE静默结束不重连且恢复失败清空本地任务 | (group under D15 follow-up milestone) | 2d |
| 3 D15 @ `frontend/src/composables/useSubmitJobs.js:139` — 导入完成冒充全流程完成 | (group under D15 follow-up milestone) | 2d |
| 3 D4 @ `backend/app/routers/submit.py:215` — 普通用户分享未进入已有审核流 | (group under D4 follow-up milestone) | 1d |
| 3 D5 @ `backend/app/services/public_contributions.py:413` — 审核修正字段未应用到公开投影 | (group under D5 follow-up milestone) | 1d |
| 3 D5 @ `backend/app/routers/bank_build.py:33` — 管理员通用任务流可读他人私人面经结果 | (group under D5 follow-up milestone) | 1d |
| 3 D9 @ `backend/app/agents/submit/persist_personal.py:111` — 私人命中公共题未持久化引用关系 | (group under D9 follow-up milestone) | 3d |
| 3 D9 @ `backend/app/services/public_contributions.py:250` — 同URL后续贡献未更新面经题目清单 | (group under D9 follow-up milestone) | 1d |

# Milestone stubs
