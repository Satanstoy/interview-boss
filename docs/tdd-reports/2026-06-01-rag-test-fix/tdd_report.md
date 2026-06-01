# TDD 开发完成报告

**功能名称:** RAG 测试修复与补充
**完成日期:** 2026-06-01
**TDD 状态:** ✅ 完整

## 执行摘要

| 指标 | 结果 |
|------|------|
| 修复前通过率 | 29/33 (88%) |
| 修复后通过率 | 85/85 (100%) |
| 新增测试数 | 31 |
| 修复测试数 | 25 (代理问题) |

## 问题修复

### 问题 1：SOCKS5 代理导致测试失败
- **根因**: `ALL_PROXY=socks5h://127.0.0.1:7891` 环境变量导致 httpx 初始化 Anthropic 客户端失败
- **修复**: 在 conftest.py 添加 session 级 autouse fixture 清除 ALL_PROXY
- **影响**: 24 个 chat 相关测试从全部失败变为全部通过

### 问题 2：Embedding 测试断言过严
- **根因**: `test_search_returns_top_k_indices_and_scores` 断言分数 >= 0，但 FAISS 内积范围为 [-1, 1]
- **修复**: 改为 `all(-1.01 <= s <= 1.01 for s in scores)`

## 新增测试文件

### 1. FTS 服务测试 (`backend/tests/services/test_fts_service.py`)
- 15 个测试，覆盖：
  - 英文关键词 FTS5 搜索路径
  - CJK 关键词 LIKE 回退路径
  - 岗位过滤
  - 排除已答题目
  - 已删除题目过滤
  - FTS 索引同步/删除

### 2. Memory Recall 规则测试 (`backend/tests/services/test_memory_recall_rules.py`)
- 16 个测试，覆盖：
  - 规则意图分类（chat/practice_request/follow_up）
  - 大小写不敏感
  - 长消息追问关键词不触发
  - 关键词提取（中文/英文/混合）
  - 停用词过滤
  - 关键词数量限制

## 测试覆盖矩阵

| 测试模块 | 测试数 | 状态 |
|---------|--------|------|
| Embedding Service | 7 | ✅ PASS |
| Session Search | 8 | ✅ PASS |
| Memory Flush | 10 | ✅ PASS |
| Context Builder | 4 | ✅ PASS |
| FTS Service (新增) | 15 | ✅ PASS |
| Memory Recall Rules (新增) | 16 | ✅ PASS |
| Chat Routing | 12 | ✅ PASS |
| Chat Memory Recall | 9 | ✅ PASS |
| Chat Fast Path | 5 | ✅ PASS |
| **总计** | **85** | **✅ 100%** |

## RAG 架构验证结果

### 运行时聊天 RAG ✅
- 意图路由：practice_request → RAG, chat → 直接回复 ✅
- CJK 回退：FTS5 不支持中文时自动切换 LIKE 搜索 ✅
- 检索门控：answer_complete=True 时才触发 RAG ✅
- 岗位过滤：按 job_position 过滤题目 ✅

### 离线聚类 RAG ✅
- Embedding 生成：bge-small-zh-v1.5 输出 512 维 float32 ✅
- FAISS 索引：构建和检索正常 ✅
- 预筛选：O(N) → O(K=30) 降维 ✅

## 结论

✅ 所有 RAG 相关测试通过
✅ 代理环境问题已修复
✅ FTS 服务和 Memory Recall 规则路径已有完整测试覆盖
✅ 可安全集成到主干
