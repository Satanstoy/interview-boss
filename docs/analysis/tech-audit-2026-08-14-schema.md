# Tech Audit 2026-08-14 — 数据库结构设计（D9 Data Model Integrity）深度排查

> 触发：/tech-audit 第三轮——「数据库的结构设计是否合理」
> 范围：SQLite 生产库（interview-boss.db，67 表 / 104 索引 / 0 触发器）全部表结构、约束、索引、迁移机制
> 前两轮：全量 audit（75 findings）→ CRUD 深度排查（21 findings，commit 0f574a9）
> 方法：生产库只读快照（WAL 一致性副本 /tmp/schema-audit）+ PRAGMA 全量检查 + 4 分域 subagent 代码×schema 交叉核对（core-infra / bank / practice-coding / chat）

## 总体结论

**结构整体健康，无 🔴 船阻塞项；本轮新增 28 条（10 🟡 / 17 🟢 / 1 🟢low），全库累计 103 条。** 新表设计普遍优秀（chat_side_effect_jobs / cluster_review_tasks / assistant_generations 的幂等键、部分唯一索引、乐观锁版本列都是教科书级模式）；主要问题集中在**历史演进债**：

1. **FK 启用的历史断层留下大量孤儿数据**：connection.py:35 的 PRAGMA foreign_keys=ON（commit e3936da）之前级联从未生效，硬删父行全部留下孤儿——chat_messages 1316 行、interview_asked_questions 2235/2245 会话孤儿 + 1860/2245 题孤儿、quality_issue 7 行、question_sources/original_items/question_position 各 1 行。
2. **FTS5 与 question_bank 失步**（本轮最意外的发现）：sync_fts_entry/delete_fts_entry 零生产调用，FTS 只在迁移 025 填充一次；快照实测 331 行中 88 行指向已不存在的题、44 个活跃题不在 FTS——搜索质量随时间劣化。
3. **约 9 处表/列缺 FK 声明**，依赖应用层手动清理（delete_conversation 手动清两表）或干脆不清理（question_bank 硬删路径不清理 asked_questions/quality_issue/FTS）。
4. **无 schema 文档**：80 个迁移、67 张表，docs/ 无架构图。
5. **清理机制普遍缺失**：analysis_queue（593 行全 done）、jobs（302 行常驻）、email_verification_codes（941 行中 936 已过期）均无按龄清理。
6. **死列/冗余索引/格式混杂**等 🟢 级打磨项：vector/duplicate_of 死列、2 对重复唯一索引、4 种时间戳格式并存、error/last_error 100% 冗余。

## 统计（本轮）

| 维度 | 新增 | 累计 |
|---|---|---|
| findings | 28（0 🔴 / 10 🟡 / 17 🟢 / 1 🟢low） | 103（4 🔴 / 27 🟡 / 56 🟢 / 10 🟢low / 6 FIXED） |
| D9 累计 | 28 | 39 |
| effort | S×9 / M×16 / L×3 | — |
| confidence | high×19 / medium×8 / needs-verification×1 | — |

## 关键证据（生产库快照，只读）

| 检查项 | 结果 |
|---|---|
| PRAGMA integrity_check | ok |
| PRAGMA foreign_key_check | **1319 violations**（chat_messages→chat_conversations 1316；question_sources/qoi/question_position→question_bank 各 1） |
| question_fts 一致性 | 331 行中 88 个 rowid 已不存在、44 个活跃题缺失 |
| interview_asked_questions 孤儿 | 2235/2245 会话、1860/2245 题目、1 用户 |
| email_verification_codes | 941 行：936 已过期、847 已用、0 清理代码、无 expires_at 索引 |
| analysis_queue | 593 行全 status='done'（2026-05~07 历史），question_detail_id 孤儿 19 行 |
| quality_issue.qb_id 孤儿 | 7/301 引用已硬删题 |
| JSON 双写列漂移 | sources/original_questions 各 4 行与规范化表不一致（含 xsec_token URL 未落表） |
| jobs | 302 行（278 completed / 19 failed / 5 running），job_payloads 291 行，无 DELETE 路径；error/last_error 快照 19 行两列恒一致 |
| schema_version | 78/79 已应用；20 为注释待启用项、080 interview_import 为未提交新迁移（生产未部署，均非问题） |
| 0 行表 | chat_turns / chat_side_effect_jobs / assistant_generations / chat_candidate_sets / chat_tool_traces / interview_events / pipeline_metrics / user_practice_history / practice_deck_items / merge_feedback / coding_playlist_items / coding_problem_favorites / user_interview_distribution_preferences |

