# Questions Pkg — 题库操作子路由

从 `questions.py` 拆分的子模块，按职责组织。

## 子路由

| 文件 | 职责 |
|------|------|
| `mutations.py` | 聚类变异操作：拆分（split）、合并（merge）、重新打标（retag） |
| `bulk.py` | 批量操作：删除原始题目、删除聚类、批量删除、上传到题库 |

删除原始题目会删除对应 `questions_detail`，必须在删除前标记受影响公共面经的 distribution stats 为 stale；重新打标也必须重新映射其 canonical question type。

## 保留在 `questions.py` 的端点

- `_build_bank_where_clause` — 查询子句构造（被 `practice.py` 导入）
- `GET /api/master-bank` — 题库列表
- `GET /api/master-bank/{id}/detail` — 题目详情
- `GET /api/master-bank/search` — 搜索
- `PUT /api/master-bank/{id}` — 编辑题目

## 注册方式

`__init__.py` 合并所有子路由为一个总路由，在 `asgi.py` 中注册为 `questions_pkg_router`。

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/bank/ -q`
2. 更新本文件
