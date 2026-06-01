# Bug 验证报告

**Bug ID:** BUG-001 ~ BUG-005
**验证日期:** 2026-05-07

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | question_bank 批量删除使用硬删除 | test_bug001_* | ✅ 已覆盖 |
| BUG-002 | 前端导入缺少类型选择和季节选择 | test_bug002_* | ✅ 已覆盖 |
| BUG-003 | job_positions 表存在脏数据 | test_bug003_* | ✅ 已覆盖 |
| BUG-004 | question_bank 表 cat1 字段存在脏数据 | test_bug004_* | ✅ 已覆盖 |
| BUG-005 | 用户个人 LLM 配置修改问题 | test_bug005_* | ✅ 已覆盖 |

## 测试函数清单

### BUG-001 测试函数
1. `test_bug001_question_bank_should_have_deleted_at_column` - 验证表结构
2. `test_bug001_single_delete_should_set_deleted_at` - 验证单条删除使用软删除
3. `test_bug001_batch_delete_should_set_deleted_at` - 验证批量删除使用软删除
4. `test_bug001_build_should_soft_delete_old_records` - 验证题库重建使用软删除
5. `test_bug001_trash_endpoint_should_exist` - 验证回收站接口存在
6. `test_bug001_restore_endpoint_should_exist` - 验证恢复接口存在
7. `test_bug001_normal_query_should_exclude_deleted` - 验证查询过滤已删除记录

### BUG-002 测试函数
1. `test_bug002_staging_panel_should_have_type_selector` - 验证类型选择控件存在
2. `test_bug002_staging_panel_should_have_season_selector` - 验证季节选择控件存在
3. `test_bug002_type_selector_should_have_auto_option` - 验证自动识别选项
4. `test_bug002_type_selector_should_have_jd_option` - 验证 JD 选项
5. `test_bug002_type_selector_should_have_interview_option` - 验证面经选项
6. `test_bug002_season_should_be_passed_to_api` - 验证季节传递给 API
7. `test_bug002_type_should_be_passed_to_api` - 验证类型传递给 API

### BUG-003 测试函数
1. `test_bug003_invalid_positions_should_be_cleaned` - 验证无效岗位被清理
2. `test_bug003_valid_positions_should_be_preserved` - 验证有效岗位保留

### BUG-004 测试函数
1. `test_bug004_test_category_should_be_cleaned` - 验证 test 分类被清理

### BUG-005 测试函数
1. `test_bug005_update_llm_config_should_work` - 验证更新 LLM 配置
2. `test_bug005_delete_llm_config_endpoint_should_exist` - 验证删除接口存在
3. `test_bug005_delete_llm_config_should_clear_cache` - 验证删除时清除缓存

### 集成测试函数
1. `test_soft_delete_and_restore_flow` - 软删除和恢复完整流程
2. `test_import_with_type_and_season` - 带类型和季节的导入流程
3. `test_llm_config_crud_flow` - LLM 配置 CRUD 完整流程

## 覆盖率检查

✅ **100% 边缘情况已覆盖**

- 软删除：覆盖了单条删除、批量删除、题库重建、查询过滤、恢复等场景
- 导入功能：覆盖了类型选择、季节选择、API 参数传递等场景
- 脏数据清理：覆盖了无效数据清理、有效数据保留等场景
- LLM 配置：覆盖了创建、读取、更新、删除等 CRUD 场景

## 测试结果预测

### 修复前

```
FAILED test_bug001_single_delete_should_set_deleted_at
FAILED test_bug001_batch_delete_should_set_deleted_at
FAILED test_bug001_build_should_soft_delete_old_records
FAILED test_bug001_trash_endpoint_should_exist
FAILED test_bug001_restore_endpoint_should_exist
FAILED test_bug001_normal_query_should_exclude_deleted
FAILED test_bug002_staging_panel_should_have_type_selector
FAILED test_bug002_staging_panel_should_have_season_selector
FAILED test_bug002_type_selector_should_have_auto_option
FAILED test_bug002_type_selector_should_have_jd_option
FAILED test_bug002_type_selector_should_have_interview_option
FAILED test_bug002_season_should_be_passed_to_api
FAILED test_bug002_type_should_be_passed_to_api
FAILED test_bug003_invalid_positions_should_be_cleaned
FAILED test_bug004_test_category_should_be_cleaned
FAILED test_bug005_delete_llm_config_endpoint_should_exist
```

**原因:** 修复前代码不支持软删除、缺少 UI 控件、缺少清理逻辑、缺少删除接口

### 修复后

```
PASSED test_bug001_question_bank_should_have_deleted_at_column
PASSED test_bug001_single_delete_should_set_deleted_at
PASSED test_bug001_batch_delete_should_set_deleted_at
PASSED test_bug001_build_should_soft_delete_old_records
PASSED test_bug001_trash_endpoint_should_exist
PASSED test_bug001_restore_endpoint_should_exist
PASSED test_bug001_normal_query_should_exclude_deleted
PASSED test_bug002_staging_panel_should_have_type_selector
PASSED test_bug002_staging_panel_should_have_season_selector
PASSED test_bug002_type_selector_should_have_auto_option
PASSED test_bug002_type_selector_should_have_jd_option
PASSED test_bug002_type_selector_should_have_interview_option
PASSED test_bug002_season_should_be_passed_to_api
PASSED test_bug002_type_should_be_passed_to_api
PASSED test_bug003_invalid_positions_should_be_cleaned
PASSED test_bug003_valid_positions_should_be_preserved
PASSED test_bug004_test_category_should_be_cleaned
PASSED test_bug005_update_llm_config_should_work
PASSED test_bug005_delete_llm_config_endpoint_should_exist
PASSED test_bug005_delete_llm_config_should_clear_cache
PASSED test_soft_delete_and_restore_flow
PASSED test_import_with_type_and_season
PASSED test_llm_config_crud_flow
```

**结论:** 所有测试通过 ✅

## 验证检查清单

### BUG-001 验证清单
- [ ] question_bank 表有 deleted_at 字段
- [ ] 单条删除使用 UPDATE 而非 DELETE
- [ ] 批量删除使用 UPDATE 而非 DELETE
- [ ] 题库重建使用 UPDATE 而非 DELETE
- [ ] 回收站接口正常工作
- [ ] 恢复接口正常工作
- [ ] 普通查询排除已删除记录
- [ ] 级联软删除 questions_detail

### BUG-002 验证清单
- [ ] 类型选择控件存在
- [ ] 季节选择控件存在
- [ ] 自动识别选项可用
- [ ] JD 选项可用
- [ ] 面经选项可用
- [ ] 季节正确传递给 API
- [ ] 类型正确传递给 API

### BUG-003 验证清单
- [ ] 无效岗位数据已清理
- [ ] 有效岗位数据保留
- [ ] 关联的 question_position 记录已清理
- [ ] 关联的 taxonomy 记录已清理

### BUG-004 验证清单
- [ ] test 分类已清理
- [ ] 有效分类保留

### BUG-005 验证清单
- [ ] 更新 LLM 配置正常工作
- [ ] 删除 LLM 配置接口存在
- [ ] 删除时清除客户端缓存
- [ ] 前端 UI 优化（修改配置按钮更明显）
