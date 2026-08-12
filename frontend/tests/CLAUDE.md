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
| `smoke/` | 冒烟测试（快速验证核心功能） |
| `diagnosis/` | 诊断/调试用 Playwright 测试和报告 |
| `_helpers/` | 测试辅助函数 |
| `playwright.config.js` | Playwright 配置 |

## 核心规则

- **默认 mock API**：常规 E2E 禁止依赖真实后端；诊断脚本需要真实页面时必须在文件名/说明里写清楚意图
- **禁止截图断言**：用文本/元素断言
- **禁止真实密码**：测试数据用 fake 值
- **测试先行**：先写失败测试，再写实现
- **Chat reasoning 断言**：模拟面试 reasoning E2E 应断言用户可见文案“面试官推理”，并覆盖 `reasoning_trace.source=model_reasoning` 时 `thinking` 优先于 summary 的展示；`ReasoningTimeline.vue` 的连线式 timeline 需断言 `.reasoning-timeline-connector` 存在

## 修改后必做

1. 运行测试确认通过
2. 更新本文件（如新增测试目录或改变规范）
