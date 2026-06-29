# Constants — 应用常量

全局配置和枚举常量，无副作用，可安全 import。

## 文件清单

| 文件 | 职责 |
|------|------|
| `config.js` | 应用配置常量（API 路径、分页大小、SSE 重连、防抖延迟、侧边栏宽度等；部分宽度值为历史/全局配置，`useSidebar.js` 仍有局部交互常量） |
| `enums.js` | 业务枚举（题库模式、难度等级、Tab 名称、排序方式） |

## 常量清单

**config.js:**
- `API_BASE` — API 基础路径 `/api`
- `DEFAULT_PAGE_SIZE` / `MASTER_BANK_PAGE_SIZE` — 分页大小
- `SSE_RETRY_DELAY` — SSE 重连间隔
- `CACHE_TTL` — 请求缓存 TTL
- `SEARCH_DEBOUNCE` — 搜索防抖延迟
- `SIDEBAR_*_WIDTH` — 侧边栏宽度范围

**enums.js:**
- `BANK_MODE` — 题库模式（public/personal/mixed）
- `DIFFICULTY` / `DIFFICULTY_LABEL` — 难度等级及中文映射
- `TAB` — Tab 页名称
- `SORT` — 排序方式

## 核心规则

- 对象枚举使用 `Object.freeze()` 防止意外修改；基础配置值直接用 `export const`
- 枚举值用英文，中文标签通过 `*_LABEL` 映射
- 新增常量优先放在对应的文件中，不要新建文件除非语义完全不同

## 修改后必做

1. 新增常量后更新本文件的常量清单
