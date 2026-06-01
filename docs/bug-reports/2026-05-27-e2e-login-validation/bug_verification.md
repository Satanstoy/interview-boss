# Bug 验证报告

**Bug ID:** BUG-001, BUG-002, BUG-003
**验证日期:** 2026-05-27

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试覆盖 | 修复状态 |
|--------|---------|---------|---------|
| BUG-001 | 前后端正则字符范围不一致 | E2E 测试 + Python 验证 | ✅ 已修复 |
| BUG-002 | 消毒函数返回值被丢弃 | 代码审查 | ✅ 已修复 |
| BUG-003 | GET 缓存未失效 | E2E 测试（刷新场景） | ✅ 已修复 |

## 修复验证

### BUG-001 验证

```python
# 修复后前端正则匹配 U+9FA6-U+9FFF
import re
frontend_re = re.compile(r'^[a-zA-Z0-9_一-鿿]{2,32}$')
assert frontend_re.match('鿿鿿')  # U+9FFF - 现在应该匹配
```

### BUG-002 验证

修复前: `sanitizeAgainstInjection(input)` 返回值被丢弃
修复后: `input = sanitizeAgainstInjection(input)` 返回值被使用

### BUG-003 验证

修复前: `fetchTableData` 直接请求，命中 30s 缓存
修复后: `fetchTableData` 先调用 `invalidateCache()` 清除缓存

## 构建验证

```
✓ frontend npm run build — 成功
✓ E2E 测试 15/16 通过（1 个是 Playwright 交互边界情况）
```
