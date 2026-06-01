# 2026-05-27 手撕代码模块 Bug 修复

**时间**：2026-05-27
**模块**：backend/app/routers/coding.py, backend/app/core/prompts.py, frontend/src/components/business/CodingPractice.vue

## 第一轮修复

### 问题
1. **流式输出无效**：后端将完整 LLM 响应（含 JSON 结构）一次性发送给前端
2. **请求提示按钮时序错误**：按钮只在提交评审出结果后才出现
3. **参考答案显示多余代码块标记**：LLM 返回的 reference_answer 含 ``` 包裹

### 修复
- Prompt 格式重构：先输出 feedback 正文，再 `---JSON---` 分隔符，再 JSON 结构
- 后端流式发送 feedback 部分，分隔符后的内容静默缓冲
- Hint 自动关联：无需 parent_submission_id，后端自动查找
- Hint 按钮始终显示
- 参考答案用 CodeEditor 语法高亮显示

## 第二轮修复（BUG-001/002/003）

### 问题
1. **输出重复**（BUG-001）：流式 chunk + 解析后 feedback_text 双重发送
2. **hint 显示评分**（BUG-002）：hint 模式不应显示评分面板
3. **提示不累积**（BUG-003）：第二次 hint 覆盖第一次

### 修复
- 后端 `replace: true` 标记 + `feedback_sent` 防重复
- hint 模式后端 `scores = {}`，前端只在 full_review 时显示评分
- hint 模式不清空 feedback，以 `---` 分隔追加显示

## 第三轮优化

### 改动
1. **三层提示 prompt 重写**（BUG-004）：严禁给出代码/伪代码，每层用面试官口吻引导
   - 第 1 次：方向性提示（引导思路）
   - 第 2 次：概念性提示（指出区域 + 算法引导）
   - 第 3 次：策略性提示（详细解释策略，仍不给代码）
2. **hint 次数限制**（BUG-005）：前端 hintCount 追踪，3 次后按钮禁用 + 提示"请提交评审"
3. **清空记录按钮**：重置本题所有状态（feedback、scores、hintCount）
4. **按钮功能说明**：hover tooltip 说明按钮用途
5. **按钮显示次数**：`请求提示 (x/3)`

## 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/app/core/prompts.py` | Prompt 格式重构 |
| `backend/app/routers/coding.py` | 流式逻辑 + hint 自动关联 + 防重复 + hint 不返回评分 |
| `frontend/src/components/business/CodingPractice.vue` | 按钮逻辑 + 参考答案 + hint 累积 + 评分条件显示 |

## 验证

- `uv run pytest backend/tests/test_coding.py -q` — 15/15 通过
- `cd frontend && npm run build` — 构建成功
- Docker 部署 — 全部容器健康