## 分域结论

### 1. 跨切面（父进程核实，6 条）
- 🟡 **FK 孤儿 1319 行**（伞形）：一次性清理迁移 + PRAGMA foreign_key_check 回归测试（chat 域 A4 同题并入本条）
- 🟡 **schema 文档缺失**：80 迁移/67 表无 docs/architecture/schema.md
- 🟢 重复唯一索引 2 对（practice_decks.deck_key / user_question_review UNIQUE；A3 同题并入本条）
- 🟢 时间戳格式混杂（mcp_sessions INTEGER / login_failures REAL / jobs 空串哨兵）
- 🟢 question_bank.vector 死列（现役 embedding BLOB）
- 🟢 任务持久化碎片化（6 套队列表）

### 2. core-infra 域（A1，7 条）
- 🟡 analysis_queue 无限增长无清理（593 done）+ question_detail_id 19 孤儿 + status 无 CHECK
- 🟡 jobs 无留存清理 + error/last_error 100% 冗余 + available_at '' 哨兵（274/302 行）
- 🟡 email_verification_codes 过期码不清理（936/941）+ 无 expires_at 索引
- 🟢 users.username 唯一约束 BINARY 大小写敏感且注册不归一化（'Alice'/'alice' 可双账户）
- 🟢 profile_pkg/email.py 绑定邮箱路径未归一化（可绑大小写变体邮箱）
- 🟢 login_failures 无清理（10/14 孤儿）+ locked_until REAL 格式混杂
- 🟢 refresh_tokens 过期清理无索引 + 同表 ISO/无时区两格式混存

### 3. bank 域（A2，6 条）
- 🟡 **FTS5 与 question_bank 失步**：同步函数零生产调用，88 死 rowid + 44 活跃题缺失（父进程复测确认）
- 🟡 quality_issue.qb_id 无 FK，7 条孤儿（serialize_issue 读不到题面）
- 🟡 JSON 双写列与规范化表漂移 4 行（仅 weekly cron 检测，无自动修复）
- 🟢 taxonomy UNIQUE(position_name,source,owner_id) 对 owner_id NULL 不约束（依赖非原子 UPDATE+INSERT）；job_positions.is_deleted 违背全库 deleted_at 约定
- 🟢 interview/jd owner_id FK 无 ON DELETE（与 chat/coding/practice 不一致，dormant）
- 🟢 question_bank.duplicate_of 死列 + idx_qb_duplicate_of 死索引（镜像机制已废除）

### 4. practice/coding 域（A3，5 条）
- 🟡 user_practice_history 与 SM-2 复习系统**双写同一评估**：self_check 同答案+分数写旧表又写 review 体系；user_answer 另在 user_question_view 双存——两套并行权威源
- 🟢 question_bank 硬删 CASCADE 连删 user_question_review 与 practice_review_events，复习事件审计痕迹永久丢失
- 🟢 practice_decks.visibility 退化无功能（public 口径强制 1=0）+ owner_id 无 FK
- 🟢 coding_playlist_items/favorites 复合 PK 的 FK 侧 problem_id 无索引 + playlists 名称 BINARY 排序
- 🟢 coding_submissions 三 FK 无 ON DELETE 策略 + parent 自引用无 SET NULL + problems.owner_id 无 FK（dormant）

### 5. chat 域（A4，4 条）
- 🟡 interview_asked_questions 全列缺 FK 且硬删无清理（2235 会话 + 1860 题孤儿，foreign_key_check 因无 FK 完全检测不到）
- 🟢 chat_conversations.jd_id 无 FK（jd 有硬删路径，产线 0 行使用 → latent）
- 🟢 chat_memories provenance 列全空（295 行 source_turn_id/source_job_id/expires_at 均空）+ source_job_id 无 FK + expires_at 无物理清理
- 🟢 新 chat 表群产线零使用：chat_tool_traces 无 INSERT 写入方（死表）却缺 FK；selected_item_id 无 FK

## 验证过的良好设计（不报 finding）

