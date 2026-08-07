# InterviewBoss

中文 AI 面试备战平台。JD/面经 → 提取面试题 → LLM 分类打标聚类 → 口述级答案 + 模拟面试 + 知识图谱。

## 语言

**全局模型配置（Global Model Config）**:
管理员统一配置的 LLM 与 embedding 参数，存于 `user_profile` 表（全局单例，无 owner）。
_避免使用_: 系统配置（歧义，per-user 配置也属配置）

**全局 LLM 配置（Global LLM Config）**:
`user_profile` 的 `llm_*` key；per-user 未配置时回退到它。
_避免使用_: 主模型配置

**per-user LLM 配置（User LLM Config）**:
`user_llm_config` 表的每用户记录；优先级高于全局 LLM 配置。

**embedding 配置（Embedding Config）**:
`user_profile` 的 `embedding_*` key；模块级 env 常量兜底，`reload_embedding_config()` 从 DB 热加载覆盖。

**全量重算（Embedding Recompute）**:
更换 embedding 模型后，重编码所有未删除题的向量并更新 `embedding_model`/`embedding_dim` 列；失败时回滚已更新行，保证"全成功或全不动"。
_避免使用_: 向量刷新（语义含糊）

**过渡窗口（Transition Window）**:
embedding 配置 reload 生效到全量重算完成之间的阶段；期间依赖 embedding 的检索/聚类暂不可用或失真，其余功能不受影响。

**测试连接（Connectivity Test）**:
用提交的配置探测 LLM/embedding 服务连通性，不保存配置。
