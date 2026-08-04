# Models — Pydantic Schemas

请求/响应体的 Pydantic v2 数据模型定义。

## 文件清单

| 文件 | 职责 |
|------|------|
| `schemas.py` | 所有 API 请求体 schema（批量删除、答案评估、配置更新、题目操作、代码提交等） |

## Schema 清单

| Schema | 用途 |
|--------|------|
| `GenericUpdateRequest` | 通用记录更新（table_name + record_id + update_data） |
| `BatchDataDeleteRequest` | 按类型批量删除 JD/面经 |
| `BatchDeleteRequest` | 按 ID 列表批量删除 |
| `BatchGenerateAnswersRequest` | 批量生成答案 |
| `EvaluateAnswerRequest` | 答案评估（question + user_answer + reference_answer） |
| `ProfileUpdateRequest` | 用户配置更新 |
| `SplitQuestionRequest` | 题目拆分 |
| `DeleteOriginalQuestionRequest` | 删除原始题目 |
| `MergeOriginalQuestionRequest` | 合并题目到目标 |
| `UploadToBankRequest` | 上传题目到题库 |
| `UpdateQuestionRequest` | 更新题目信息（分类/标签/难度） |
| `CodingSubmitRequest` | 手撕代码提交 |
| `CodingProblemCreateRequest` | 创建代码题目 |
| `DistributionPreferenceRequest` | 五类题型比例、题数与风格来源的保存/单场覆盖 schema |

## 核心规则

- Pydantic v2：用 `model_dump()` 不是 `.dict()`，`field_validator` 不是 `@validator`
- 新增字符串字段应尽量使用 `Field(..., max_length=...)` 约束；历史 schema 中仍有少量未加约束的字段，改动时可顺手补齐但不要引发兼容性破坏
- 新 schema 在此文件中添加，不要分散到多个文件
- routers 层通过 `Depends` 或直接类型注解使用这些 schema

## 修改后必做

1. 新增 schema 后更新本文件的 Schema 清单
