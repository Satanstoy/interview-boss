# Tests — Bank 测试

题库操作相关测试：模式过滤、CRUD、拆分合并。

## 测试文件

| 文件 | 测试对象 |
|------|---------|
| `test_bank_mode_cache.py` | 题库模式缓存 |
| `test_bank_mode_sql.py` | 题库模式 SQL 生成 |
| `test_cross_category_merge.py` | 跨分类合并 |
| `test_edit_question.py` | 编辑题目 |
| `test_master_bank_syntax.py` | 题库语法 |
| `test_oqs_backfill.py` | original_questions 回填 |
| `test_per_user_answers.py` | 用户级答案（生成权限：普通用户 403、管理员可生成）+ 背诵稿定制（generate-recitation：写个人答案、无参考答案 404、不可见题 404） |
| `test_rebuild_position_filter.py` | 岗位过滤重建 |
| `test_source_url_count_mismatch.py` | 来源 URL 计数不匹配 |
| `test_split_question_data_loss.py` | 拆分题目数据丢失 |
| `test_soft_delete_and_ux.py` | 软删除与 UX 行为 |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/bank/ -q
```
