# 全局 Embedding 配置：DB 热加载 + 模型更换全量重算

背景：管理员无法通过 UI 配置 embedding——全部是模块级 env 常量，换模型必须改 env + 重建容器，旧向量失效需手动重算（生产 2026-08-06 切 SiliconFlow bge-m3 后重算过 320 题）。决定让 `embedding_service.py` 的模块级常量保持 env 兜底，新增 `reload_embedding_config()` 从 `user_profile`（全局单例）热加载覆盖；保存配置时若模型相关项变化，触发全量重算 job。

关键权衡（grill-me 确认）：

- **原子性**：重算逐批 UPDATE `question_bank.embedding`，每批前读取旧值，失败逆向恢复已更新行——"全成功或全不动"，避免混合模型向量导致 FAISS 维度不一致崩溃。
- **过渡窗口**：保存配置后立即 reload + invalidate FAISS，接受重算完成前 embedding 检索/聚类短暂不可用或失真（低频管理员操作、几十秒、其余功能不受影响），不加额外"重算期间禁用 embedding"的防护。
- **启动同步**：`asgi.py`/`worker.py` 启动时紧跟 `_reload_from_db()` 调用 `reload_embedding_config()`，保证容器重启后配置保持（DB 无 `embedding_*` key 时 no-op，env 兜底向前兼容）。
- **跨进程**：重算 job 在 ARQ worker 进程运行（`EMBEDDING_RECOMPUTE_USE_ARQ=0` 时 backend 内联），worker 启动时也从 DB 加载配置；backend 保存配置立即 reload，两进程状态独立但同源。
- **重算范围**：`question_bank` 全部未删除题（`deleted_at IS NULL`），含个人题与 pending，与 FAISS 按 `(job_position, owner_id)` 分池的口径一致，消除个人池维度不一致风险。
