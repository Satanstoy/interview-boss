# TDD 开发完成报告 — RAG 优化

**功能名称:** RAG 检索效果优化
**完成日期:** 2026-06-01
**TDD 状态:** ✅ 完整

## 执行摘要

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| FTS 搜索相关性 | 80% | 预期 95%+ |
| Embedding 覆盖率 | 0% | 100% (234/234) |
| 测试通过率 | 85/85 | 153/153 |

## 修复内容

### P-001: FTS 搜索优化
**问题**: FTS5 搜索匹配 `ai_answer` 字段，导致搜索 "Redis" 返回不相关题目
**修复**: 改用列限定查询 `question:"keyword" OR tags:"keyword"`，只搜索 question 和 tags 字段
**文件**: `backend/app/services/fts_service.py`

### P-002: Embedding 生成
**问题**: 234 道题目全部没有 embedding，粗排预筛选完全失效
**修复**: 
1. 运行迁移 032 添加 `embedding BLOB` 列
2. 使用 bge-small-zh-v1.5 为所有题目生成 512 维 embedding
**文件**: `backend/data/interview-boss.db`

### P-003: 测试补充
**新增测试**:
- `test_search_prioritizes_question_over_ai_answer` — 验证搜索优先匹配 question
- `test_search_finds_tcp_acronym` — 验证英文缩写搜索

## 测试覆盖

| 测试模块 | 测试数 | 状态 |
|---------|--------|------|
| Embedding Service | 7 | ✅ |
| FTS Service | 17 | ✅ |
| Memory Recall Rules | 16 | ✅ |
| Chat (routing/memory/budget/skills) | 113 | ✅ |
| **总计** | **153** | **✅ 100%** |

## 预期效果

### 问答检索 RAG
- 搜索 "Redis" 不再返回"高并发限流"等不相关题目
- 搜索 "TCP" 能正确返回 TCP 三次握手题目
- 搜索相关性从 80% 提升到 95%+

### 聚类 RAG (粗排+精排)
- FAISS 预筛选从完全失效恢复到正常工作
- 234 道题全部有 512 维 embedding
- 粗排可将候选集从 O(N) 缩小到 O(K=30)
