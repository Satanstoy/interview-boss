# SPEC: Embedding 服务双后端 + 全量重建 + 配置外置

## 背景

现有 `embedding_service.py` 仅支持本地 ONNX（bge-small-zh-v1.5，512 维）+ hash 兜底。
聚类每次 `cluster_batch` 都全表分页扫描 SQLite 重建临时 FAISS（`batch.py:112-143`）。
聚类阈值等 12 个参数硬编码在模块常量，改一次要改代码重新部署。

## 目标（本批次）

1. **embedding 双后端**：新增 SiliconFlow API 后端（BAAI/bge-m3，1024 维），保留 ONNX/hash 路径做离线兜底。
2. **维度自描述**：`question_bank` 加 `embedding_model`/`embedding_dim` 列，避免 512/1024 维数据混用。
3. **全量重建脚本**：`scripts/rebuild_embeddings.py` 用 bge-m3 重算所有题 embedding 并回写 BLOB。
4. **配置外置**：聚类参数从模块常量迁到 `core/config.py` + 环境变量，支持不重启调参（A/B 半步）。

## 非目标（后续批次）

- FAISS 索引常驻内存 + `add_with_ids` 增量维护（批次二）
- 二次验证 embedding 预排序、清死代码（批次三）
- 统一个人/公共入库、ARQ 默认、指标持久化、背压（批次四）

## 设计

### A. embedding_service.py 改造

- 复用 `openai` 库的 **同步** `OpenAI` client（`openai>=1.30.0` 已是依赖），保持 `encode_texts()` 同步签名不变，避免改动所有调用方。
- 配置（env）：
  - `EMBEDDING_BACKEND`：`auto` | `onnx` | `hash` | `siliconflow`（新增）
  - `SILICONFLOW_API_KEY`、`SILICONFLOW_BASE_URL`（默认 `https://api.siliconflow.cn/v1`）
  - `EMBEDDING_API_MODEL`（默认 `BAAI/bge-m3`）
  - `EMBEDDING_API_BATCH`（默认 32，单次请求文本条数上限）
  - `EMBEDDING_DIMENSION`：维度由后端决定。siliconflow bge-m3 = 1024（不可调，bge-m3 不支持 Qwen 系列的 `dimensions` 参数）。onnx = 512。`auto` 默认 onnx（512），切到 `siliconflow` 时维度自动 1024。
- `_get_siliconflow_client()` 惰性单例 + 缓存（key=api_key+base_url+model）。
- `_encode_texts_siliconflow(texts)`：按 `EMBEDDING_API_BATCH` 切分，循环调 `client.embeddings.create(model, input=chunk)`，拼接 `data[*].embedding`，float32 + L2 归一化。失败直接抛（生产不应静默降级到 hash）；但 `auto` 模式下 API 失败才回退 hash。
- `encode_texts()`：`siliconflow` 后端调新函数；`auto` 优先 onnx，onnx 不可用→尝试 siliconflow（如果配了 key）→hash。
- 维度常量 `_DIMENSION` 改为按后端动态算：siliconflow→1024，否则维持 env `EMBEDDING_DIMENSION`（默认 512）。新增 `get_embedding_dimension()` 公开函数返回当前生效维度。

### B. Migration 048

`migrations/clustering.py::_migration_048_embedding_metadata`：
- `question_bank` 加 `embedding_model TEXT DEFAULT NULL`、`embedding_dim INTEGER DEFAULT NULL`。
- 幂等（先查 columns）。注册到 `__init__.py::_MIGRATIONS` 末尾。

### C. 重建脚本 `scripts/rebuild_embeddings.py`

- 前缀 `fix_` 不合适（非修复），用通用脚本（放 `scripts/` 根，不加 `fix_/verify_/check_` 前缀，属一次性运维工具）。
- 流程：
  1. 连生产 DB（`backend/data/interview-boss.db`）
  2. 查所有 `embedding` 为 NULL 或 `embedding_dim != 当前维度` 且 `deleted_at IS NULL` 的题
  3. 按 cat2 分组，每组按 `EMBEDDING_API_BATCH` 批量调 bge-m3
  4. 写 `embedding` BLOB（float32 + 归一化的 `tobytes()`）+ `embedding_model` + `embedding_dim`
  5. 进度打印 + 失败计数；支持 `--dry-run`、`--limit N`
- 可作模块执行：`docker compose exec backend python /app/backend/scripts/rebuild_embeddings.py --dry-run`

### D. 配置外置（core/config.py）

新增聚合配置区域（env，启动加载，不热更新——热更新留给后续）：

