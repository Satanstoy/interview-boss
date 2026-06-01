# 红灯阶段报告

**功能:** 注册强制绑定邮箱 + 登录检测邮箱绑定
**日期:** 2026-05-28

## 测试文件

`backend/tests/security/test_email_required.py`

## 测试策略

沿用现有 test_email_auth.py 模式：直接调用 endpoint 函数 + mock 依赖。先跑全部测试确认红灯，然后逐个实现。

## 预期失败原因

- T-001~004: RegisterRequest 还没有 email 字段
- T-005~006: login endpoint 还没有邮箱检测逻辑
- T-007~010: bind-email-with-token endpoint 尚未创建

## 状态

- [x] 测试代码已编写
- [ ] 测试运行失败（红色）
- [ ] 进入绿灯阶段
