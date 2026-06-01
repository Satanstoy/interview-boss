# Bug 预览报告

**日期:** 2026-05-07
**问题:** 前端登录时显示"服务暂时不可用"
**严重程度:** Critical (P0) - 服务完全不可用

## 初步诊断

### 问题现象
用户在前端输入用户名和密码后，系统返回"服务暂时不可用"错误。

### 根本原因
后端服务无法启动，原因是 `backend/app/routers/master_bank.py` 文件第 922-954 行存在严重的 Python 缩进错误。

### 错误详情
```
File "/root/sj/interview-boss/backend/app/routers/master_bank.py", line 923
    nonlocal generated, failed, done_count
    ^
IndentationError: expected an indented block after function definition on line 922
```

### 影响范围
- **后端服务:** 完全无法启动
- **所有 API 端点:** 包括 `/api/auth/login` 在内均不可用
- **用户体验:** 所有功能失效

### 问题代码位置
- **文件:** `backend/app/routers/master_bank.py`
- **行号:** 922-954
- **函数:** `_gen_one` (异步生成器函数内的嵌套函数)

### 技术细节
`_gen_one` 函数定义后，其函数体（第 923-954 行）的缩进级别错误，应该比函数定义多一级缩进，但实际缩进与函数定义同级，导致 Python 解析器报错。

## 初步风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 服务中断 | Critical | 后端完全无法启动 |
| 数据完整性 | Low | 数据库未受影响 |
| 安全风险 | Low | 非安全漏洞 |

## 下一步行动

1. 修复 `master_bank.py` 中的缩进错误
2. 重启后端服务
3. 验证登录功能恢复正常
