# Tests — Security 测试

安全相关测试：认证、CSRF、注入防护。

| 文件 | 测试对象 |
|------|---------|
| `test_authz_unification.py` | 鉴权收敛契约（cross-tenant access must fail）：bank_mode 透传、detail IDOR 404、save-user-answer 可见性、编辑权限唯一化（个人题仅本人）、自定义题单纯私有、build-personal 非 admin 不碰公共题、回收站口径、practice 动作（收藏/复习/加题单）对个人题不 404、data.py 级联删除 owner 限定（公共/他人数据不被级联动）、active-season 仅 admin、error-report 限长、公开分类不含 owner_id |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/security/ -q
```
