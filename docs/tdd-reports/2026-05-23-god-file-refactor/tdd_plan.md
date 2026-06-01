# TDD 开发计划

**功能名称:** God File 拆分重构
**日期:** 2026-05-23
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

将 backend 中行数过多的「皇帝代码」文件按职责拆分为多个小模块，保持 API 端点不变。

## 目标文件

| 文件 | 行数 | 拆分方案 |
|------|------|---------|
| `routers/profile.py` | 791 | → `profile/` 目录，按领域拆为 5 个子模块 |
| `routers/questions.py` | 1050 | → `questions/` 目录，拆出 mutations 模块 |
| `routers/submit.py` | 819 | → 清理旧版本 submit_data，保留 stream_v2 |

## 验收标准

- [ ] 所有现有 API 端点路径不变
- [ ] 所有现有测试继续通过
- [ ] 每个新模块 < 400 行
- [ ] 内部导入路径兼容（re-export）

## 拆分方案

### profile.py (791 → ~5 个文件)

```
routers/
├── profile/
│   ├── __init__.py        ← re-export 所有 router
│   ├── llm.py             ← LLM 配置 (get/update/delete)
│   ├── taxonomy.py        ← 分类体系管理
│   ├── position.py        ← 岗位管理
│   ├── email.py           ← 邮箱绑定
│   └── resume.py          ← 简历管理
└── profile.py             ← 保留公共 profile + 管理员 profile (~300 行)
```

### questions.py (1050 → ~3 个文件)

```
routers/
├── questions/
│   ├── __init__.py        ← re-export
│   ├── mutations.py       ← merge/split/retag (巨型函数)
│   └── bulk.py            ← batch_delete/delete_original
└── questions.py           ← 保留 CRUD + search (~500 行)
```

### submit.py (819 → 清理)

- 删除 `submit_data` (v1，已被 stream_v2 替代)
- 删除 `submit_data_stream` (中间版本)
- 保留 `submit_data_stream_v2` + `tag_questions_batch` + helpers

## 测试清单

| ID | 测试场景 | 预期输出 | 状态 |
|----|---------|----------|------|
| T-001 | profile 所有端点可访问 | 路由注册正确 | ⏳ 待写 |
| T-002 | questions 所有端点可访问 | 路由注册正确 | ⏳ 待写 |
| T-003 | _build_bank_where_clause 仍可从原路径导入 | 导入成功 | ⏳ 待写 |
| T-004 | submit 端点可访问 | 路由注册正确 | ⏳ 待写 |

## 红-绿-重构循环计划

- [ ] 循环 1: 写路由完整性测试（红灯）
- [ ] 循环 2: 拆分 profile.py（绿灯）
- [ ] 循环 3: 拆分 questions.py（绿灯）
- [ ] 循环 4: 清理 submit.py（绿灯）
- [ ] 循环 5: 全量回归测试
