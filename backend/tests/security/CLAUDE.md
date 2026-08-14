# Tests — Security 测试

安全相关测试：认证、CSRF、注入防护。

| 文件 | 测试对象 |
|------|---------|
| `test_authz_unification.py` | 鉴权收敛契约（cross-tenant access must fail）：bank_mode 透传、detail IDOR 404、save-user-answer 可见性、编辑权限唯一化（个人题仅本人）、自定义题单纯私有、build-personal 非 admin 不碰公共题、回收站口径、practice 动作（收藏/复习/加题单）对个人题不 404、data.py 级联删除 owner 限定（公共/他人数据不被级联动）、active-season 仅 admin、error-report 限长、公开分类不含 owner_id |
| `test_rate_limit_client_ip.py` | 限速 client-IP 隔离：`get_client_ip` 仅被可信代理时取 XFF；auth/email limiter `key_func` 必须是 `get_client_ip`（防 nginx 反代下全站共享限速桶）；asgi 全局 200/min 默认被中间件强制执行 |
| `test_login_form_csrf.py` | `/api/auth/login-form` 同源校验：`_is_same_origin_request` 拦截跨源 Origin/Referer，跨源表单 403（封堵锁定 DoS），同源放行 |
| `test_insights_owner_isolation.py` | insights `high_frequency` 跨租户隔离：他人私有面经的 cat2 主题不泄漏进当前用户聚合，本人主题可见 |
| `test_upload_size_guard.py` | 上传大小守卫（audit cf418f2）：audio transcribe 25MB / chat extract-pdf 10MB / resume upload 10MB 超限返回 413，且超限时下游服务与 `file.read()` 均不被触发（提前用 Content-Length 拦截，防读入放大）；变异验证已做（移除守卫后用例变红）。音频用例因 test-runtime 未装 `deepgram` 用 `@skipif` 跳过 |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/security/ -q
```
