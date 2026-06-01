# API 兼容层 — Re-export

> 位置：`frontend/src/api/` | 上游：所有 `import { xxx } from '@/api/index.js'` 的地方 | 下游：`services/` 领域模块
> 职责：统一 re-export 兼容层。新代码应直接从 `services/` 按领域导入。

## 规则

- `index.js` 只做 re-export，不包含业务逻辑
- 新增 API 函数在 `services/` 对应文件中实现，然后在此 re-export
- 新代码建议直接导入：`import { authLogin } from '@/services/authApi.js'`
