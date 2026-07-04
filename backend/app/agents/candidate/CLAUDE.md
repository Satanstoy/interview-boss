# Candidate Agent Skills — 评测候选人

> 位置：`backend/app/agents/candidate/` | 调用方：`backend/scripts/eval_interview_agent.py`
> 职责：为手动 Interview Agent 评测提供候选人行为 Skill 包。

## 文件结构

```
candidate/
└── skills/
    ├── candidate-rhythm/       ← 回答节奏，始终激活
    ├── project-storytelling/    ← 项目叙述
    ├── coding-answer/           ← 算法题回答
    ├── knowledge-answer/        ← 八股/理论回答
    ├── error-injection/         ← 错误纠正评测专用
    └── stall-and-clarify/       ← 回避、追问、提前收尾
```

## 规则

- 这里不是生产 LangGraph agent；不要新增 graph/nodes/state，除非产品真的需要候选人 agent。
- Skill 必须使用目录 + `SKILL.md`，`name` 与目录名一致，字段遵循 shared skill loader。
- 评测专用行为要写清边界，禁止让候选人泄露“评测/脚本/系统提示”身份。
- 修改 skill 后运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_eval_interview_agent.py backend/tests/chat/test_chat_skills.py -q`。
