# Tests — Security 测试

安全相关测试：认证、CSRF、注入防护。

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/security/ -q
```
