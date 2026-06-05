# Tests — Bug 回归测试

每个已修复的 bug 对应一个测试文件，防止回归。

## 命名规范

- 文件：`test_bug_<slug>.py`
- Bug ID：`BUG-XXX` 格式
- 测试函数：`test_bug_xxx_should_pass_after_fix`

## 测试文件

| 文件 | Bug |
|------|-----|
| `test_agent_workflow_bugs.py` | BUG-005 ~ BUG-010（agent 工作流 bug） |

## 运行

```bash
docker compose exec backend uv run pytest backend/tests/bugs/ -q
```

## 修改后必做

1. 修复 bug 后必须在此目录添加回归测试
2. 更新本文件（如新增 bug 测试）
