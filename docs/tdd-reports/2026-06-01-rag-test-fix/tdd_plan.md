# TDD 开发计划

**功能名称:** RAG 测试修复与补充
**日期:** 2026-06-01
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

修复现有 RAG 测试因代理配置导致的失败，并补充缺失的 FTS 检索和记忆召回服务单元测试。

## 验收标准

- [ ] 所有 chat 相关测试通过（routing、memory_recall、fast_path）
- [ ] FTS 服务有独立的单元测试覆盖
- [ ] Memory Recall 服务的规则路径有独立测试覆盖
- [ ] 所有测试在有代理的环境下也能正常运行

## 问题分析

### 问题 1：代理配置导致测试失败
- **根因**: `ALL_PROXY=socks5h://127.0.0.1:7891` 环境变量导致 httpx 初始化 Anthropic 客户端失败
- **影响**: 24 个 chat 相关测试全部失败
- **修复方案**: 在 conftest.py 中添加 session 级 fixture 清除 ALL_PROXY

### 问题 2：FTS 服务缺少单元测试
- **文件**: `backend/app/services/fts_service.py`
- **缺失**: FTS5 搜索、CJK 回退、岗位过滤、排除已答题目的测试

### 问题 3：Memory Recall 服务规则路径缺少独立测试
- **文件**: `backend/app/services/memory_recall_service.py`
- **缺失**: `_rule_based_intent`、`_extract_keywords_fallback` 的独立测试

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | 修复代理问题 | 运行现有 chat 测试 | 全部通过 | ⏳ 待写 |
| T-002 | FTS 英文关键词搜索 | "Redis" | 匹配含 Redis 的题目 | ⏳ 待写 |
| T-003 | FTS CJK 回退搜索 | "缓存策略" | LIKE 匹配成功 | ⏳ 待写 |
| T-004 | FTS 岗位过滤 | keywords + job_position | 只返回匹配岗位的题目 | ⏳ 待写 |
| T-005 | FTS 排除已答题目 | keywords + exclude_ids | 不包含已排除 ID | ⏳ 待写 |
| T-006 | 规则意图分类 - 面试 | "请介绍一下 Redis" | interview_question | ⏳ 待写 |
| T-007 | 规则意图分类 - 练习 | "给我出一道题" | practice_request | ⏳ 待写 |
| T-008 | 规则意图分类 - 闲聊 | "你好" | chat | ⏳ 待写 |
| T-009 | 关键词提取 - 中文 | "Redis 的缓存策略" | 包含 Redis、缓存 | ⏳ 待写 |
| T-010 | 关键词提取 - 英文 | "How to use Docker" | 包含 Docker | ⏳ 待写 |

## 红-绿-重构循环计划

- [x] 循环 1: 修复代理问题 (T-001) ✅ 25/25 通过
- [x] 循环 2: FTS 服务测试 (T-002 ~ T-005) ✅ 15/15 通过
- [x] 循环 3: Memory Recall 规则路径测试 (T-006 ~ T-010) ✅ 16/16 通过