- chat_side_effect_jobs：UNIQUE(kind, source_turn_id) 幂等键 + status CHECK + FK 策略完整
- cluster_review_tasks：UNIQUE(cluster_id, review_version) 防重复入队；dispatcher lease 正确
- assistant_generations：UNIQUE(message_id) + parent SET NULL 自引用
- chat_turns：UNIQUE(conversation_id, client_request_id) 请求幂等 + 部分唯一索引保证单 running fence
- interview_distribution_stats/exclusions：复合 PK 天然幂等
- merge_history：审计追加式（rollback 用标志位而非硬删）
- refresh_tokens：jti 唯一 + family 吊销 + 定期过期清理（仅缺索引）
- question_variant_owners：normalized_question 主键 = 全局去重注册表
- delete_conversation：手动清无 FK 表 + 依赖 CASCADE，当前路径正确（孤儿为历史遗留）
- mcp_tokens：token 由 HMAC(SECRET,user_id+seed) 派生，仅存 hash，无明文种子

## 建议里程碑

- **M1（本轮修复，S/M 级）**：孤儿数据一次性清理迁移（chat_messages/asked_questions/quality_issue/19 条 analysis_queue/88 条 FTS）+ foreign_key_check=0 回归断言
- **M2（短期）**：FTS 同步修复（挂接删除/合并/清空路径 + 全量重建）+ 补齐缺 FK 声明（9 处）+ email 验证码/analysis_queue/jobs 清理任务
- **M3（中期）**：schema 文档（docs/architecture/schema.md）+ 死列/冗余索引清理 + user_practice_history 双写收敛（定唯一权威源）+ 统一时间戳格式

## 修复实施（2026-08-14，同日完成）

> 用户要求三项保证：不破坏数据 / 数据库操作同步改 / 安全。全部按 TDD 实施，测试在 Docker test-runtime 全绿；破坏性迁移在生产库部署时由 run_migrations 自动整库备份后执行。

### 已修复（本轮 21 条标记 FIXED，另有 5 条前轮 FIXED）

| commit | 内容 |
|---|---|
| bdb93ba | 迁移执行器安全：破坏性迁移（081/082/084/085/086）执行前自动整库备份（backend/data/backups/pre_migration_vNNN_*.db）+ 表重建期间临时关闭 FK（防 DROP 级联误删子表） |
| 2109042 / 94b7806 | 迁移 081-086：孤儿清理（含 qois 子表级联缺口修复）、FTS 重建+触发器同步、重复索引清理、时间戳/任务表统一、11 表 FK 声明补齐（含 username 小写回填、taxonomy 去重）、死列/过期索引；代码同步：jobs.error 全部读写点改 last_error（worker/job_lifecycle/embedding_recompute/interview_import/bank_build） |
| 52489d3 | 认证归一化：username/email 小写+去空白（注册/登录/绑定/锁定期统一口径）；locked_until TEXT 格式；顺带修复「锁定计数每次登录前被清空、锁定机制永不触发」的潜在缺陷 |
| 0e059e5 | jobs.error 列遗留读写清理 |
| 6050b9c | worker 每日 4:00 DB 保留期清理（过期验证码/完成队列/失败登录/90 天陈旧任务，父任务血缘保护） |
| bbebc89 | mcp_sessions.updated_at 统一 ISO 文本 |

### 生产库快照验证结果（只读副本全链跑 081-086）

- integrity_check: ok；foreign_key_check: 0（1319 孤儿清零）
- 非孤儿数据 100% 保留：users 52 / jobs 302 / question_bank 313 / interview 62 / jd 29 / chat_conversations 53 / chat_memories 295 / coding_submissions 9 / practice_decks 2 / taxonomy 7
- 孤儿清理：chat_messages −1316、asked_questions −2215、quality_issue −7、analysis_queue −19、sources/qoi/qp −1×3
- FTS 重建 313=313，触发器插/删同步生效；Jihangyu→jihangyu；refresh_tokens ISO 统一
- 新增测试：test_migration_backup（6）/ test_schema_hygiene（16）/ test_auth_normalization（7）/ test_db_retention（5）/ test_mcp_session_format（3）

### 剩余未修（设计/低优先，保持 open）

- 任务队列碎片化整合（jobs/analysis_queue/cluster_review_tasks 等 6 套）
- JSON 双写列漂移自动修复（现仅 weekly cron 检测）
- interview/jd owner FK ON DELETE 策略（无用户删除路径，dormant）
- job_positions.is_deleted → deleted_at 改名
- practice 双写权威源收敛（user_practice_history vs SM-2 体系）
- practice_review_events 级联删除审计保留策略
- practice_decks.visibility 死列删除（owner FK 已补）
- coding_playlist_items/favorites FK 侧索引、chat_memories.expires_at 物理清理

