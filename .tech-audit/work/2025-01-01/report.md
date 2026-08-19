# 高频题库子系统技术审计报告

**审计范围**: 题库管理 (questions.py, questions_pkg/, bank_build.py, admin_review.py) + 题库服务 (question_bank_integrity.py, question_variant_reconciliation.py, question_draw_service.py, clustering_maintenance.py) + 题库数据层 (question_bank_sources.py)

**审计维度**: D1 代码精简性, D3 测试对抗性, D4 安全态势, D14 正确性与健壮性

---

## 健康评估: ⚠️

| 指标 | 状态 |
|------|------|
| 严重 (🔴) | 0 |
| 主要 (🟡) | 3 |
| 次要 (🟢) | 10 |

---

## 发现汇总

### 🟡 主要发现 (3)

| # | 维度 | 位置 | 问题 | 修复建议 |
|---|------|------|------|----------|
| 1 | D1 | mutations.py | 609 行路由包含完整业务逻辑 | 提取到 services/question_mutations_service.py |
| 2 | D1 | bulk.py | 529 行路由直接访问数据库和业务规则 | 提取到 services/question_bulk_service.py |
| 3 | D1 | bank_build.py | 416 行路由混合 SSE 流和任务管理 | 提取任务管理到 services/bank_build_service.py |

### 🟢 次要发现 (10)

| # | 维度 | 位置 | 问题 | 修复建议 |
|---|------|------|------|----------|
| 4 | D1 | questions.py:28 | _parse_answer_sources 静默吞掉所有异常 | 捕获 (json.JSONDecodeError, TypeError) |
| 5 | D1 | question_draw_service.py | 重复的 get_db_connection 包装器 | 直接使用 db.connection |
| 6 | D3 | tests/bank/ | 缺少 merge/split 端点集成测试 | 添加集成测试 |
| 7 | D3 | tests/services/clustering/ | 缺少竞态条件测试 | 添加并发测试 |
| 8 | D3 | tests/bank/ | 缺少 SSE 断开行为测试 | 添加断开模拟测试 |
| 9 | D4 | bank_build.py:62 | SSE 端点泄露任务错误信息 | 清理错误消息 |
| 10 | D4 | mutations.py | split/merge 无原始问题大小限制 | 添加 Pydantic 验证 |
| 11 | D14 | share.py:49-62 | find_matching_public_question 全表扫描 | 添加索引优化 |
| 12 | D14 | question_draw_service.py:200-217 | embedding_supplement 全表扫描 | 使用 FAISS 索引 |
| 13 | D14 | bulk.py:255 | delete_original_question 重抛为通用 500 | 记录具体异常类型 |

---

## 详细发现

### D1 代码精简性 — 路由层业务逻辑 (🟡)

**问题**: 题库路由文件包含大量业务逻辑，违反项目架构规则。

项目 CLAUDE.md 明确规定：
> "禁止业务逻辑：路由函数只做 HTTP 感知（解析请求、格式化响应），业务逻辑放 services/"

当前实现中：
- **mutations.py** (609 行): 包含 23 次 conn.execute、12 次 cursor.execute
- **bulk.py** (529 行): 包含 14 次 cursor.execute、13 次 conn.execute
- **bank_build.py** (416 行): 包含 21 次 json.dumps、8 次 conn.execute

**修复建议**: 按领域提取到 services 层

### D3 测试对抗性 — 集成测试缺失 (🟢)

**问题**: 缺少关键端点的集成测试覆盖。

缺少：
1. merge_question 端点完整流程测试
2. split_question 端点数据一致性测试
3. SSE 客户端断开连接资源清理测试
4. 并发 claim 同一原始题目竞态条件测试

### D14 正确性与健壮性 — 性能瓶颈 (🟢)

**问题**: 存在潜在性能问题。

1. share.py find_matching_public_question 每次分享都扫描所有公共题目
2. question_draw_service.py _embedding_supplement 使用 Python 循环而非 FAISS

---

## 已验证的正确实现

1. **事务处理**: BEGIN/COMMIT/ROLLBACK 模式正确
2. **认证授权**: 所有端点正确使用 Depends
3. **双写一致性**: sync_question_bank_projections 正确验证
4. **错误处理**: HTTPException 在事务内正确传播

---

## 优先级建议

| 优先级 | 发现 | 工作量 | 影响 |
|--------|------|--------|------|
| P1 | 路由层业务逻辑提取 (D1) | 大 | 架构改进 |
| P2 | 集成测试补充 (D3) | 中 | 质量保障 |
| P3 | 性能优化 (D14) | 中 | 可扩展性 |
| P4 | 小问题修复 (D1/D4) | 小 | 代码质量 |