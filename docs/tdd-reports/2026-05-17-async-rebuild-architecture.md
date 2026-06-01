# 并发安全 + 异步重建架构

**日期：** 2026-05-17
**类型：** TDD / 架构改进
**状态：** 完成

## 问题描述

1. `merge_question` 的 `_merge()` 无事务包裹，中途失败留脏数据
2. `dequeue_batch` 非原子（SELECT + UPDATE 分离），并发 worker 可能重复取出
3. `build_master_bank` 无锁，并发重建会互相破坏
4. 重建题库 inline 执行，连接断开丢失进度

## 解决方案

### Fix 1: merge_question 事务包裹
- `_merge()` 内函数添加 `BEGIN/COMMIT/ROLLBACK`
- LLM 调用在事务提交后执行

### Fix 2: 原子 dequeue
- 使用 `UPDATE ... WHERE id IN (SELECT ... LIMIT N) RETURNING` 实现原子取出
- 防止并发 worker 重复处理同一批次

### Fix 3: 并发锁 + 异步重建架构
- 新增 `jobs` 表（migration 022）跟踪后台任务状态和进度
- `POST /api/master-bank/build` 改为提交模式：创建 job 记录 → 返回 job_id → 立即响应
- ARQ worker 后台执行重建，写入 jobs 表进度
- Redis 不可用时 fallback 到 `asyncio.create_task`
- 重复重建请求返回 HTTP 409

### 新增端点
- `GET /api/jobs/{job_id}/stream` — SSE 进度流（2s 轮询 jobs 表）
- `GET /api/jobs/{job_id}` — 非流式状态查询

### worker.py 新增
- `build_master_bank_task` — ARQ 任务函数
- `enqueue_build_job` — 入队辅助函数

## 涉及文件
- `backend/app/db/connection.py` — migration 022 (jobs 表)
- `backend/app/routers/master_bank.py` — 异步重建 + job 端点 + merge 事务
- `backend/app/services/pipeline.py` — 原子 dequeue
- `backend/app/worker.py` — build_master_bank_task

## 架构变化

```
之前: 前端 → POST /build → SSE inline (分钟级) → 连接断开 = 进度丢失
之后: 前端 → POST /build → 立即返回 job_id
      前端 → GET /jobs/{id}/stream → SSE 轮询进度表
      worker → ARQ 执行重建 → 写入 jobs 表进度
```
