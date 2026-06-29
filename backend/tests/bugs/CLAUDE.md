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
| `test_*position*.py` / `test_*frequency*.py` / `test_*source*.py` | 岗位、frequency、来源展示/统计等回归 |
| `test_reupload_after_soft_delete.py` / `test_soft_delete_and_ux.py` | 软删除与重复导入回归 |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/bugs/ -q
```

## 修改后必做

1. 修复 bug 后必须在此目录添加回归测试
2. 更新本文件（如新增 bug 测试）
