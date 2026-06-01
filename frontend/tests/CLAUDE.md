# Frontend Tests — 前端测试

Playwright E2E 测试。

## 命令

```bash
cd frontend
npx playwright test                # 全部测试
npx playwright test tests/e2e/     # E2E 测试
```

## 目录结构

| 目录 | 职责 |
|------|------|
| `e2e/` | 端到端测试（Playwright） |
| `diagnosis/` | 诊断测试 |
| `_helpers/` | 测试辅助函数 |

## 核心规则

- **必须 mock API**：禁止使用真实后端
- **禁止截图断言**：用文本/元素断言
- **禁止真实密码**：测试数据用 fake 值
- **测试先行**：先写失败测试，再写实现

## 修改后必做

1. 运行测试确认通过
2. 更新本文件（如新增测试目录或改变规范）