| 常量 | env | 默认 | 来源模块 |
|------|-----|------|---------|
| `CLUSTER_BATCH_SIZE` | `CLUSTER_BATCH_SIZE` | 40 | `pipeline/sanitize.py` |
| `CLUSTER_MAX_CONCURRENCY` | `CLUSTER_MAX_CONCURRENCY` | 8 | `clustering/matcher.py`、`clusterer.py`、`compact.py` |
| `CLUSTER_PREFILTER_TOP_K` | `CLUSTER_PREFILTER_TOP_K` | 30 | `matcher.py` |
| `CLUSTER_RECENT_DAYS` | `CLUSTER_RECENT_DAYS` | 7 | `matcher.py` |
| `CLUSTER_VALIDATION_BATCH` | `CLUSTER_VALIDATION_BATCH` | 20 | `matcher.py` |
| `CLUSTER_DIRECT_ACCEPT` | `CLUSTER_DIRECT_ACCEPT_CONF` | 0.92 | `clustering/prompts.py` |
| `CLUSTER_VALIDATION_ACCEPT` | `CLUSTER_VALIDATION_ACCEPT` | 0.8 | `clustering/prompts.py` |
| `CLUSTER_MIN_SIMILARITY` | `CLUSTER_MIN_SIMILARITY` | 0.6 | `clusterer.py` |
| `CLUSTER_V2_SIM_THRESHOLD` | `CLUSTER_V2_SIM_THRESHOLD` | 0.6 | `clusterer.py` |
| `CLUSTER_V2_FAISS_TOP_K` | `CLUSTER_V2_FAISS_TOP_K` | 10 | `clusterer.py` |
| `CLUSTER_COMPACTION_CONCURRENCY` | `CLUSTER_COMPACTION_CONCURRENCY` | 8 | `compact.py` |
| `CLUSTER_CAT2_BATCH` | `CLUSTER_CAT2_BATCH` | 5 | `compact.py` |
| `CLUSTER_PHASE2_BATCH` | `CLUSTER_PHASE2_BATCH` | 20 | `compact.py` |

各模块改为 `from app.core.config import CLUSTER_*` 替换硬编码常量。
`clustering/prompts.py` 的阈值是运行时拼进 prompt，改成读 config（仍保持模块导入时绑定值——首启加载即可，不需要热更新）。

## TDD 测试矩阵

| 测试 | 验证 |
|------|------|
| `test_siliconflow_client_caching` | 同 key/url/model 复用单例 |
| `test_siliconflow_encode_batch_split` | 超过 batch 切片循环调用 |
| `test_siliconflow_encode_normalizes` | 输出 L2 归一化 float32 |
| `test_siliconflow_empty_input` | 空输入返回 (0, dim) |
| `test_siliconflow_api_error_raises` | API 异常直接抛 |
| `test_auto_falls_back_to_hash_when_no_onnx_no_key` | 无 onnx 无 key → hash |
| `test_get_embedding_dimension_per_backend` | 不同后端返回正确维度 |
| `test_migration_048_adds_columns` | 幂等加列 |
| `test_cluster_config_loaded_from_env` | env 覆盖默认值 |
| 现有 `test_embedding_*` `test_embedding_core` | 不回归（默认 onnx 512 维） |

## 执行顺序

1. 写失败测试（services + infra）
2. Migration 048
3. embedding_service siliconflow 后端
4. config.py 聚类参数
5. 各聚类模块常量替换
6. rebuild_embeddings.py 脚本
7. `docker compose --profile test run --rm test uv run pytest backend/tests/services/ backend/tests/infra/ -q`
8. 停下，等用户确认再 commit / 下一批次

## 偏差修复记录（四批次完成后对照 spec 的补齐）

| 偏差 | 修复 |
|------|------|
| #9 统一入库路径核心未落地：个人提交仍走旧路径，不进 analysis_queue | ① `faiss_index_manager.py` 双层 key `(job_position, owner_id)` + SQL `owner_id IS NULL / = ?` 严格隔离 ② `batch.py` cluster_batch 增量 `add_clusters` 替代 invalidate ③ `persist_personal.py` 落库后 `enqueue_questions(interview_id, owner_id=user_id)` ④ `graph.py` 个人路径 `match_persist_personal → cluster_public → END` |
| rebuild_embeddings.py 未按 cat2 分组 | 查询加 `ORDER BY cat2, id`，按 cat2 分组、组内按 BATCH 处理，打印分组数 |
| siliconflow client 缓存未按 key | `_SILICONFLOW_CLIENTS: Dict[(api_key, base_url, model), client]`，配置变化重建 client |
| FAISS 用失效重建而非 add_with_ids 增量维护 | `IndexIDMap2(IndexFlatIP)` + `add_with_ids`/`remove_ids`；cluster_batch 写后从 DB 读新聚类 embedding 增量 add；compact 低频路径保留全清 |

新增测试：`test_faiss_index_manager.py` owner 隔离/增量维护 3 项、`test_embedding_siliconflow.py` keyed cache 1 项；`test_langgraph_workflows.py` mock_db patch `batch.process_incremental_batch` + 独立 `FAISSIndexManager`（测试隔离）。